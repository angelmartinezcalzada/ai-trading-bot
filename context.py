"""Hourly MARKET CONTEXT: one snapshot shared by the bot, the brain, the Director, the operator and the panel.

Writes data/context_now.json (atomic) and appends one line per run to data/context.jsonl (schema code 'context/1').
Nothing here ever trades. Every field that cannot be computed is null and its dotted name goes to 'stale' (fail-closed:
unknown stays unknown, never a pass). Inputs: Binance public klines (SOL/BTC 1h) and SOL ticker, GeckoTerminal new_pools
page 1, the Solana RPC priority fees, and the local state files the other modules already write (news_state.json,
status_binance.json, state/trend_status.json, data/hl_risk.json, insider_status.json, data/st_budget.json, data/x_buzz.json,
brain_state.json, director_state.json, candidates_solana.jsonl). All network calls are injectable (fetch={...} or the
module-level FETCH) so tests run offline.

Usage (from the repo root):  python3 context.py --once | --loop | --show
API:  gather(root, now, fetch) -> raw;  build(raw, history, now) -> snapshot;  write(snapshot, root);  load(root, max_age)
      stamp(snapshot, thr, score_adj, size_mult, equity, n_pos, now) -> rec['ctx'];  signals(ctx) -> bools;  keys(ctx) -> tuple
      (signals / keys accept the full snapshot OR the compact rec['ctx'] stamp)"""
import calendar, json, math, os, statistics, sys, time

CODE = "context/1"
NOW_F, HIST_F = "data/context_now.json", "data/context.jsonl"
HIST_MAX, HIST_KEEP = 20_000, 10_000            # jsonl bound: rewrite with the last HIST_KEEP lines when longer than HIST_MAX
HIST_TAIL = 4_000_000                           # bytes of data/context.jsonl an hourly run reads (> 7 days even at a 5-min period)
TAIL_CAP, TAIL_MAX = 300_000, 8_000_000         # candidates_solana.jsonl byte tail: 300 KB like dash_data, grown x4 (max 8 MB) only while it does not reach back one hour
REGIME_MAX_AGE = 900                            # status_binance.json older than this -> btc_on unknown
BREADTH_MAX_AGE = 2 * 86400                     # trend_status.json older than this -> breadth unknown
HL_MAX_AGE = 7200                               # hl_risk.json 'updated' older than this -> biases / stress unknown (same freshness as the panel)
NEWS_SRC_FRESH = 6 * 3600                       # a news source counts as ok when it answered within this window
HIST_TOL = 1500                                 # s: a history sample counts as "the hour before" if within this tolerance
HEAT_MIN_SAMPLES, HEAT_HOT, HEAT_COLD = 3, 1.5, 0.5
TREND_UP, TREND_DOWN = 2.0, -4.0                # sol_trend on r24h (%)
GRAD_DEXES = ("pumpswap", "raydium", "meteora")
JUP = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
RPC = os.environ.get("SOLANA_RPC") or "https://api.mainnet-beta.solana.com"
FETCH = None                                    # module-level override of the fetchers (tests / CLI without network)
TIMEOUT = 10
STAMP_KEYS = ("ts", "age_s", "sol_24h", "sol_4h", "sol_trend", "btc_on", "risk_off", "fng", "heat", "heat_ratio", "new_pools_1h", "breadth",
              "hour_utc", "dow", "thr", "score_adj", "size_mult", "equity", "n_pos")
SIGNAL_KEYS = ("sol_up", "sol_down", "btc_on", "risk_off", "fear_extreme", "heat_hot", "heat_cold", "launches_hi", "breadth_hi", "night_utc", "weekend")


# ----------------------------------------------------------------------------------------------------------- fetchers
def _get(url, **params):
    import requests
    r = requests.get(url, params=params or None, timeout=TIMEOUT, headers={"accept": "application/json"}); r.raise_for_status(); return r.json()

