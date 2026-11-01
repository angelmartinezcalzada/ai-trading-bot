"""Collect Solana AI-narrative pools from GeckoTerminal search + 1m OHLCV (up to 3 pages of 1000 bars). -> research/ai_paths.json"""
import requests, json, time, os
H = {"Accept": "application/json"}; G = "https://api.geckoterminal.com/api/v2"
def get(u, **p):
    for _ in range(3):
        time.sleep(2.2)
        try:
            r = requests.get(u, params=p, headers=H, timeout=20)
            if r.status_code == 429: time.sleep(20); continue
            return r.json()
        except Exception: pass
OUT = "research/ai_paths.json"; D = json.load(open(OUT)) if os.path.exists(OUT) else {}
pools = {}
for q in ["ai", "agent", "gpt", "neural", "agi", "bot", "llm", "aixbt", "sentient", "robot", "cyber", "brain", "deepseek", "grok", "openai", "claude", "virtual"]:
    for page in (1, 2):
        d = get(f"{G}/search/pools", query=q, network="solana", page=page) or {}
        for p in d.get("data", []):
            a = p["attributes"]; liq = float(a.get("reserve_in_usd") or 0); vol = float((a.get("volume_usd") or {}).get("h24") or 0)
            if liq >= 30000 and vol >= 20000: pools[p["attributes"]["address"]] = dict(name=a["name"], liq=liq, vol24=vol, created=a.get("pool_created_at"))
print("pools", len(pools), flush=True)
for addr, meta in list(pools.items())[:90]:
    if addr in D: continue
    bars = []; before = None
    for _ in range(3):
        p = dict(aggregate=1, limit=1000, currency="usd"); 
        if before: p["before_timestamp"] = before
        d = get(f"{G}/networks/solana/pools/{addr}/ohlcv/minute", **p)
        try: rows = d["data"]["attributes"]["ohlcv_list"]
        except Exception: break
        if not rows: break
        bars += rows; before = min(r[0] for r in rows)
        if len(rows) < 1000: break
    if bars: D[addr] = dict(meta, bars=sorted({b[0]: b[:6] for b in bars}.values()))
    json.dump(D, open(OUT, "w"))
print("done", len(D), sum(len(v["bars"]) for v in D.values()))
