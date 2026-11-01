"""Solana Tracker signal. Shadow logging + LIVE veto/priority via live_check() (owner OK 01-nov 00:49).
Endpoints: GET /tokens/{mint} (risk: snipers/bundlers/insiders/dev %, holders, pools, events),
           GET /deployer/{wallet} (creator's past tokens), GET /price?token={mint} (forward prices).
Budget: <=1 req/1.2s, daily cap DAILY_CAP, token cache 15 min, deployer cache 6 h, price cache 5 min.
Failure/missing key => neutral (None)."""
import os, json, time, urllib.request
BASE = "https://data.solanatracker.io"
DAILY_CAP = int(os.environ.get("ST_DAILY_CAP", "300"))   # 01-nov: free plan ~10k/month = ~330/day; 400 exhausted the month early and the ALT gate went neutral all day
CACHE_F = "data/st_cache.json"; SHADOW_F = "data/st_shadow.jsonl"; BUDGET_F = "data/st_budget.json"
TTL = {"tokens": 3600, "deployer": 86400, "price": 300}   # 01-nov: longer cache (risk/creator data moves slowly)
DAEMON_CAP = int(os.environ.get("ST_DAEMON_CAP", "60"))   # shadow daemon may not starve the live bot (research only: the bot keeps >= 240/day)
OWNER = ["bot"]
VETO_PCT = 22.0
_last = [0.0]

def _key():
    k = os.environ.get("SOLANATRACKER_API_KEY")
    if not k and os.path.exists("keys.env"):
        for ln in open("keys.env"):
            if ln.startswith("SOLANATRACKER_API_KEY="): k = ln.split("=", 1)[1].strip()
    return k

def _load(f, d):
    try: return json.load(open(f))
    except Exception: return d

def _dump(o, f):
    t = f"{f}.{os.getpid()}.tmp"; json.dump(o, open(t, "w")); os.replace(t, f)   # atomic: shared by bot + shadow daemon

def _budget_ok():
    b = _load(BUDGET_F, {}); day = time.strftime("%Y-%m-%d")
    if b.get("day") != day: b = {"day": day, "n": 0}
    if b["n"] >= DAILY_CAP: return False
    if OWNER[0] == "daemon" and b.get("nd", 0) >= DAEMON_CAP: return False
    b["n"] += 1; b["nd"] = b.get("nd", 0) + (OWNER[0] == "daemon"); _dump(b, BUDGET_F); return True

def get(path, kind, cache=None):
    cache = cache if cache is not None else _load(CACHE_F, {})
    e = cache.get(path)
    if e and time.time() - e["t"] < TTL[kind]: return e["d"]
    k = _key()
    if not k or not _budget_ok(): return None
    w = 1.2 - (time.time() - _last[0])
    if w > 0: time.sleep(w)
    _last[0] = time.time()
    try:
        r = urllib.request.Request(BASE + path, headers={"x-api-key": k, "User-Agent": "st-shadow"})
        d = json.load(urllib.request.urlopen(r, timeout=15))
    except Exception:
        return None
    cache[path] = {"t": time.time(), "d": d}
    if len(cache) > 3000:
        for p in sorted(cache, key=lambda p: cache[p]["t"])[:1000]: cache.pop(p)
    _dump(cache, CACHE_F); return d

def features(tok, dep=None, now=None):
    """Pure: extract features from /tokens and /deployer responses."""
    if not tok or "risk" not in tok: return None
    now = now or time.time(); r = tok["risk"]
    pct = lambda k: float((r.get(k) or {}).get("totalPercentage") or 0)
    f = {"snipers": pct("snipers"), "bundlers": pct("bundlers"), "insiders": pct("insiders"),
         "dev": float((r.get("dev") or {}).get("percentage") or 0), "top10": float(r.get("top10") or 0),
         "st_rugged": bool(r.get("rugged")), "st_score": r.get("score"), "holders": tok.get("holders"),
         "buys": tok.get("buys"), "sells": tok.get("sells")}
    pools = tok.get("pools") or []
    f["liq"] = max([((p.get("liquidity") or {}).get("usd") or 0) for p in pools] or [0])
    f["price"] = max([((p.get("price") or {}).get("usd") or 0) for p in pools] or [0])
    f["migrated"] = any((p.get("market") or "") in ("pumpfun-amm", "raydium", "meteora-dyn-v2", "raydium-cpmm", "meteora-damm-v2") for p in pools)
    ct = ((tok.get("token") or {}).get("creation") or {}).get("created_time")
    f["age_h"] = round((now - ct) / 3600, 2) if ct else None
    f["creator"] = ((tok.get("token") or {}).get("creation") or {}).get("creator")
    if dep and isinstance(dep.get("data"), list):
        past = [t for t in dep["data"] if t.get("mint") != (tok.get("token") or {}).get("mint")]
        dead = [t for t in past if (t.get("liquidityUsd") or 0) < 100 and (now * 1000 - (t.get("createdAt") if t.get("createdAt") is not None else now * 1000)) > 3600e3]
        f["creator_tokens"] = len(past); f["creator_rugs"] = len(dead)
    else:
        f["creator_tokens"] = f["creator_rugs"] = None
    return f

def decide(f):
    """Shadow decision: (verdict, reasons, prio). verdict in pass/reject/neutral."""
    if f is None: return "neutral", ["no_data"], 0
    why = []
    conc = f["snipers"] + f["bundlers"] + f["dev"]
    if conc > VETO_PCT: why.append(f"conc{conc:.1f}%")
    if f["insiders"] > VETO_PCT: why.append(f"insiders{f['insiders']:.1f}%")
    if f["creator_rugs"] and (f["creator_rugs"] >= 3 and f["creator_rugs"] / max(1, f["creator_tokens"]) >= 0.5):
        why.append(f"creator_rugs{f['creator_rugs']}/{f['creator_tokens']}")
    if f["st_rugged"]: why.append("st_rugged")
    prio = 0
    if f["migrated"] and (f["age_h"] or 99) < 6 and (f["holders"] or 0) >= 300 and (f["buys"] or 0) > (f["sells"] or 0):
        prio = 1
    return ("reject" if why else "pass"), why, prio

def shadow(mint, live=None, sym=None):
    tok = get(f"/tokens/{mint}", "tokens")
    f = features(tok) if tok else None
    if f and f.get("creator"):
        f = features(tok, get(f"/deployer/{f['creator']}", "deployer"))
    v, why, prio = decide(f)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "mint": mint, "sym": sym,
           "verdict": v, "why": why, "prio": prio, "live": live, "f": f}
    with open(SHADOW_F, "a") as fh: fh.write(json.dumps(rec) + "\n")
    return rec

PRIO_BONUS = 3.0
def live_check(mint, sym=None):
    """LIVE: (veto_reasons, score_bonus, rec). Only tightens. No key / API error / budget out -> ([], 0, None) neutral."""
    try:
        rec = shadow(mint, live={"from": "memebot"}, sym=sym)
        if rec["verdict"] == "neutral": return [], 0.0, rec
        return ["st_" + w for w in rec["why"]], (PRIO_BONUS if rec["prio"] and rec["verdict"] == "pass" else 0.0), rec
    except Exception:
        return [], 0.0, None
