"""Insider wallet reliability engine ("seguir a las mejores wallets de insiders, las mas fiables"). Pure functions + one build entry point.
Replaces insider.py's point-estimate ranking (Beta(1,1) prior: 2121 of 2196 'good' wallets were exactly h=2,m=0; no decay; launch snipers
in 32-39 % of ALL mined launches ranked top-5) with, per wallet, from research/insider_mined.jsonl:
  - hits/misses decayed by launch age (half-life 7 d) -> h_eff/m_eff; Beta prior centred on the mined base rate (strength 10)
  - rel = 20th percentile of the Beta posterior (a wallet with 2 hits and no misses is NOT elite: the lower bound says "not known yet")
  - bot filter: participation share, slot-0/1 sniping, early sells (insider.py rules kept, new ones added); dev exclusion
  - funding-cluster collapse (only the best wallet of a cluster may be elite/good), live 1h-forward track veto (insider_wallet_live.json),
    Solana Tracker realized-PnL veto (st_pnl), hysteresis (up moves need a pending build, down moves are immediate), tier-change log
Output insider_rank.json (schema in rank()); insider.py consumers use load() and fall back to the old sc ranking when it is missing/stale.
Tighten-only relative to insider.py: nothing here places an order or relaxes a veto; unknown data -> no tier (never a pass)."""
import json, os, sys, re, time, math, collections, contextlib, datetime as dt, logging
import numpy as np
log = logging.getLogger("insider_rank")
CODE = "insider_rank/1"; F_RANK = "insider_rank.json"; F_LOG = "research/insider_rank_log.jsonl"
F_W = "insider_wallets.json"; F_MINED = "research/insider_mined.jsonl"; F_WL = "insider_wallet_live.json"
N_EARLY = 100; MAX_AGE_S = 7200; TOP_N = 200; MIN_N = 2; HALF_LIFE_D = 7.0; PRIOR_N = 10.0; Q = 0.20; DISC_KEEP_D = 14; DISC_MINTS_KEEP = 3000
RANK = {None: 0, "watch": 1, "good": 2, "elite": 3}; TIERS = ("elite", "good", "watch")
ADDR = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
# thresholds; params(p) may only TIGHTEN them (owner invariant), direction per key in _TIGHT
P = dict(rel_elite=0.60, h_elite=2.5, days_elite=2, hit_days=14.0, live_min_n=10, live_elite=0.0, live_good=-0.02, rel_good=0.50, h_good=1.5,
         pnl_min_tokens=5, pnl_win=50.0, bot_part=0.10, bot_part_snipe=0.03, bot_slot=1.0)
_TIGHT = dict(rel_elite=max, h_elite=max, days_elite=max, hit_days=min, live_min_n=min, live_elite=max, live_good=max, rel_good=max, h_good=max,
              pnl_min_tokens=min, pnl_win=max, bot_part=min, bot_part_snipe=min, bot_slot=max)
def params(p=None):
    """defaults merged with p, but every override is clamped to the stricter side (relaxing a threshold is silently ignored)"""
    out = dict(P)
    for k, v in (p or {}).items():
        if k in _TIGHT:
            try: out[k] = _TIGHT[k](P[k], float(v))
            except Exception: pass
    return out
# ---------- Beta posterior quantile (no scipy) ----------
def _betacf(a, b, x, maxit=400, eps=1e-14):
    """continued fraction for the regularised incomplete beta (Numerical Recipes betacf)"""
    tiny = 1e-300; qab, qap, qam = a+b, a+1.0, a-1.0; c = 1.0; d = 1.0-qab*x/qap
    d = tiny if abs(d) < tiny else d; d = 1.0/d; h = d
    for m in range(1, maxit+1):
        m2 = 2*m; aa = m*(b-m)*x/((qam+m2)*(a+m2))
        d = 1.0+aa*d; d = tiny if abs(d) < tiny else d; c = 1.0+aa/c; c = tiny if abs(c) < tiny else c; d = 1.0/d; h *= d*c
        aa = -(a+m)*(qab+m)*x/((a+m2)*(qap+m2))
        d = 1.0+aa*d; d = tiny if abs(d) < tiny else d; c = 1.0+aa/c; c = tiny if abs(c) < tiny else c; d = 1.0/d; de = d*c; h *= de
        if abs(de-1.0) < eps: break
    return h