def _f_sol_price():
    return float(_get("https://api.binance.com/api/v3/ticker/price", symbol="SOLUSDT")["price"])

def _f_klines(sym):
    return _get("https://api.binance.com/api/v3/klines", symbol=sym, interval="1h", limit=25)

def _f_gecko_new_pools():
    return _get("https://api.geckoterminal.com/api/v2/networks/solana/new_pools", page=1).get("data") or []

def _f_prio_fees():
    """median non-zero microlamports/CU recently paid on Jupiter's program (public RPC); informational only"""
    import requests
    r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getRecentPrioritizationFees", "params": [[JUP]]}, timeout=TIMEOUT)
    v = [int(x["prioritizationFee"]) for x in r.json()["result"] if int(x.get("prioritizationFee") or 0) > 0]
    return int(statistics.median(v)) if v else 0

DEFAULT_FETCH = {"sol_price": _f_sol_price, "btc_klines": lambda: _f_klines("BTCUSDT"), "sol_klines": lambda: _f_klines("SOLUSDT"),
                 "gecko_new_pools": _f_gecko_new_pools, "prio_fees": _f_prio_fees}


# ------------------------------------------------------------------------------------------------------------ helpers
def _num(x):
    if isinstance(x, bool): return None
    try:
        v = float(x); return v if math.isfinite(v) else None
    except Exception: return None

