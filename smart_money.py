"""Smart-money / insider-flow module (SHADOW). Legal on-chain data only: GeckoTerminal public pool trades + Jupiter token info.
- profile(): wallets consistently profitable across recent memecoin pools (realized + marked PnL, >=3 tokens, win-rate, bot filter)
- signals(pair, mint, entry_t): smart wallets buying now, dev wallet selling, early-buyer exit, whale net flow
Nothing here changes trades until validated (research/smart_eval.py)."""
import json, time, os, datetime as dt, requests, collections, logging
log = logging.getLogger("smart"); H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
F_W = "smart_wallets.json"; F_LOG = "research/smart_shadow.jsonl"; _last = [0.0]
def _gk(path):
    for i in range(3):
        dt_ = time.time()-_last[0]
        if dt_ < 2.1: time.sleep(2.1-dt_)          # GeckoTerminal free tier ~30 req/min
        _last[0] = time.time()
        try:
            r = requests.get("https://api.geckoterminal.com/api/v2/networks/solana/"+path, headers=H, timeout=15)
            if r.status_code == 429: time.sleep(10*(i+1)); continue
            r.raise_for_status(); return r.json()
        except Exception: time.sleep(2)
    return {}
def trades(pair):
    out = []
    for t in _gk(f"pools/{pair}/trades").get("data", []):
        a = t["attributes"]
        out.append(dict(ts=dt.datetime.fromisoformat(a["block_timestamp"].replace("Z", "+00:00")).timestamp(), w=a["tx_from_address"], kind=a["kind"],
                        usd=float(a.get("volume_in_usd") or 0), px=float((a.get("price_to_in_usd") if a["kind"] == "buy" else a.get("price_from_in_usd")) or 0),
                        qty=float((a.get("to_token_amount") if a["kind"] == "buy" else a.get("from_token_amount")) or 0)))
    return sorted(out, key=lambda x: x["ts"])
def wallet_pnl(tr):
    """per-wallet PnL on one pool: realized on sells + remaining tokens marked at the last price"""
    if not tr: return {}
    last = tr[-1]["px"]; W = collections.defaultdict(lambda: dict(b=0., s=0., qb=0., qs=0., n=0))
    for t in tr:
        w = W[t["w"]]; w["n"] += 1
        if t["kind"] == "buy": w["b"] += t["usd"]; w["qb"] += t["qty"]
        else: w["s"] += t["usd"]; w["qs"] += t["qty"]
    out = {}
    for a, w in W.items():
        if w["b"] < 20 or w["n"] > 40: continue          # dust and bots/market makers out
        rem = max(0, w["qb"]-w["qs"]); out[a] = w["s"] + rem*last - w["b"]
    return out
def profile(pairs, min_tokens=3, min_wr=0.6, min_pnl=300):
    agg = collections.defaultdict(lambda: dict(pnl=0., n=0, wins=0))
    for p in pairs:
        for a, v in wallet_pnl(trades(p)).items():
            g = agg[a]; g["pnl"] += v; g["n"] += 1; g["wins"] += v > 0
    smart = {a: dict(pnl=round(g["pnl"], 1), n=g["n"], wr=round(g["wins"]/g["n"], 2)) for a, g in agg.items()
             if g["n"] >= min_tokens and g["wins"]/g["n"] >= min_wr and g["pnl"] >= min_pnl}
    json.dump(dict(t=time.time(), pools=len(pairs), wallets_seen=len(agg), smart=smart), open(F_W, "w"))
    log.info("[smart] profile: %d pools, %d wallets, %d smart", len(pairs), len(agg), len(smart)); return smart
def load():
    try: return json.load(open(F_W)).get("smart", {})
    except Exception: return {}
def signals(pair, dev=None, entry_t=None, smart=None, whale_usd=3000, win=1800):
    smart = smart if smart is not None else load(); tr = trades(pair); now = time.time(); rec = [t for t in tr if now-t["ts"] <= win]
    sb = {t["w"] for t in rec if t["kind"] == "buy" and t["w"] in smart}; ss = {t["w"] for t in rec if t["kind"] == "sell" and t["w"] in smart}
    early = []
    for t in tr:
        if t["kind"] == "buy" and t["w"] not in early and (entry_t is None or t["ts"] <= entry_t): early.append(t["w"])
        if len(early) >= 20: break
    es = {t["w"] for t in rec if t["kind"] == "sell" and t["w"] in early}
    dev_sell = round(sum(t["usd"] for t in rec if t["kind"] == "sell" and dev and t["w"] == dev), 1)
    wb = sum(t["usd"] for t in rec if t["kind"] == "buy" and t["usd"] >= whale_usd); ws = sum(t["usd"] for t in rec if t["kind"] == "sell" and t["usd"] >= whale_usd)
    return dict(smart_buyers=len(sb), smart_sellers=len(ss), early_sellers=len(es), early_n=len(early), dev_sell_usd=dev_sell,
                whale_net_usd=round(wb-ws), px=tr[-1]["px"] if tr else None, n_trades=len(rec))
def shadow_log(rec):
    os.makedirs("research", exist_ok=True)
    with open(F_LOG, "a") as f: f.write(json.dumps(rec)+"\n")
