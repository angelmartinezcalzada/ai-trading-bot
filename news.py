"""Real-time news/sentiment: RSS (CoinDesk, The Block, Decrypt, Cointelegraph), Binance announcements, Fear&Greed.
Keyword classifier -> importance (1-3), sentiment (-1..1), affected coins. Writes news.jsonl + news_state.json.
API used by bots: news.state() -> {risk_off, fng, items, coin_block{SYM:until}, coin_boost{SYM:until}}"""
import requests, json, time, re, threading, os, logging, html, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
D = os.path.dirname(os.path.abspath(__file__)); UA = {"User-Agent": "Mozilla/5.0"}; log = logging.getLogger("news")
RSS = {"CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/", "The Block": "https://www.theblock.co/rss.xml",
       "Decrypt": "https://decrypt.co/feed", "Cointelegraph": "https://cointelegraph.com/rss"}
NEG3 = r"hack(ed)?|exploit|drain(ed)?|stolen|bankrupt|insolven|halts? withdrawals|sec (sues|charges)|lawsuit against|ban(s|ned)? crypto|depeg|rug ?pull|delist|emergency"
NEG2 = r"crash|plunge|liquidat|outflow|selloff|sell-off|tumble|slump|probe|fraud|fine[sd]?|tariff|recession|rate hike|sanction"
POS3 = r"will list|(?<!black)(?<!short)(?<!check)(?<!de)lists?\b|(?<!de)listing|etf approv|approves? .*etf|launch(es)? on binance|strategic reserve"
POS2 = r"surge|rall(y|ies)|soar|record high|all-time high|inflow|partnership|adopt|rate cut|upgrade"
MACRO = r"binance|coinbase|exchange|fed\b|fomc|powell|cpi|inflation|tariff|sec\b|treasury|recession|war|etf"
NOT_TICKERS = {"SEC", "ETF", "US", "USA", "UK", "EU", "AI", "USD", "CEO", "CFO", "IPO", "AML", "KYC", "DOJ", "FBI", "IRS", "CPI", "FOMC", "GDP", "NFT", "DEX", "CEX", "DAO", "TVL", "ATH", "ETFS", "FED", "UAE"}
COINS = {"BTC": r"bitcoin|\bbtc\b", "ETH": r"ethereum|\beth\b|ether\b", "SOL": r"solana|\bsol\b", "XRP": r"\bxrp\b|ripple", "BNB": r"\bbnb\b",
         "DOGE": r"dogecoin|\bdoge\b", "ADA": r"cardano|\bada\b", "AVAX": r"avalanche|\bavax\b", "LINK": r"chainlink|\blink\b", "SUI": r"\bsui\b"}
def classify(title, src):
    t = title.lower(); imp = 1; sent = 0.0
    if re.search(NEG3, t): sent -= 1; imp = 3
    elif re.search(NEG2, t): sent -= .5; imp = max(imp, 2)
    if re.search(POS3, t) and not re.search(r"delist", t): sent += 1; imp = 3
    elif re.search(POS2, t): sent += .5; imp = max(imp, 2)
    coins = [k for k, r in COINS.items() if re.search(r, t)]
    m = re.findall(r"\(([A-Z0-9]{2,10})\)", title); coins += [x for x in m if x not in coins and x not in NOT_TICKERS]
    macro = bool(re.search(MACRO, t)) or "BTC" in coins
    return dict(imp=imp, sent=max(-1, min(1, sent)), coins=coins, macro=macro)
class News:
    def __init__(s): s.items = {}; s.fng = None; s.lock = threading.Lock(); s.sources_ok = {}; s.load()
    def load(s):
        try:
            for l in open(f"{D}/news.jsonl"):
                r = json.loads(l); s.items[r["id"]] = r
        except Exception: pass
    def add(s, src, title, ts, url):
        title = html.unescape(title or "").strip(); k = f"{src}|{title}"
        if not title or k in s.items: return
        r = dict(id=k, src=src, title=title, ts=ts, url=url, seen=time.time(), **classify(title, src)); s.items[k] = r
        open(f"{D}/news.jsonl", "a").write(json.dumps(r) + "\n")
        if r["imp"] >= 2: log.info("NEWS [%s] imp=%d sent=%+.1f %s %s", src, r["imp"], r["sent"], r["coins"], title[:120])
    def poll(s):
        for src, u in RSS.items():
            try:
                x = ET.fromstring(requests.get(u, headers=UA, timeout=15).content)
                for it in x.iter("item"):
                    try: ts = parsedate_to_datetime(it.findtext("pubDate")).timestamp()
                    except Exception: ts = time.time()
                    s.add(src, it.findtext("title"), ts, it.findtext("link"))
                s.sources_ok[src] = time.time()
            except Exception as e: log.warning("news %s: %s", src, e)
        try:
            d = requests.get("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=10", headers=UA, timeout=15).json()
            for cat in d["data"]["catalogs"]:
                if cat["catalogName"] in ("New Cryptocurrency Listing", "Delisting"):
                    for a in cat["articles"]: s.add("Binance", a["title"], a["releaseDate"]/1000, "https://www.binance.com/en/support/announcement/" + a["code"])
            s.sources_ok["Binance"] = time.time()
        except Exception as e: log.warning("news binance: %s", e)
        try:
            f = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()["data"][0]; s.fng = dict(value=int(f["value"]), label=f["value_classification"]); s.sources_ok["Fear&Greed"] = time.time()
        except Exception as e: log.warning("news fng: %s", e)
        s.save()
    def state(s, now=None):
        now = now or time.time(); rec = [r for r in s.items.values() if now - r["ts"] < 6*3600]
        risk_off = any(r["imp"] >= 3 and r["sent"] < 0 and r["macro"] and now-r["ts"] < 2*3600 for r in rec) or (s.fng and s.fng["value"] <= 15)
        block = {c: r["ts"]+6*3600 for r in rec if r["sent"] < 0 and r["imp"] >= 2 for c in r["coins"]}
        boost = {c: r["ts"]+6*3600 for r in rec if r["sent"] > 0 and r["imp"] >= 3 for c in r["coins"]}
        top = sorted([r for r in rec if r["imp"] >= 2], key=lambda r: -r["ts"])[:12]
        sent = sum(r["sent"]*r["imp"] for r in rec)/max(1, sum(r["imp"] for r in rec))
        return dict(risk_off=bool(risk_off), fng=s.fng, sentiment=round(sent, 3), coin_block=block, coin_boost=boost, n_6h=len(rec),
                    top=[{k: r[k] for k in ("src", "title", "ts", "imp", "sent", "coins", "url")} for r in top], sources_ok={k: round(v) for k, v in s.sources_ok.items()})
    def save(s): json.dump(s.state(), open(f"{D}/news_state.json", "w"))
_N = None
def start(every=120):
    global _N
    if _N: return _N
    _N = News()
    def loop():
        while True:
            try: _N.poll()
            except Exception as e: log.warning("news loop %s", e)
            time.sleep(every)
    threading.Thread(target=loop, daemon=True).start(); return _N
def state():
    """read the shared file (written by whichever process polls)"""
    try: return json.load(open(f"{D}/news_state.json"))
    except Exception: return dict(risk_off=False, coin_block={}, coin_boost={}, top=[], fng=None, sentiment=0)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO); n = News(); n.poll(); st = n.state(); print(json.dumps({k: v for k, v in st.items() if k != "top"}, indent=1))
    for r in st["top"]: print(r["src"], r["imp"], r["sent"], r["coins"], r["title"][:90])