def _epoch(s, utc=False):
    """epoch | ISO with Z/offset | naive ISO ('2026-10-31T12:00:00': local time like candidates_solana.jsonl, or UTC when utc=True) -> epoch; else None"""
    if isinstance(s, bool): return None
    if isinstance(s, (int, float)): return _num(s)
    if not isinstance(s, str) or not s.strip(): return None
    s = s.strip()
    try:
        if s.endswith("Z") or "+" in s[10:] or (len(s) > 19 and "-" in s[19:]):
            import datetime as dt; return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        t = time.strptime(s[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        return float(calendar.timegm(t)) if utc else time.mktime(t)
    except Exception: return None

def _json(path):
    """(object, mtime) or (None, None) on a missing / corrupt file"""
    try:
        with open(path, encoding="utf-8") as f: return json.load(f), os.path.getmtime(path)
    except Exception: return None, None

def _mtime(path):
    try: return os.path.getmtime(path)
    except Exception: return None

def _tail_rows(path, cap):
    """(rows, complete): JSON rows from the last `cap` bytes of a jsonl (a line cut by the seek is dropped; complete = the whole
    file was read); (None, False) if the file is unreadable"""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); start = max(0, size - cap); f.seek(start); data = f.read()
    except Exception: return None, False
    lines = data.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines: lines = lines[1:]
    out = []
    for l in lines:
        try: r = json.loads(l)
        except Exception: continue
        if isinstance(r, dict): out.append(r)
    return out, start == 0

def _cands(path, since):
    """candidate rows from a byte tail that reaches back to `since` when the file allows: TAIL_CAP, then x4 up to TAIL_MAX"""
    cap = TAIL_CAP
    while True:
        rows, complete = _tail_rows(path, cap)
        if rows is None: return None
        first = next((t for t in (_epoch(r.get("ts")) for r in rows) if t is not None), None)
        if complete or cap >= TAIL_MAX or (first is not None and first <= since): return rows
        cap = min(TAIL_MAX, cap * 4)

def _atomic(path, obj):
    d = os.path.dirname(path)
    if d: os.makedirs(d, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(obj, f)
    os.replace(tmp, path)

def _pct(a, b):
    a, b = _num(a), _num(b)
    return round((a / b - 1) * 100, 3) if a is not None and b is not None and a > 0 and b > 0 else None

def _closes(kl):
    """Binance klines (list of lists, close at index 4) -> list of floats; None unless every row parses to a positive close"""
    if not isinstance(kl, list) or not kl: return None
    out = []
    for k in kl:
        c = _num(k[4]) if isinstance(k, (list, tuple)) and len(k) > 4 else None
        if c is None or c <= 0: return None
        out.append(c)
    return out

def _rv(closes):
    """std of the 24 hourly log returns in % (population std, not annualised); needs 25 closes"""
    if not closes or len(closes) < 25: return None
    c = closes[-25:]; r = [math.log(c[i] / c[i - 1]) * 100 for i in range(1, 25)]
    return round(statistics.pstdev(r), 3)

def _recent(history, now, days=7):
    """[(ts, snapshot)] of the history samples in the last `days` days (strictly before now)"""
    out = []
    for h in history or []:
        ts = _num(h.get("ts")) if isinstance(h, dict) else None
        if ts is not None and now - days * 86400 <= ts < now: out.append((ts, h))
    return out

def _p75(vals):
    v = sorted(x for x in vals if x is not None)
    return v[min(len(v) - 1, int(math.ceil(0.75 * len(v))) - 1)] if len(v) >= HEAT_MIN_SAMPLES else None

def _hist_at(history, path, t, tol=HIST_TOL):
    """value of snapshot[path[0]][path[1]] in the history sample closest to epoch t (within tol); None if none"""
    best, bd = None, tol + 1
    for h in history or []:
        ts = _num(h.get("ts")) if isinstance(h, dict) else None
        if ts is None: continue
        d = abs(ts - t)
        if d <= tol and d < bd:
            blk = h.get(path[0]); v = _num(blk.get(path[1])) if isinstance(blk, dict) else None
            if v is not None: best, bd = v, d
    return best

def _returns(coin, usd, closes, history, now):
    """r1h / r4h / r24h / rv24h from klines when present, else from the hourly history of <coin>.usd"""
    out = {"usd": usd, "r1h": None, "r4h": None, "r24h": None, "rv24h": None}
    if closes:
        n = len(closes)
        out["r1h"] = _pct(closes[-1], closes[-2]) if n >= 2 else None
        out["r4h"] = _pct(closes[-1], closes[-5]) if n >= 5 else None
        out["r24h"] = _pct(closes[-1], closes[-25]) if n >= 25 else None
        out["rv24h"] = _rv(closes)
        return out
    if usd is None: return out
    for k, hrs in (("r1h", 1), ("r4h", 4), ("r24h", 24)):
        p = _hist_at(history, (coin, "usd"), now - hrs * 3600)
        out[k] = _pct(usd, p) if p is not None else None
    series = [_hist_at(history, (coin, "usd"), now - h * 3600) for h in range(24, 0, -1)] + [usd]
    out["rv24h"] = _rv(series) if all(v is not None for v in series) else None
    return out


# ------------------------------------------------------------------------------------------------------------- gather
def gather(root=".", now=None, fetch=None):
    """Raw inputs: network via the fetchers (dict of callables: fetch > FETCH > DEFAULT_FETCH; a failing / raising / missing
    fetcher yields None) + the local state files. Never raises on data problems."""
    now = time.time() if now is None else now
    fx = dict(DEFAULT_FETCH); fx.update(FETCH or {}); fx.update(fetch or {})
    raw = {"ts": now}
    for k in DEFAULT_FETCH:
        try: raw[k] = fx[k]() if callable(fx.get(k)) else None
        except Exception: raw[k] = None
    P = lambda *p: os.path.join(root, *p)
    raw["news"], raw["news_mtime"] = _json(P("news_state.json"))
    raw["binance_status"], raw["binance_mtime"] = _json(P("status_binance.json"))
    raw["trend_status"], _ = _json(P("state", "trend_status.json"))
    raw["hl_risk"], raw["hl_mtime"] = _json(P("data", "hl_risk.json"))
    raw["insider_mtime"] = _mtime(P("insider_status.json"))
    raw["st_budget"], _ = _json(P("data", "st_budget.json"))
    try:
        import solanatracker; raw["st_cap"] = int(solanatracker.DAILY_CAP)
    except Exception: raw["st_cap"] = None
    raw["x_buzz"], raw["x_buzz_mtime"] = _json(P("data", "x_buzz.json"))
    raw["brain_state"], _ = _json(P("brain_state.json"))
    raw["director_state"], _ = _json(P("director_state.json"))
    raw["cands"] = _cands(P("candidates_solana.jsonl"), now - 3600)
    return raw


# -------------------------------------------------------------------------------------------------------------- build
def _news(raw, now):
    n, mt = raw.get("news"), raw.get("news_mtime")
    out = {"risk_off": None, "fng": None, "sentiment": None, "sources_ok": None, "age_s": None}
    if not isinstance(n, dict): return out
    if isinstance(n.get("risk_off"), bool): out["risk_off"] = n["risk_off"]
    fng = n.get("fng"); fng = fng.get("value") if isinstance(fng, dict) else fng
    if _num(fng) is not None: out["fng"] = int(_num(fng))
    out["sentiment"] = _num(n.get("sentiment"))
    so = n.get("sources_ok")
    if isinstance(so, dict):                        # news.py: {source: epoch of its last success} -> sources that answered recently
        ts = [_num(v) for v in so.values()]
        out["sources_ok"] = sum(1 for v in ts if v is not None and now - v <= NEWS_SRC_FRESH) if all(v is not None for v in ts) else len(so)
    elif isinstance(so, list): out["sources_ok"] = len(so)
    elif isinstance(so, int) and not isinstance(so, bool): out["sources_ok"] = so
    ts = _epoch(n.get("ts")) if n.get("ts") is not None else mt
    out["age_s"] = int(max(0, now - ts)) if ts is not None else None
    return out

def _btc_regime(raw, now):
    st, mt = raw.get("binance_status"), raw.get("binance_mtime")
    reg = ((st or {}).get("regime") or {}).get("regime") if isinstance(st, dict) and isinstance(st.get("regime"), dict) else None
    reg = reg if reg in ("bull", "bear", "range") else None
    age = int(max(0, now - mt)) if mt is not None and reg is not None else None
    return reg, age

def _market(raw, history, now):
    out = {"new_pools_1h": None, "graduations_1h": None, "new_pools_vol_h1_usd": None, "agg_vol_h1_usd": None, "n_cands_1h": None,
           "heat": None, "heat_ratio": None, "new_pools_p75_7d": None, "prio_fee_ulam": None}
    pools = raw.get("gecko_new_pools")
    if isinstance(pools, list):
        n = g = 0; vol = 0.0
        for p in pools:
            if not isinstance(p, dict): continue
            a = p.get("attributes") or {}
            t = _epoch(a.get("pool_created_at"))
            if t is None or not (now - 3600 <= t <= now + 300): continue
            n += 1; vol += _num((a.get("volume_usd") or {}).get("h1")) or 0.0
            dex = str((((p.get("relationships") or {}).get("dex") or {}).get("data") or {}).get("id") or "").lower()
            if dex.startswith(GRAD_DEXES): g += 1
        out.update(new_pools_1h=n, graduations_1h=g, new_pools_vol_h1_usd=round(vol, 2))
    cands = raw.get("cands")
    if isinstance(cands, list):
        latest, carry = {}, False                   # mint -> (ts, vol_h1) of the latest row in the hour that carries a volume (row order irrelevant)
        for r in cands:
            if not isinstance(r, dict): continue
            t = _epoch(r.get("ts")); m = r.get("mint")
            if t is None or not m or t < now - 3600 or t > now + 300: continue
            v = r.get("vol_h1"); v = (r.get("vol") or {}).get("h1") if v is None and isinstance(r.get("vol"), dict) else v
            v = _num(v)
            if v is not None: carry = True
            cur = latest.get(m)
            if cur is None or (v is not None and (cur[1] is None or t >= cur[0])): latest[m] = (t, v)
        out["n_cands_1h"] = len(latest)
        if carry: out["agg_vol_h1_usd"] = round(sum(v for _, v in latest.values() if v is not None), 2)
    pf = _num(raw.get("prio_fees"))
    if pf is not None and pf >= 0: out["prio_fee_ulam"] = int(pf)
    hour = time.gmtime(now).tm_hour
    rec = [h for _, h in _recent(history, now) if isinstance(h.get("market"), dict)]
    vols = [v for v in (_num(h["market"].get("new_pools_vol_h1_usd")) for h in rec if h.get("hour_utc") == hour) if v is not None]
    if len(vols) >= HEAT_MIN_SAMPLES and out["new_pools_vol_h1_usd"] is not None:
        med = statistics.median(vols)
        if med > 0:
            r = out["new_pools_vol_h1_usd"] / med
            out["heat_ratio"] = round(r, 3); out["heat"] = "hot" if r >= HEAT_HOT else "cold" if r <= HEAT_COLD else "normal"
    p75 = _p75(_num(h["market"].get("new_pools_1h")) for h in rec)
    if p75 is not None: out["new_pools_p75_7d"] = round(p75, 2)
    return out

def _breadth(raw, now):
    out = {"n_entry": None, "n_universe": None, "share": None, "med_atr_ratio": None}
    st = raw.get("trend_status")
    if not isinstance(st, dict) or not isinstance(st.get("signals"), dict): return out
    ts = _num(st.get("ts"))
    if ts is None or now - ts > BREADTH_MAX_AGE: return out
    uni = [s for s in st["signals"].values() if isinstance(s, dict) and s.get("in_universe", True)]
    if not uni: return out
    out["n_universe"] = len(uni); out["n_entry"] = sum(1 for s in uni if s.get("entry") is True)
    out["share"] = round(out["n_entry"] / len(uni), 3)
    ar = [v for v in (_num(s.get("atr_ratio")) for s in uni) if v is not None]
    out["med_atr_ratio"] = round(statistics.median(ar), 3) if ar else None
    return out

def _hl(raw, now):
    """data/hl_risk.json (hl_leg.hl_context): {updated: ISO UTC, status: ok|partial|degraded, coins: {COIN: {apex, crowd, flags_long, ...}}}
    -> apex (money_printer tier) bias on SOL / BTC and stress = SOL long-side flags ('none' | 'crowd_with_us|apex_against|liq_cluster|high_leverage');
    everything unknown when the data is older than HL_MAX_AGE (a degraded pass keeps the last good 'updated')"""
    out = {"sol_bias": None, "btc_bias": None, "stress": None, "status": None, "age_s": None}
    h = raw.get("hl_risk")
    if not isinstance(h, dict): return out
    if isinstance(h.get("status"), str): out["status"] = h["status"]
    ts = _epoch(h.get("updated"), utc=True) if h.get("updated") is not None else raw.get("hl_mtime")
    if ts is None: return out
    out["age_s"] = int(max(0, now - ts))
    if out["age_s"] > HL_MAX_AGE: return out
    coins = h.get("coins") if isinstance(h.get("coins"), dict) else {}
    sol, btc = coins.get("SOL"), coins.get("BTC")
    if isinstance(sol, dict):
        out["sol_bias"] = _num(sol.get("apex"))
        fl = sol.get("flags_long"); fl = fl.split("|") if isinstance(fl, str) else fl
        if isinstance(fl, list): out["stress"] = "|".join(str(x) for x in fl if x) or "none"
    if isinstance(btc, dict): out["btc_bias"] = _num(btc.get("apex"))
    return out

def _health(raw, now):
    out = {"insider_age_s": None, "st_budget_used": None, "st_budget_cap": None, "x_buzz_age_s": None, "brain_active": None, "director_shadow": None}
    if raw.get("insider_mtime") is not None: out["insider_age_s"] = int(max(0, now - raw["insider_mtime"]))
    b = raw.get("st_budget")
    if isinstance(b, dict) and isinstance(b.get("n"), int) and not isinstance(b.get("n"), bool):
        out["st_budget_used"] = b["n"] if b.get("day") == time.strftime("%Y-%m-%d", time.localtime(now)) else 0   # solanatracker resets the counter per local day
    if isinstance(raw.get("st_cap"), int) and not isinstance(raw.get("st_cap"), bool): out["st_budget_cap"] = raw["st_cap"]
    xb = raw.get("x_buzz")
    if isinstance(xb, dict):
        ts = [v for v in (_num((e or {}).get("ts")) for e in xb.values() if isinstance(e, dict)) if v is not None]
        t = max(ts) if ts else raw.get("x_buzz_mtime")
        if t is not None: out["x_buzz_age_s"] = int(max(0, now - t))
    bs, ds = raw.get("brain_state"), raw.get("director_state")
    if isinstance(bs, dict) and isinstance(bs.get("active"), bool): out["brain_active"] = bs["active"]
    if isinstance(ds, dict) and isinstance(ds.get("shadow"), bool): out["director_shadow"] = ds["shadow"]
    return out

def _stale(snap):
    """dotted names of every null field, plus the block name when the whole block is unknown"""
    out = []
    for blk in ("sol", "btc", "news", "market", "breadth", "hl", "health", "regime"):
        d = snap[blk]; nulls = [k for k, v in d.items() if v is None]
        if nulls and len(nulls) == len(d): out.append(blk)
        out += [f"{blk}.{k}" for k in nulls]
    return out

def build(raw, history=None, now=None):
    """PURE: raw inputs (gather()) + previous snapshots (list of dicts from data/context.jsonl, any order) -> the snapshot dict."""
    raw = raw if isinstance(raw, dict) else {}
    now = _num(raw.get("ts")) if now is None else _num(now)
    now = time.time() if now is None else now
    g = time.gmtime(now)
    sc, bc = _closes(raw.get("sol_klines")), _closes(raw.get("btc_klines"))
    sol_usd = _num(raw.get("sol_price"))
    if sol_usd is not None and sol_usd <= 0: sol_usd = None
    if sol_usd is None and sc: sol_usd = sc[-1]
    sol = _returns("sol", sol_usd, sc, history, now)
    btc = _returns("btc", bc[-1] if bc else None, bc, history, now)
    reg, reg_age = _btc_regime(raw, now)
    btc.update(regime=reg, regime_age_s=reg_age)
    news, market, breadth = _news(raw, now), _market(raw, history, now), _breadth(raw, now)
    r24 = sol["r24h"]
    trend = None if r24 is None else "up" if r24 >= TREND_UP else "down" if r24 <= TREND_DOWN else "flat"
    btc_on = (reg != "bear") if reg is not None and reg_age is not None and reg_age <= REGIME_MAX_AGE else None
    snap = {"ts": now, "code": CODE, "hour_utc": g.tm_hour, "dow": g.tm_wday, "sol": sol, "btc": btc, "news": news, "market": market,
            "breadth": breadth, "hl": _hl(raw, now), "health": _health(raw, now),
            "regime": {"sol_trend": trend, "btc_on": btc_on, "risk_off": news["risk_off"], "heat": market["heat"]}}
    snap["stale"] = _stale(snap)
    return snap


# ------------------------------------------------------------------------------------------------------- persistence
def history(root=".", cap=None):
    """previous snapshots from data/context.jsonl, oldest first ([] if missing); cap = read only the last `cap` bytes"""
    p = os.path.join(root, HIST_F)
    try: size = os.path.getsize(p)
    except Exception: return []
    rows, _ = _tail_rows(p, cap or max(size, 1))
    return [r for r in rows or [] if _num(r.get("ts")) is not None]

def write(snapshot, root="."):
    """data/context_now.json (atomic) + append to data/context.jsonl, bounded (> HIST_MAX lines -> keep the last HIST_KEEP). Returns the json path."""
    nowf, histf = os.path.join(root, NOW_F), os.path.join(root, HIST_F)
    _atomic(nowf, snapshot)
    os.makedirs(os.path.dirname(histf), exist_ok=True)
    with open(histf, "a", encoding="utf-8") as f: f.write(json.dumps(snapshot) + "\n")
    try:
        with open(histf, "rb") as f: n = sum(ch.count(b"\n") for ch in iter(lambda: f.read(1 << 20), b""))
        if n > HIST_MAX:
            with open(histf, "rb") as f: keep = f.read().splitlines()[-HIST_KEEP:]
            tmp = f"{histf}.{os.getpid()}.tmp"
            with open(tmp, "wb") as f: f.write(b"\n".join(keep) + b"\n")
            os.replace(tmp, histf)
    except Exception: pass
    return nowf

def load(root=".", max_age=7200, now=None):
    """snapshot from data/context_now.json, or None if missing / corrupt / another schema / older than max_age seconds"""
    now = time.time() if now is None else now
    s, _ = _json(os.path.join(root, NOW_F))
    if not isinstance(s, dict) or s.get("code") != CODE or _num(s.get("ts")) is None: return None
    if now - s["ts"] > max_age: return None
    return s


# ---------------------------------------------------------------------------------------------------------- consumers
def _flat(ctx):
    """the consumer fields from a full snapshot (nested blocks) or from a compact rec['ctx'] stamp (flat); unknown -> None"""
    if not isinstance(ctx, dict): return {}
    if isinstance(ctx.get("regime"), dict) or isinstance(ctx.get("market"), dict):
        r, m, n, b, s = (ctx.get(k) if isinstance(ctx.get(k), dict) else {} for k in ("regime", "market", "news", "breadth", "sol"))
        return {"ts": ctx.get("ts"), "sol_24h": s.get("r24h"), "sol_4h": s.get("r4h"), "sol_trend": r.get("sol_trend"), "btc_on": r.get("btc_on"),
                "risk_off": r.get("risk_off"), "fng": n.get("fng"), "heat": r.get("heat", m.get("heat")), "heat_ratio": m.get("heat_ratio"),
                "new_pools_1h": m.get("new_pools_1h"), "p75": m.get("new_pools_p75_7d"), "breadth": b.get("share"), "hour_utc": ctx.get("hour_utc"), "dow": ctx.get("dow")}
    return {k: ctx.get(k) for k in ("ts", "sol_24h", "sol_4h", "sol_trend", "btc_on", "risk_off", "fng", "heat", "heat_ratio", "new_pools_1h", "breadth", "hour_utc", "dow")}

def stamp(snapshot, thr=None, score_adj=None, size_mult=None, equity=None, n_pos=None, now=None):
    """compact rec['ctx'] the memebot writes on every candidate: STAMP_KEYS, nulls allowed (snapshot None -> all context nulls).
    hour_utc / dow are those of `now` (the candidate's moment), age_s = now - snapshot ts."""
    now = time.time() if now is None else now; g = time.gmtime(now)
    f = _flat(snapshot); ts = _num(f.get("ts"))
    return {"ts": ts, "age_s": int(max(0, now - ts)) if ts is not None else None, "sol_24h": f.get("sol_24h"), "sol_4h": f.get("sol_4h"),
            "sol_trend": f.get("sol_trend"), "btc_on": f.get("btc_on"), "risk_off": f.get("risk_off"), "fng": f.get("fng"), "heat": f.get("heat"),
            "heat_ratio": f.get("heat_ratio"), "new_pools_1h": f.get("new_pools_1h"), "breadth": f.get("breadth"), "hour_utc": g.tm_hour, "dow": g.tm_wday,
            "thr": thr, "score_adj": score_adj, "size_mult": size_mult, "equity": equity, "n_pos": n_pos}

def signals(ctx, history=None):
    """SIGNAL_KEYS -> bool, for the brain (features, not gates: an unknown field is False here; gates must read the nulls themselves).
    ctx = snapshot or stamp. launches_hi needs the 7-day p75 of new_pools_1h: from the snapshot (market.new_pools_p75_7d) or from
    `history` (list of snapshots, the 7 days before ctx.ts); a stamp without history -> False."""
    f = _flat(ctx); fng, share, hour, dow, npools, p75 = (f.get(k) for k in ("fng", "breadth", "hour_utc", "dow", "new_pools_1h", "p75"))
    if history:
        now = _num(f.get("ts")) or time.time()
        p75 = _p75(_num(h["market"].get("new_pools_1h")) for _, h in _recent(history, now) if isinstance(h.get("market"), dict))
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    return {"sol_up": f.get("sol_trend") == "up", "sol_down": f.get("sol_trend") == "down", "btc_on": f.get("btc_on") is True,
            "risk_off": f.get("risk_off") is True, "fear_extreme": bool(num(fng) and fng <= 20), "heat_hot": f.get("heat") == "hot",
            "heat_cold": f.get("heat") == "cold", "launches_hi": bool(num(npools) and num(p75) and npools >= p75),
            "breadth_hi": bool(num(share) and share >= 0.5), "night_utc": bool(num(hour) and 0 <= hour <= 6), "weekend": bool(num(dow) and dow >= 5)}

def keys(ctx):
    """regime key the Director groups by: (sol_trend, btc_on, risk_off, heat), None -> 'na'; ctx = snapshot or stamp"""
    f = _flat(ctx); na = lambda v: "na" if v is None else v
    return (na(f.get("sol_trend")), na(f.get("btc_on")), na(f.get("risk_off")), na(f.get("heat")))


# ---------------------------------------------------------------------------------------------------------------- CLI
def summary_line(snap):
    q = lambda v, f="{}": "?" if v is None else f.format(v)
    r = snap.get("regime") or {}; m = snap.get("market") or {}; b = snap.get("breadth") or {}; n = snap.get("news") or {}; s = snap.get("sol") or {}
    bo = r.get("btc_on"); ro = r.get("risk_off")
    return (f"contexto: SOL {q(s.get('r24h'), '{:+.1f}')}% 24h, BTC {'?' if bo is None else 'on' if bo else 'off'}, F&G {q(n.get('fng'))}, "
            f"riesgo-off {'?' if ro is None else 'si' if ro else 'no'}, lanzamientos/h {q(m.get('new_pools_1h'))}, calor {q(m.get('heat'))}, "
            f"amplitud {q(b.get('n_entry'))}/{q(b.get('n_universe'))}")

def run_once(root=".", now=None, fetch=None):
    """gather + build + write; returns the snapshot (never raises on data problems: nulls + stale)"""
    now = time.time() if now is None else now
    snap = build(gather(root, now, fetch), history(root, cap=HIST_TAIL), now)
    write(snap, root); return snap

def main(argv=None, fetch=None, root=None):
    argv = sys.argv[1:] if argv is None else argv
    root = root or os.path.dirname(os.path.abspath(__file__))   # the repo root whatever the cwd (like hl_context)
    if "--show" in argv:
        s, _ = _json(os.path.join(root, NOW_F)); print(json.dumps(s, indent=1, ensure_ascii=False) if s else "sin contexto (data/context_now.json no existe)"); return 0
    if "--loop" in argv:
        period = int(os.environ.get("CONTEXT_SECONDS", "3600"))
        while not os.path.exists(os.path.join(root, "STOP")):
            try: print(time.strftime("%Y-%m-%dT%H:%M:%S"), summary_line(run_once(root, fetch=fetch)), flush=True)
            except Exception as e: print(time.strftime("%Y-%m-%dT%H:%M:%S"), f"contexto: error {str(e)[:120]}", flush=True)
            for _ in range(period):
                if os.path.exists(os.path.join(root, "STOP")): break
                time.sleep(1)
        return 0
    print(summary_line(run_once(root, fetch=fetch))); return 0

if __name__ == "__main__":
    sys.exit(main())
