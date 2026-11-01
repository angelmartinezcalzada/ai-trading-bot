"""Swing strategies validated out-of-sample (research/research.py, robust.py):
 - breakout_4h : Donchian 4h, entry close > max(high,120 bars prev), exit close < min(low,40 bars prev), only if BTC 1d > SMA50
 - xs_rotation_4h: every 12x4h bars hold top-5 by 60-bar (10d) return, only if BTC 1d > SMA50
Signals always computed from Binance spot 4h candles (Coinbase has no 4h granularity); executed on the bot's own exchange."""
import time, logging, requests, numpy as np, pandas as pd, datetime as dt
log = logging.getLogger("bot")
API = "https://data-api.binance.vision/api/v3/klines"
BAR = 4*3600
def kl(sym, iv, n):
    k = requests.get(API, params=dict(symbol=sym, interval=iv, limit=n), timeout=15).json()
    if not isinstance(k, list) or len(k) < 3: return None
    d = pd.DataFrame(k).iloc[:, :5].astype(float); d.columns = ["t","o","h","l","c"]
    if d.t.iloc[-1]/1000 + (BAR if iv == "4h" else 86400) > time.time(): d = d.iloc[:-1]   # drop forming candle
    return d.reset_index(drop=True)
def bsym(bot, sym): return sym if bot.ex == "binance" else bot.m.base_of(sym) + "USDT"
def run(bot, px):
    c = bot.cfg; S = c["strategies"]; sc = c.get("swing", {})
    if not (S.get("breakout_4h") or S.get("xs_rotation_4h")): return
    bar = int(time.time()//BAR)
    if bot.cool.get("__swing_bar") == bar: return
    t0 = time.time()
    btc = kl("BTCUSDT", "1d", 80)
    if btc is None: return
    regime_on = btc.c.iloc[-1] > btc.c.rolling(sc.get("regime_sma_d", 50)).mean().iloc[-1]
    try:
        import news; ns = news.state()
        if ns.get("risk_off") and regime_on: regime_on = False; bot.log.info("swing: news risk-off -> no new entries") if hasattr(bot, "log") else None
    except Exception: pass
    uni = [s for s in bot.symbols if s in px][:sc.get("universe_top", 50)]
    data = {}
    for s in uni:
        try:
            d = kl(bsym(bot, s), "4h", 200)
            if d is not None and len(d) >= 130: data[s] = d
        except Exception: pass
    sigs = []
    # ---- breakout exits / entries ----
    if S.get("breakout_4h"):
        N, M = sc.get("bo_entry", 120), sc.get("bo_exit", 40)
        for s, p in list(bot.pos.items()):
            if p.get("strategy") != "breakout_4h" or s not in data: continue
            d = data[s]
            if d.c.iloc[-1] < d.l.iloc[-M-1:-1].min():
                b, a = bot.m.book(s); bot.close(s, b, a, "donchian_exit", px)
        for s, d in data.items():
            hh = d.h.iloc[-N-1:-1].max(); brk = d.c.iloc[-1] > hh
            sigs.append({"t": dt.datetime.now().strftime("%H:%M:%S"), "sym": s, "type": "breakout_4h", "strategy": "breakout_4h" if brk and regime_on else "-",
                         "side": 1 if brk and regime_on else 0, "chg5": round((d.c.iloc[-1]/hh-1)*100, 2), "vol": None, "rsi": None, "mtf": None, "rs": None})
            if not (brk and regime_on) or s in bot.pos or s in bot.pending: continue
            if sum(1 for p in bot.pos.values() if p.get("strategy") == "breakout_4h") >= sc.get("bo_max", 6): break
            enter(bot, s, px, "breakout_4h", sc.get("bo_size_pct", 0.08))
    # ---- cross-sectional rotation ----
    if S.get("xs_rotation_4h") and bar % sc.get("xs_rebalance_bars", 12) == 0:
        L, K = sc.get("xs_lookback", 60), sc.get("xs_top", 5)
        ret = {s: d.c.iloc[-1]/d.c.iloc[-L-1]-1 for s, d in data.items() if len(d) > L}
        top = sorted(ret, key=lambda k: -ret[k])[:K] if regime_on else []
        for s, p in list(bot.pos.items()):
            if p.get("strategy") == "xs_rotation_4h" and s not in top:
                b, a = bot.m.book(s); bot.close(s, b, a, "rotation_out", px)
        for s in top:
            sigs.append({"t": dt.datetime.now().strftime("%H:%M:%S"), "sym": s, "type": "xs_rotation_4h", "strategy": "xs_rotation_4h", "side": 1,
                         "chg5": round(ret[s]*100, 2), "vol": None, "rsi": None, "mtf": None, "rs": None})
            if s not in bot.pos and s not in bot.pending: enter(bot, s, px, "xs_rotation_4h", sc.get("xs_size_pct", 0.08))
    bot.signals += sigs; bot.signals = bot.signals[-200:]
    bot.cool["__swing_bar"] = bar
    log.info("[%s] SWING bar=%d regime_on=%s scanned=%d breakout_pos=%d rotation_pos=%d (%.0fs)", bot.ex, bar, regime_on, len(data),
             sum(1 for p in bot.pos.values() if p.get("strategy") == "breakout_4h"), sum(1 for p in bot.pos.values() if p.get("strategy") == "xs_rotation_4h"), time.time()-t0)
def enter(bot, s, px, strat, pct):
    size = min(bot.equity(px)*pct, bot.cash*0.99)
    if size < bot.cfg["min_order_quote"]: log.info("[%s] %s skip %s: no cash", bot.ex, strat, s); return
    b, a = bot.m.book(s)
    if (a-b)/a*100 > bot.cfg["max_spread_pct"]: return
    if bot.live:
        import live_cb; x = a; return live_cb.open_pos(bot, s, size, x*0.02, strat, 17.5, 1e9, 1e9, "swing", 1e9, 1)
    x = a*(1+bot.cfg["slippage_pct"]/100); bot.cash -= size
    # exits are rule-based in run(); disaster stop at -35%, no TP / time exit
    bot._fill(s, 1, size, x, bot.fee_t, x*0.02, strat, 17.5, 1e9, 1e9, "swing", 1e9, 1)
