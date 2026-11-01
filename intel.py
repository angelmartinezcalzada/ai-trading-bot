"""Pro layer: market regime, S/R, MTF confluence, order book, relative strength, news & sentiment."""
import time, re, logging, requests, numpy as np
import xml.etree.ElementTree as ET
log = logging.getLogger("bot")
POS = "surge rally soar breakout bullish partnership launch listing list adopt approve upgrade record gain jump etf inflow integrat".split()
NEG = "hack exploit delist crash plunge bearish lawsuit sue sec fraud scam dump outflow halt ban investigat drop fall liquidat".split()
H = {"User-Agent": "Mozilla/5.0"}

def ema(x, n): return x.ewm(span=n, adjust=False).mean()

def regime(m):
    """BTC 1h/4h: bull / bear / range + volatility state."""
    from features import atr
    d4, d1 = m.klines(m.btc, "4h", 120), m.klines(m.btc, "1h", 300)
    c4, c1 = d4.c, d1.c
    e50, e200 = ema(c1, 50).iloc[-1], ema(c1, 200).iloc[-1]
    slope = ema(c4, 20).iloc[-1] / ema(c4, 20).iloc[-6] - 1
    vol = atr(d1).iloc[-1] / c1.iloc[-1] * 100
    if c1.iloc[-1] > e50 > e200 and slope > 0.003: r = "bull"
    elif c1.iloc[-1] < e50 < e200 and slope < -0.003: r = "bear"
    else: r = "range"
    return {"regime": r, "btc_vol_pct": round(vol, 2), "btc_slope4h": round(slope*100, 2), "btc_chg1h": c1.iloc[-1]/c1.iloc[-2]-1}

def sr_levels(df, win=5, n=6):
    """Swing-high/low pivot levels (support/resistance)."""
    h, l = df.h.values, df.l.values
    res = [h[i] for i in range(win, len(h)-win) if h[i] == h[i-win:i+win+1].max()]
    sup = [l[i] for i in range(win, len(l)-win) if l[i] == l[i-win:i+win+1].min()]
    return sorted(sup)[-n:], sorted(res)[:n] if False else sorted(res)[-n:]

def volume_poc(df, bins=24):
    """Point of control of a volume profile."""
    hist, edges = np.histogram((df.h+df.l+df.c)/3, bins=bins, weights=df.v)
    i = hist.argmax(); return (edges[i]+edges[i+1])/2

def book_imbalance_lv(bids, asks):
    b = sum(float(p)*float(q) for p, q in bids); a = sum(float(p)*float(q) for p, q in asks)
    return (b-a)/(b+a) if b+a else 0.0

def book_imbalance(m, sym, depth=20):
    ob = m.get("/api/v3/depth", symbol=sym, limit=depth)
    b = sum(float(p)*float(q) for p, q in ob["bids"]); a = sum(float(p)*float(q) for p, q in ob["asks"])
    return (b - a) / (b + a) if b + a else 0.0

class Sentiment:
    def __init__(s, ttl=600): s.ttl, s.t, s.fng, s.heads, s.delist, s.listings = ttl, 0, 50, [], set(), set()
    def refresh(s, force=False):
        if not force and time.time() - s.t < s.ttl: return
        s.t = time.time()
        try: s.fng = int(requests.get("https://api.alternative.me/fng/?limit=1", timeout=8).json()["data"][0]["value"])
        except Exception as e: log.warning("F&G fail %s", e)
        heads = []
        for u in ["https://cointelegraph.com/rss", "https://www.coindesk.com/arc/outboundfeeds/rss/", "https://decrypt.co/feed"]:
            try:
                r = requests.get(u, headers=H, timeout=8, allow_redirects=True)
                heads += [i.findtext("title") or "" for i in ET.fromstring(r.content).iter("item")]
            except Exception as e: log.warning("RSS fail %s %s", u, e)
        s.heads = heads
        def titles(cat):
            j = requests.get("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
                             params={"type": 1, "catalogId": cat, "pageNo": 1, "pageSize": 20}, headers=H, timeout=8).json()
            return [a["title"] for c in j["data"]["catalogs"] for a in c["articles"]]
        try:   # spot token delistings only: "Binance Will Delist EPIC, QUICK on 2026-10-28"
            d = set()
            for ti in titles(161):
                mm = re.match(r"Binance Will Delist (.+?) on \d{4}-\d{2}-\d{2}", ti)
                if mm: d |= {x for x in re.split(r",\s*|\s+and\s+", mm.group(1)) if re.fullmatch(r"[A-Z0-9]{2,12}", x)}
            s.delist = d
        except Exception as e: log.warning("delist fetch fail %s", e)
        try:   # new spot listings: "Binance Will List Foo (FOO) ..."
            s.listings = {x for ti in titles(48) if re.search(r"Will List|Will Add", ti) for x in re.findall(r"\(([A-Z0-9]{2,12})\)", ti)}
        except Exception as e: log.warning("listing fetch fail %s", e)
        log.info("SENTIMENT F&G=%d headlines=%d delist_flags=%d new_listings=%s", s.fng, len(s.heads), len(s.delist), sorted(s.listings)[:10])
    def coin(s, base, name_aliases=()):
        keys = {base.lower(), *[a.lower() for a in name_aliases]}
        sc = 0
        for t in s.heads:
            tl = t.lower(); words = set(re.findall(r"[a-z0-9]+", tl))
            if keys & words:
                sc += sum(w in tl for w in POS) - 1.5 * sum(w in tl for w in NEG)
        return max(-3, min(3, sc))
    def market_mult(s):
        """Extreme fear: smaller; greed ok; extreme greed: smaller (blow-off risk)."""
        f = s.fng
        return 0.5 if f < 20 else 0.8 if f < 35 else 1.0 if f < 75 else 0.7