def betainc(a, b, x):
    """regularised incomplete beta I_x(a, b)"""
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    bt = math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)+a*math.log(x)+b*math.log1p(-x))
    return bt*_betacf(a, b, x)/a if x < (a+1.0)/(a+b+2.0) else 1.0-bt*_betacf(b, a, 1.0-x)/b
def beta_ppf(p, a, b, tol=1e-10):
    """scalar quantile of Beta(a, b) by bisection on betainc (Beta(2,2) 20th pct = 0.2871, Beta(5,5) = 0.3661)"""
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo+hi)/2
        if betainc(a, b, mid) < p: lo = mid
        else: hi = mid
        if hi-lo < tol: break
    return (lo+hi)/2
def beta_ppf_vec(p, a, b, grid=1024, chunk=512):
    """vectorised quantile for arrays a, b >= 1: midpoint-rule Beta pdf on a grid, cumulative sum, linear interpolation inside the cell
    (|error| < 1e-4 vs beta_ppf; 4000 wallets in ~0.1 s)"""
    a = np.asarray(a, float); b = np.asarray(b, float); n = len(a); out = np.empty(n)
    if not n: return out
    x = (np.arange(grid)+0.5)/grid; lx = np.log(x); l1x = np.log1p(-x); edge = np.arange(grid+1)/grid
    for i in range(0, n, chunk):
        A = a[i:i+chunk, None]; B = b[i:i+chunk, None]
        lp = (A-1)*lx+(B-1)*l1x; lp -= lp.max(axis=1, keepdims=True); cdf = np.cumsum(np.exp(lp), axis=1); cdf /= cdf[:, -1:]
        k = np.minimum((cdf < p).sum(axis=1), grid-1); r = np.arange(len(k)); hi = cdf[r, k]; lo = np.where(k > 0, cdf[r, np.maximum(k-1, 0)], 0.0)
        out[i:i+chunk] = edge[k]+np.clip((p-lo)/np.maximum(hi-lo, 1e-300), 0, 1)/grid
    return out
def decay(age_s, half_life_d=HALF_LIFE_D):
    """weight of a launch outcome by age (0.5 at the half-life); unknown/negative age -> 0 (no credit)"""
    if age_s is None: return 0.0
    return 0.5 ** (max(0.0, age_s)/86400.0/half_life_d)
# ---------- helpers ----------
def _median(v):
    if not v: return None
    s = sorted(v); n = len(s)
    return float(s[n//2]) if n % 2 else (s[n//2-1]+s[n//2])/2.0
def _num(v): return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
def _fl(v):
    try: return float(v) if _num(v) or (isinstance(v, str) and v.strip()) else None
    except Exception: return None
def _r(v, d): return None if v is None else round(float(v), d)
def read_jsonl(path):
    out = []
    try:
        for l in open(path):
            try: out.append(json.loads(l))
            except Exception: continue
    except Exception: pass
    return out
def _load_json(path, default):
    try: return json.load(open(path))
    except Exception: return default
def write_json(path, obj):
    t = f"{path}.{os.getpid()}.tmp"
    with open(t, "w") as f: json.dump(obj, f)
    os.replace(t, path)
@contextlib.contextmanager
def _owner(st, who):
    """Solana Tracker budget owner for the duration of the calls (per-owner caps in solanatracker._budget_ok), restored afterwards"""
    ow = getattr(st, "OWNER", None)
    if not isinstance(ow, list) or not ow: yield; return
    old = ow[0]; ow[0] = who
    try: yield
    finally: ow[0] = old
def _safe(fn, *a):
    try: return fn(*a)
    except Exception: return None
# ---------- Solana Tracker payload parsers (shapes assumed, see solanatracker.py docstrings; anything unexpected -> dropped) ----------
def parse_pnl(d):
    """/pnl/{wallet} summary -> {realized, unrealized, win_pct, n_tokens, src:'st'} | None. Accepts an already parsed dict."""
    if not isinstance(d, dict): return None
    if "n_tokens" in d and "realized" in d: return dict(d, src=d.get("src") or "st")
    s = d.get("summary")
    if not isinstance(s, dict): return None
    wins, losses = _fl(s.get("totalWins")), _fl(s.get("totalLosses")); wp = _fl(s.get("winPercentage"))
    if wp is None and wins is not None and losses is not None and wins+losses > 0: wp = 100.0*wins/(wins+losses)
    tok = d.get("tokens"); nt = len(tok) if isinstance(tok, (dict, list)) else int((wins or 0)+(losses or 0))
    return dict(realized=_fl(s.get("realized")) or 0.0, unrealized=_fl(s.get("unrealized")) or 0.0, win_pct=_r(wp, 2), n_tokens=int(nt), src="st")
def _rows(d, keys):
    if isinstance(d, list): return d
    if isinstance(d, dict):
        for k in keys:
            if isinstance(d.get(k), list): return d[k]
    return []
def parse_first_buyers(d):
    """/first-buyers/{token} -> [{wallet, total, realized, unrealized, first_buy_time}] (bare list assumed; dict with a list under buyers/data/wallets tolerated)"""
    out = []
    for e in _rows(d, ("buyers", "data", "wallets", "first_buyers")):
        if isinstance(e, dict) and isinstance(e.get("wallet"), str) and ADDR.match(e["wallet"]):
            out.append(dict(wallet=e["wallet"], total=_fl(e.get("total")), realized=_fl(e.get("realized")), unrealized=_fl(e.get("unrealized")), first_buy_time=_fl(e.get("first_buy_time"))))
    return out
def parse_top_traders(d):
    """/top-traders/all -> [{wallet, total, win_pct, wins, losses, realized, unrealized}] from {wallets: [{wallet, summary: {...}}]} or a bare list"""
    out = []
    for e in _rows(d, ("wallets", "data", "traders")):
        if not (isinstance(e, dict) and isinstance(e.get("wallet"), str) and ADDR.match(e["wallet"])): continue
        s = e.get("summary") if isinstance(e.get("summary"), dict) else e
        wins, losses = _fl(s.get("totalWins")), _fl(s.get("totalLosses")); wp = _fl(s.get("winPercentage"))
        if wp is None and wins is not None and losses is not None and wins+losses > 0: wp = 100.0*wins/(wins+losses)
        out.append(dict(wallet=e["wallet"], total=_fl(s.get("total")), win_pct=_r(wp, 2), wins=int(wins or 0), losses=int(losses or 0), realized=_fl(s.get("realized")), unrealized=_fl(s.get("unrealized"))))
    return out
# ---------- aggregation over mined launches ----------
def _agg(rows, now):
    """one pass over mined rows -> (per-wallet raw stats, early-sell counter, n_launches, wins, devs).
    Rows without a boolean win or without an ev list are skipped (unknown outcome = no information). ev fields as insider.mine_launch:
    buys {w, rank, dt, dslot, sol, q}, sells {w, sell: True, dt, sol, q}."""
    A = {}; SE = collections.Counter(); nL = 0; wins = 0; devs = set()
    for x in rows:
        if not isinstance(x, dict): continue
        win = x.get("win"); ev = x.get("ev")
        if win is None or not isinstance(ev, list): continue
        win = bool(win); nL += 1; wins += win; t0 = x.get("t0") if _num(x.get("t0")) else None
        for c in (x.get("creator"), x.get("creator2")):
            if isinstance(c, str): devs.add(c)
        if t0 is not None: w = decay(now-t0); day = int(t0//86400)
        else: w = 0.0; day = None
        seen = set()
        for e in ev:
            if not isinstance(e, dict): continue
            wa = e.get("w")
            if not isinstance(wa, str): continue
            if e.get("sell"): SE[wa] += 1; continue
            rk = e.get("rank")
            if not _num(rk) or rk >= N_EARLY or wa in seen: continue
            seen.add(wa); a = A.get(wa)
            if a is None: a = A[wa] = dict(n=0, h=0, m=0, he=0.0, me=0.0, rk=0.0, sol=0.0, ns=0, dts=[], dss=[], days=set(), snipe=0, lh=None, ls=None)
            a["n"] += 1; a["rk"] += rk
            sol = e.get("sol"); d_t = e.get("dt"); ds = e.get("dslot")
            if _num(sol): a["sol"] += sol; a["ns"] += 1
            if _num(d_t): a["dts"].append(d_t)
            if _num(ds): a["dss"].append(ds); a["snipe"] += ds <= 1
            if day is not None: a["days"].add(day)
            if t0 is not None and (a["ls"] is None or t0 > a["ls"]): a["ls"] = t0
            if win:
                a["h"] += 1; a["he"] += w
                if t0 is not None and (a["lh"] is None or t0 > a["lh"]): a["lh"] = t0
            else: a["m"] += 1; a["me"] += w
    return A, SE, nL, wins, devs
def _bot_why(a, se, part, pr):
    n = a["n"]; med = _median(a["dss"])
    if part > pr["bot_part"]: return "part>%.0f%%" % (100*pr["bot_part"])
    if med is not None and med <= pr["bot_slot"] and part > pr["bot_part_snipe"]: return "slot_sniper"
    if n >= 6 and part > 0.5: return "n/nL>0.5"                      # insider.py rule
    if se > 3*n: return "sells_early"                                 # insider.py rule
    if a["snipe"] >= max(2, 0.6*n): return "snipe"                    # insider.py rule
    return None
def _raw_tier(o, pr, base_rate, now):
    """(tier, why) for one wallet before cluster collapse and hysteresis. Fail-closed: a veto with unknown data blocks the higher tier."""
    if o["why"] in ("dev", "farm_cluster"): return None, o["why"]
    if o["bot"]: return None, "bot"
    if o["n"] == 0: return None, o["why"] or "no_data"
    why = None; ln, lm, pnl = o["live_n"], o["live_mean"], o["pnl"]
    if o["rel"] >= pr["rel_elite"] and o["h_eff"] >= pr["h_elite"] and o["days"] >= pr["days_elite"]:
        if not (o["last_hit_t"] is not None and now-o["last_hit_t"] <= pr["hit_days"]*86400): why = "stale"
        elif not (ln < pr["live_min_n"] or (lm is not None and lm > pr["live_elite"])): why = "live_veto"
        elif pnl and pnl.get("n_tokens", 0) >= pr["pnl_min_tokens"] and not (pnl.get("win_pct") is not None and pnl["win_pct"] >= pr["pnl_win"]): why = "pnl_veto"
        else: return "elite", "elite"
    if o["rel"] >= pr["rel_good"] and o["h_eff"] >= pr["h_good"]:
        if ln < pr["live_min_n"] or (lm is not None and lm > pr["live_good"]): return "good", why or "good"
        why = why or "live_veto"
    if o["hr_post"] > base_rate: return "watch", why or "watch"
    return None, why or "low"
def _hyst(raw, prev_tier, mark, known):
    """down/same: immediate. Up: one tier per build when prev had the wallet at the tier just below; a bigger jump (or a wallet absent from
    prev) is held at the previous tier and marked '<tier>?' so the NEXT build may confirm it. Returns (tier, marker|None)."""
    if RANK[raw] <= RANK[prev_tier]: return raw, None
    if mark == f"{raw}?": return raw, None
    if known and RANK[raw] == RANK[prev_tier]+1: return raw, None
    return prev_tier, f"{raw}?"
def _prev_state(prev):
    """(tier per wallet in prev, pending markers, known set) from a previous rank doc"""
    PT, M, known = {}, {}, set()
    if not isinstance(prev, dict): return PT, M, known
    pw = prev.get("wallets") if isinstance(prev.get("wallets"), dict) else {}
    for a, o in pw.items():
        if isinstance(o, dict): PT[a] = o.get("tier") if o.get("tier") in TIERS else None; known.add(a)
    for a, v in (prev.get("prev_tiers") or {}).items():
        if isinstance(v, str) and v.endswith("?") and v[:-1] in TIERS: M[a] = v
        elif a not in PT and v in TIERS: PT[a] = v; known.add(a)
    return PT, M, known
def _prune_discovery(disc, now):
    disc = disc if isinstance(disc, dict) else {}
    C = {a: c for a, c in (disc.get("candidates") or {}).items() if isinstance(c, dict) and now-(c.get("t") or 0) <= DISC_KEEP_D*86400}
    return dict(t=disc.get("t"), n_candidates=len(C), n_added=0, note=disc.get("note") or "", mints=list(disc.get("mints") or [])[-DISC_MINTS_KEEP:], candidates=C)
# ---------- the rank ----------
def rank(wallets_json, mined_rows, live_json, now, prev=None, st_pnl=None, p=None, discovery=None):
    """Pure. Returns the insider_rank.json document:
    {t, code:'insider_rank/1', base_rate, half_life_d: 7, n_launches,
     wallets: {addr: {rel, tier: 'elite'|'good'|'watch'|None, h, m, h_eff, m_eff, hr_post, part, bot, bot_why, early, days, med_dt, med_dslot, avg_sol,
                      last_hit_t, last_seen_t, cluster, live_n, live_hit, live_mean, pnl: {realized, unrealized, win_pct, n_tokens, src:'st'}|None, why}},
     tiers: {elite, good, watch}, top: [addr... by rel desc, tiered non-bot wallets only, max 200], prev_tiers: {addr: tier|'elite?'...},
     discovery: {t, n_candidates, n_added, note, mints: [...], candidates: {addr: {src, n_wins, pnl_total, win_pct, t}}}}
    Universe: wallets in >= 2 mined launches (first 100 swaps) + wallets_json/live_json keys + prev tiered wallets + discovery candidates.
    wallets_json: insider_wallets.json doc or its 'wallets' dict (source of cluster ids); live_json: {addr: {n, h, sum}}; st_pnl: {addr: /pnl doc or parsed};
    prev: previous rank doc (hysteresis + tier-change detection; None = bootstrap, raw tiers); p: threshold overrides (tighten-only, see params())."""
    pr = params(p); now = float(now); W = wallets_json.get("wallets") if isinstance(wallets_json, dict) and isinstance(wallets_json.get("wallets"), dict) else (wallets_json or {})
    WL = live_json if isinstance(live_json, dict) else {}; st_pnl = st_pnl if isinstance(st_pnl, dict) else {}
    A, SE, nL, wins, devs = _agg(mined_rows or [], now)
    base_rate = wins/nL if nL else 0.5; a0 = max(1.0, PRIOR_N*base_rate); b0 = max(1.0, PRIOR_N*(1-base_rate)); nLd = max(1, nL)
    PT, M, known = _prev_state(prev)
    disc = _prune_discovery(discovery if discovery is not None else (prev or {}).get("discovery") if isinstance(prev, dict) else None, now)
    keep = {a for a, x in A.items() if x["n"] >= MIN_N} | {a for a in W if isinstance(a, str)} | {a for a in WL if isinstance(a, str)} | \
           {a for a in known if PT.get(a) or a in M} | set(disc["candidates"])
    out = {}; addrs = sorted(keep)
    for a in addrs:
        x = A.get(a); wj = W.get(a) if isinstance(W.get(a), dict) else {}; l = WL.get(a) if isinstance(WL.get(a), dict) else {}
        ln = int(l.get("n") or 0) if _num(l.get("n")) else 0; lh = int(l.get("h") or 0) if _num(l.get("h")) else 0; ls = l.get("sum")
        o = dict(rel=0.0, tier=None, h=0, m=0, h_eff=0.0, m_eff=0.0, hr_post=0.0, part=0.0, bot=False, bot_why=None, early=0.0, days=0, med_dt=None, med_dslot=None,
                 avg_sol=None, last_hit_t=None, last_seen_t=None, cluster=wj.get("cluster") if isinstance(wj.get("cluster"), str) else None,
                 live_n=ln, live_hit=lh, live_mean=_r(ls/ln, 4) if ln and _num(ls) else None, pnl=parse_pnl(st_pnl.get(a)), why=None, n=0)
        if x is not None:
            part = x["n"]/nLd
            o.update(h=x["h"], m=x["m"], h_eff=x["he"], m_eff=x["me"], part=part, early=round(1-x["rk"]/x["n"]/N_EARLY, 3), days=len(x["days"]), med_dt=_r(_median(x["dts"]), 1),
                     med_dslot=_r(_median(x["dss"]), 1), avg_sol=_r(x["sol"]/x["ns"], 4) if x["ns"] else None, last_hit_t=x["lh"], last_seen_t=x["ls"], n=x["n"])
            o["bot_why"] = _bot_why(x, SE.get(a, 0), part, pr); o["bot"] = o["bot_why"] is not None
        if a in devs: o["why"] = "dev"
        elif (wj.get("excluded") == "farm_cluster") or (_num(wj.get("cluster_n")) and wj["cluster_n"] > 5): o["why"] = "farm_cluster"
        elif x is None and a in disc["candidates"]: o["why"] = "discovered"
        out[a] = o
    if addrs:
        av = np.array([out[a]["h_eff"]+a0 for a in addrs]); bv = np.array([out[a]["m_eff"]+b0 for a in addrs]); rel = beta_ppf_vec(Q, av, bv); hp = av/(av+bv)
        for i, a in enumerate(addrs): out[a]["rel"] = float(rel[i]); out[a]["hr_post"] = float(hp[i])
    raw = {}
    for a, o in out.items(): raw[a] = _raw_tier(o, pr, base_rate, now)
    C = collections.defaultdict(list)                                  # cluster collapse: only the best wallet of a funding cluster may be elite/good
    for a, o in out.items():
        if o["cluster"] and not o["bot"] and o["why"] not in ("dev", "farm_cluster"): C[o["cluster"]].append(a)
    for ws in C.values():
        best = max(ws, key=lambda a: (out[a]["rel"], out[a]["h_eff"], a))
        for a in ws:
            if a != best and raw[a][0] in ("elite", "good"): raw[a] = ("watch", "cluster")
    tiers = collections.Counter(); prev_tiers = {}
    for a, o in out.items():
        rt, why = raw[a]
        if prev is None: tier, mark = rt, None
        else: tier, mark = _hyst(rt, PT.get(a), M.get(a), a in known)
        if mark: why = "pending:" + rt
        o["tier"] = tier; o["why"] = why
        o["h_eff"] = round(o["h_eff"], 3); o["m_eff"] = round(o["m_eff"], 3); o["rel"] = round(o["rel"], 4); o["hr_post"] = round(o["hr_post"], 4); o["part"] = round(o["part"], 4)
        n = o.pop("n")
        if tier: tiers[tier] += 1
        if mark: prev_tiers[a] = mark
        elif tier: prev_tiers[a] = tier
    top = sorted((a for a, o in out.items() if o["tier"] and not o["bot"]), key=lambda a: (-out[a]["rel"], a))[:TOP_N]
    disc["n_added"] = sum(1 for o in out.values() if o["why"] == "discovered")
    return dict(t=now, code=CODE, base_rate=round(base_rate, 4), half_life_d=int(HALF_LIFE_D), n_launches=nL, wallets=out, tiers={k: tiers.get(k, 0) for k in TIERS},
                top=top, prev_tiers=prev_tiers, discovery=disc)
def tier_changes(prev, doc):
    """log rows {t, addr, from, to, rel, why} for every wallet whose tier differs between the previous rank doc and `doc` (wallets that vanished -> to None)"""
    PT, _, _ = _prev_state(prev); W = doc["wallets"]; out = []
    for a in sorted(set(PT) | set(W)):
        o = W.get(a) or {}; to = o.get("tier")
        if PT.get(a) != to: out.append({"t": doc["t"], "addr": a, "from": PT.get(a), "to": to, "rel": o.get("rel"), "why": o.get("why") or "gone"})
    return out
# ---------- Solana Tracker discovery / PnL (optional; research budget, owner 'insider') ----------
def discover(st, winners, rank_doc, now, budget=20):
    """first_buyers() on up to `budget` recent winner mints (mined rows with win True, newest first, mints already in rank_doc['discovery']['mints']
    skipped) + top_traders(page 1). Returns {candidates: {addr: {src: 'first_buyers'|'top_traders', n_wins, pnl_total, win_pct}}, n_calls, mints}.
    Candidates are NOT trusted: rank() merges them with tier None and why='discovered' until the RPC miner confirms them (h_eff > 0).
    n_wins: winner mints where the wallet was a first buyer (first_buyers) or the leaderboard's totalWins (top_traders)."""
    disc = (rank_doc or {}).get("discovery") if isinstance(rank_doc, dict) else None; done = set((disc or {}).get("mints") or [])
    mints = []
    for x in sorted((x for x in (winners or []) if isinstance(x, dict) and x.get("win") and isinstance(x.get("mint"), str)), key=lambda x: -(x.get("t0") or 0)):
        if len(mints) >= max(0, int(budget)): break
        if x["mint"] not in done and x["mint"] not in mints: mints.append(x["mint"])
    C = {}; n_calls = 0; queried = []
    with _owner(st, "insider"):
        for m in mints:
            d = _safe(getattr(st, "first_buyers", None) or (lambda m: None), m); n_calls += 1
            if d is None: continue                                     # no key / budget / malformed: unknown, nothing is added
            queried.append(m)
            for b in parse_first_buyers(d):
                c = C.setdefault(b["wallet"], dict(src="first_buyers", n_wins=0, pnl_total=None, win_pct=None)); c["n_wins"] += 1
                if b["total"] is not None: c["pnl_total"] = round((c["pnl_total"] or 0.0)+b["total"], 4)
        d = _safe(getattr(st, "top_traders", None) or (lambda p: None), 1); n_calls += 1
        for t in parse_top_traders(d) if d is not None else []:
            c = C.setdefault(t["wallet"], dict(src="top_traders", n_wins=0, pnl_total=None, win_pct=None))
            if c["pnl_total"] is None: c["pnl_total"] = t["total"]
            if t["win_pct"] is not None: c["win_pct"] = t["win_pct"]
            c["n_wins"] = max(c["n_wins"], t["wins"])
    return dict(candidates=C, n_calls=n_calls, mints=queried)
def merge_discovery(prev_disc, found, now):
    """previous discovery block + a discover() result -> new block (candidates kept DISC_KEEP_D days, queried mints remembered)"""
    d = _prune_discovery(prev_disc, now)
    for a, c in (found or {}).get("candidates", {}).items(): d["candidates"][a] = dict(c, t=now)
    d["mints"] = (d["mints"]+[m for m in (found or {}).get("mints", []) if m not in d["mints"]])[-DISC_MINTS_KEEP:]
    d["t"] = now; d["n_candidates"] = len(d["candidates"]); d["note"] = "%d llamadas ST, %d candidatos nuevos" % ((found or {}).get("n_calls", 0), len((found or {}).get("candidates", {})))
    return d
def pull_pnl(st, addrs, budget=20):
    """{addr: parsed /pnl summary} for addrs: cached entries first (free), then at most `budget` network calls (owner 'insider'); never raises"""
    out = {}; cache = {}; ttl = None
    try: cache = st._load(st.CACHE_F, {}) if hasattr(st, "_load") and hasattr(st, "CACHE_F") else {}; ttl = (getattr(st, "TTL", None) or {}).get("pnl")
    except Exception: cache = {}
    cached = lambda a: isinstance(cache.get(f"/pnl/{a}"), dict) and ttl is not None and time.time()-(cache[f"/pnl/{a}"].get("t") or 0) < ttl
    todo = [a for a in addrs if isinstance(a, str)]; order = [a for a in todo if cached(a)]+[a for a in todo if not cached(a)]; n = 0
    with _owner(st, "insider"):
        for a in order:
            if not cached(a):
                if n >= max(0, int(budget)): break
                n += 1
            v = parse_pnl(_safe(getattr(st, "wallet_pnl", None) or (lambda a: None), a))
            if v is not None: out[a] = v
    return out
# ---------- files ----------
def load(root="."):
    """insider_rank.json as dict, or None when missing, corrupt, another code or older than MAX_AGE_S (callers fall back to the old sc ranking)"""
    d = _load_json(os.path.join(root, F_RANK), None)
    if not isinstance(d, dict) or d.get("code") != CODE or not _num(d.get("t")) or abs(time.time()-d["t"]) > MAX_AGE_S or not isinstance(d.get("wallets"), dict): return None
    return d
def build(root=".", st=None, now=None, disc_budget=5, pnl_budget=5):
    """Reads root/research/insider_mined.jsonl (+ insider_wallets.json, insider_wallet_live.json, previous insider_rank.json), writes insider_rank.json
    atomically, appends research/insider_rank_log.jsonl rows {t, addr, from, to, rel, why} per tier change, returns the doc (None when nothing mined).
    st: solanatracker module (or None, offline): discovery + PnL for the top wallets under the 'insider' budget owner. Safe every 20 min."""
    now = float(now or time.time()); rows = read_jsonl(os.path.join(root, F_MINED))
    if not rows: log.warning("[insider_rank] sin lanzamientos minados en %s", os.path.join(root, F_MINED)); return None
    W = _load_json(os.path.join(root, F_W), {}); WL = _load_json(os.path.join(root, F_WL), {}); prev = _load_json(os.path.join(root, F_RANK), None)
    if not isinstance(prev, dict): prev = None
    disc = None; st_pnl = {}
    if st is not None:
        found = _safe(discover, st, rows, prev, now, disc_budget) or dict(candidates={}, n_calls=0, mints=[])
        disc = merge_discovery((prev or {}).get("discovery"), found, now)
    doc = rank(W, rows, WL, now, prev=prev, discovery=disc)
    if st is not None and doc["top"]:                                   # PnL for the current best wallets (cache first, then <= pnl_budget calls), then re-rank

        st_pnl = pull_pnl(st, doc["top"][:max(pnl_budget, 20)], budget=pnl_budget)
        if st_pnl: doc = rank(W, rows, WL, now, prev=prev, st_pnl=st_pnl, discovery=disc)
    changes = tier_changes(prev, doc)
    write_json(os.path.join(root, F_RANK), doc)
    if changes:
        os.makedirs(os.path.join(root, "research"), exist_ok=True)
        with open(os.path.join(root, F_LOG), "a") as f:
            for c in changes: f.write(json.dumps(c)+"\n")
    log.warning("[insider_rank] %d wallets %s base=%.2f launches=%d cambios=%d", len(doc["wallets"]), doc["tiers"], doc["base_rate"], doc["n_launches"], len(changes))
    return doc
# ---------- CLI ----------
def table(doc, top=20):
    """compact text table of the best wallets (Spanish headers): wallet, nivel, fiab, ac/fa, part, bot, live, pnl, motivo"""
    if not doc: return "sin ranking (insider_rank.json ausente u obsoleto)"
    W = doc["wallets"]; rows = ["%-10s %-6s %5s %7s %6s %-3s %-12s %-12s %s" % ("wallet", "nivel", "fiab", "ac/fa", "part", "bot", "live", "pnl", "motivo")]
    order = doc.get("top") or []; order = order+[a for a in sorted(W, key=lambda a: -W[a]["rel"]) if a not in order]
    for a in order[:top]:
        o = W[a]; live = "%d/%d %+.1f%%" % (o["live_hit"], o["live_n"], 100*o["live_mean"]) if o["live_n"] else "-"
        pnl = "%+.1f %d%%" % (o["pnl"]["realized"], o["pnl"]["win_pct"] or 0) if o.get("pnl") else "-"
        rows.append("%-10s %-6s %5.3f %7s %6.3f %-3s %-12s %-12s %s" % (a[:6]+"...", o["tier"] or "-", o["rel"], "%.1f/%.1f" % (o["h_eff"], o["m_eff"]), o["part"], "si" if o["bot"] else "no", live, pnl, o["why"]))
    t = doc.get("t") or 0
    rows.append("%d wallets, %s, base %.2f, %d lanzamientos, hace %.0f min" % (len(W), doc.get("tiers"), doc.get("base_rate", 0), doc.get("n_launches", 0), (time.time()-t)/60))
    return "\n".join(rows)
if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    args = sys.argv[1:]; n = int(args[args.index("--top")+1]) if "--top" in args else 20; root = args[args.index("--root")+1] if "--root" in args else "."
    d = build(root) if "--build" in args else (load(root) or _load_json(os.path.join(root, F_RANK), None))
    print(table(d, n))
