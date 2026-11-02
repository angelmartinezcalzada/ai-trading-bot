"""Cerebro v3: meta-controller for the Solana memecoin module.
 archive : every tradable sighting (liq>=min, no hard veto) is labelled ONCE by replaying the BASE exit rules (cfg_base, not the
           director-tightened config) on GeckoTerminal 1m OHLCV and appended to data/labels_solana.jsonl (append-once per rid,
           never relabelled). The 7-day candidate window only feeds NEW rows; training uses the whole archive (expanding) with
           exponential time decay (half-life HALF_LIFE_D), per-mint caps (MAX_ROWS_MINT_DAY per UTC day, MAX_ROWS_MINT newest
           overall) and weight x MISMATCH_W for rows labelled under other exit parameters (cfg_hash).
 models  : Beta-Bernoulli hit-rate per binary signal (as v2, now weighted); L2 logistic regression and ridge regression on the
           winsorised return over the 23 booleans + a standardised continuous block (liquidity, momentum, age, round-trip cost,
           RugCheck, insiders, hour, source, Solana Tracker fields, market context), lambda chosen on an inner time split of the
           train set; pessimism = one standard error for a LOCAL sample size (train rows within Hamming distance LOCAL_HAMMING on
           the booleans, min LOCAL_MIN_N) so the linear models are as cautious as Beta's smallest-signal rule.
 gate    : rolling-origin 3 folds (cuts at 50/60/70 % of time, mint-episode grouping, EMBARGO_S after each cut, purged labels);
           the deployed policy (ev > brain_ev_min and score_brain >= brain_min_score) must beat the baseline (score >= min_score)
           and be positive on EVERY fold; a vote counts only with >= VOTE_NEW_ROWS new archived rows since the last counted vote;
           HYSTERESIS consecutive counted votes activate, ONE failing refit deactivates; a model switch needs SWITCH_WINS consecutive
           OOS wins. Nothing here places an order: memebot reads decide() and applies its own vetoes, floors and caps."""
import json, os, time, math, re, datetime as dt, collections, hashlib, requests, logging
try: import numpy as np
except Exception: np = None   # the linear models are optional; without numpy the Beta model runs alone
from eval_solana import sim, get
log = logging.getLogger("meme")
K, DAMP, KELLY_FRAC, MIN_TRAIN, MIN_TEST = 10, 0.3, 0.25, 60, 25
EV_MIN = 0.01   # 2026-10-31 tuned OOS (was K=20, DAMP=0.5, ev>0)
MIN_MINTS, HYSTERESIS, MAX_ROWS_MINT_DAY, MAX_ROW_AGE_H = 10, 3, 6, 7*24   # 31-oct review: activation needs >= 10 distinct mints and 3 consecutive agreeing refits
CODE = "brain/3"
try: CODE_VERSION = f"{CODE}@{int(os.path.getmtime(__file__))}"
except Exception: CODE_VERSION = CODE
ARCHIVE = os.path.join("data", "labels_solana.jsonl")
EXIT_KEYS = ("hard_stop_pct", "trail_pct_tt", "max_hold_hours", "exit_mode")            # the label's identity (cfg_hash)
SIM_KEYS = EXIT_KEYS + ("stop_pct", "max_stop_pct", "trail_pct", "runner_trail_pct", "trail_activate_pct", "partial_tp_pct", "partial_tp_frac")   # everything sim() reads
HALF_LIFE_D, MAX_ROWS_MINT, MISMATCH_W = 10, 30, 0.5
FOLD_CUTS, EMBARGO_S, EPISODE_GAP_S, FOLD_MIN_TRAIN, FOLD_MIN_TEST = (0.5, 0.6, 0.7), 3*3600, 3*3600, 30, 10
VOTE_NEW_ROWS, SWITCH_WINS, MODELS_HIST, MODELS = 25, 2, 10, ("beta", "logit", "ridge")
LAMBDAS, LOCAL_HAMMING, LOCAL_MIN_N, RET_CLIP = (2.0, 5.0, 10.0, 20.0), 2, 5, (-0.30, 1.00)
DEFAULT_ST = {"active": False, "weights": {}, "base": 0.35, "avg_win": 0.15, "avg_loss": 0.08}
RENAMED = {"insiders": "rc_insiders", "insider_conv": "insider_t1", "insider_elite": "insider_t2"}   # v2 -> v3 Beta signal names
ST_F = ("snipers_pct", "bundlers_pct", "insiders_pct", "dev_pct", "holders", "migrated", "age_h", "creator_rugs")
CTX_KEYS = ("sol_up", "sol_down", "btc_on", "risk_off", "fear_extreme", "heat_hot", "heat_cold", "launches_hi", "breadth_hi", "night_utc", "weekend")
XC = (["liq_log", "vol_liq", "h1", "m5", "age_log", "rt", "rt_missing", "top10", "holders_log", "ins", "buys", "buys_missing", "hour_sin", "hour_cos"]
      + [f"src_{i}" for i in range(6)] + [f"st_{k}" for k in ST_F] + [f"st_{k}_missing" for k in ST_F] + list(CTX_KEYS) + ["ctx_missing", "score"])
WINSOR = {"liq_log", "vol_liq", "h1", "m5", "age_log", "rt", "top10", "holders_log", "ins", "buys", "score"} | {f"st_{k}" for k in ST_F}
def _atomic_json(path, obj, **kw):
    tmp = path + ".tmp"; json.dump(obj, open(tmp, "w"), **kw); os.replace(tmp, path)
STOP = {"the","of","a","to","and","in","on","coin","token","sol","solana","inu","ai","x","by","for","is","it","pump","fun","usd","usdc","wif","meme"}
def lo(p): p = min(0.99, max(0.01, p)); return math.log(p/(1-p))
def sg(x): return 1/(1+math.exp(-x))
def _num(v):
    if isinstance(v, bool): return float(v)
    try: v = float(v); return v if math.isfinite(v) else None
    except Exception: return None
def _ts(r):
    t = r.get("_t", r.get("t"))
    if isinstance(t, (int, float)) and not isinstance(t, bool): return float(t)
    try: return dt.datetime.fromisoformat(r["ts"]).timestamp()
    except Exception: return None
def cfg_hash(cfg):
    """identity of the exit rule a label was replayed with (hard_stop_pct, trail_pct_tt, max_hold_hours, exit_mode)"""
    return hashlib.sha1(json.dumps({k: (cfg or {}).get(k) for k in EXIT_KEYS}, sort_keys=True, default=str).encode()).hexdigest()[:12]
def label_cfg(cfg, cfg_base=None):
    """the config a label is replayed with: cfg with the exit parameters of cfg_base (the owner's base rules, never the director-tightened ones)"""
    lab = dict(cfg)
    if cfg_base: lab.update({k: cfg_base[k] for k in SIM_KEYS if k in cfg_base})
    return lab
def score_brain(r):
    """the score the model learns from and decides on: the one at decide time (score_brain), else the pre-X-buzz score, else the final score"""
    for k in ("score_brain", "score_noX", "score"):
        if r.get(k) is not None: return r[k]
    return None
def insider_tier(I):
    """0 none / 1 convergence (conv >= 3) / 2 elite wallet(s) (elite >= 1); a stale snapshot is no evidence (0)"""
    if not I or I.get("stale"): return 0
    return 2 if (I.get("elite") or 0) >= 1 else 1 if (I.get("conv") or 0) >= 3 else 0
def signals(r, ctx=None):
    P = (r.get("parts") or {}); Q = P.get("parts") or {}; ctx = ctx or {}
    if not Q: return None
    S = {
     "buy_press": Q.get("buy_press", 0) >= 5, "momentum": Q.get("momentum", 0) >= 12, "velocity": Q.get("velocity", 0) >= 3,
     "uniq_buyers": Q.get("uniq_buyers", 0) >= 3, "holder_growth": Q.get("holder_growth", 0) >= 3, "liq_growth": Q.get("liq_growth", 0) > 0,
     "conc_falling": Q.get("concentration", 0) > 0, "socials": Q.get("socials", 0) >= 6, "whale_buys": P.get("whale_buys", 0) > 0,
     "whale_sells": P.get("whale_sells", 0) > 0, "bots": Q.get("bots", 0) <= -3, "rc_insiders": Q.get("insiders", 0) < 0,   # RugCheck insider networks (v2 name: insiders)
     "young": (P["age_h"] if P.get("age_h") is not None else 99) <= 24, "vol_liq_hi": (P.get("vol_liq") or 0) >= 3, "h1_hot": (P.get("h1") or 0) >= 20,
     "m5_neg": (P.get("m5") or 0) < 0, "deep_liq": (r.get("liq") or 0) >= 150000, "score_hi": (score_brain(r) or 0) >= 45}
    if "narr" in r: S["narrative"] = bool(r["narr"])
    if "heat" in r: S["heat_hot"] = r["heat"] == "hot"
    I = r.get("insider")
    if I:   # on-chain smart-money features (insider.py): ONE tiered feature (two cumulative booleans) + the sell signal
        tier = insider_tier(I); S["insider_t1"] = tier >= 1; S["insider_t2"] = tier >= 2; S["insider_sell"] = (I.get("sells") or 0) >= 2
    return S
# ---------------- continuous feature block ----------------
def _ctx_signals(C):
    """context.signals(ctx) -> {key: bool}; {} when the helper or the stamp is missing (the block then reads 0 with ctx_missing=1)"""
    if not isinstance(C, dict) or not C: return {}
    try:
        import context; out = context.signals(C)
        return out if isinstance(out, dict) else {}
    except Exception: return {}
def xraw(r):
    """raw continuous block of a candidate record (None = missing); JSON-serialisable, archived next to the label and rebuilt at decide time"""
    P = r.get("parts") or {}; R = r.get("rug") or {}; I = r.get("insider") or {}; ST = r.get("st_f") if isinstance(r.get("st_f"), dict) else None
    C = r.get("ctx") if isinstance(r.get("ctx"), dict) else None
    buys = None; bs = P.get("b_s")
    if isinstance(bs, str) and "/" in bs:
        try: b1, s1 = (float(v) for v in bs.split("/", 1)); buys = b1/(b1+s1) if b1+s1 > 0 else None
        except Exception: buys = None
    hour = None
    if C and _num(C.get("hour_utc")) is not None: hour = int(_num(C["hour_utc"])) % 24
    else:
        t = _ts(r)
        if t is not None: hour = dt.datetime.fromtimestamp(t, dt.timezone.utc).hour
    ins = None if (not I or I.get("stale")) else (_num(I.get("tok")) or 0.0)*(_num(I.get("w")) or 0.0)
    cx = _ctx_signals(C) if C else {}
    return {"liq": _num(r.get("liq")), "vol_liq": _num(P.get("vol_liq")), "h1": _num(P.get("h1")), "m5": _num(P.get("m5")), "age_h": _num(P.get("age_h")),
            "rt": _num(r.get("roundtrip_loss_pct")), "top10": _num(R.get("top10")), "holders": _num(R.get("holders")), "ins": ins, "buys": buys, "hour": hour,
            "src": r.get("src") if isinstance(r.get("src"), str) else None, "score": _num(score_brain(r)),
            "st": {k: _num(ST.get(k)) for k in ST_F} if ST else None, "cx": {k: bool(cx.get(k)) for k in CTX_KEYS} if cx else None}
def _xrow(d):
    """the raw block of a dataset row (planted rows without `x` still carry their score)"""
    x = dict(d.get("x") or {})
    if x.get("score") is None: x["score"] = _num(d.get("score"))
    return x
def xvec(x, src_top=()):
    """raw dict -> floats in XC order: log1p / clips, missing -> neutral value + flag, hour as sin/cos, src one-hot over src_top (the 6
    most frequent sources of the training set), Solana Tracker fields with per-field flags, context booleans with ctx_missing"""
    x = x or {}; g = x.get; L = lambda v: math.log1p(max(0.0, v)) if v is not None else 0.0
    rt, buys, hour, st, cx = g("rt"), g("buys"), g("hour"), (x.get("st") or {}), x.get("cx")
    v = [L(g("liq")), g("vol_liq") or 0.0, min(100.0, max(-50.0, g("h1") or 0.0)), min(50.0, max(-30.0, g("m5") or 0.0)), L(g("age_h")),
         3.0 if rt is None else rt, 1.0 if rt is None else 0.0, g("top10") or 0.0, L(g("holders")), g("ins") or 0.0,
         0.5 if buys is None else buys, 1.0 if buys is None else 0.0,
         math.sin(2*math.pi*hour/24) if hour is not None else 0.0, math.cos(2*math.pi*hour/24) if hour is not None else 0.0]
    top = (list(src_top) + [None]*6)[:6]; v += [1.0 if (s is not None and g("src") == s) else 0.0 for s in top]
    for k in ST_F:
        val = st.get(k) if x.get("st") else None
        v.append(0.0 if val is None else (L(val) if k in ("holders", "age_h") else float(val)))
    v += [1.0 if (not x.get("st") or st.get(k) is None) else 0.0 for k in ST_F]
    v += [1.0 if (cx or {}).get(k) else 0.0 for k in CTX_KEYS] + [0.0 if cx else 1.0]
    v.append((g("score") or 0.0)/100.0)
    return v
def _bits(S, keys): return sum(1 << i for i, k in enumerate(keys) if S.get(k))
def _kish(ws): return (sum(ws)**2/sum(w*w for w in ws)) if ws else 0.0
# ---------------- linear models (numpy only; no sklearn in production) ----------------
def _design(Z): return np.hstack([Z, np.ones((Z.shape[0], 1))])
def _wlogit(Z, y, w, lam, iters=40):
    """weighted L2 logistic regression on the standardised design: damped Newton steps on the convex objective
    sum(w*logloss)/sum(w) + lam/sum(w) * |coef|^2/2 (intercept unpenalised); returns (coef, intercept)"""
    A = _design(Z); S = float(w.sum()) or 1.0; k = A.shape[1]; R = np.full(k, lam/S); R[-1] = 0.0
    m = min(max(float((w*y).sum()/S), 1e-3), 1-1e-3); beta = np.zeros(k); beta[-1] = math.log(m/(1-m))
    def J(b):
        p = np.clip(1/(1+np.exp(-(A@b))), 1e-9, 1-1e-9); return float(-(w*(y*np.log(p)+(1-y)*np.log(1-p))).sum()/S + 0.5*(R*b*b).sum())
    j = J(beta)
    for _ in range(iters):
        p = 1/(1+np.exp(-(A@beta))); g = A.T@(w*(p-y))/S + R*beta
        H = (A*(w*p*(1-p))[:, None]).T@A/S + np.diag(R) + 1e-9*np.eye(k)
        try: step = np.linalg.solve(H, g)
        except Exception: step = g
        t = 1.0
        for _h in range(12):   # backtracking keeps every step a descent step (a full Newton step can overshoot on near-separable data)
            nb = beta - t*step; nj = J(nb)
            if nj <= j: break
            t *= 0.5
        else: break
        done = float(np.abs(t*step).max()) < 1e-7; beta, j = nb, nj
        if done: break
    return beta[:-1], float(beta[-1])
def _wridge(Z, y, w, lam):
    """weighted ridge regression on the standardised design (intercept unpenalised); returns (coef, intercept)"""
    A = _design(Z); S = float(w.sum()) or 1.0; k = A.shape[1]; R = np.full(k, lam/S); R[-1] = 0.0
    H = (A*w[:, None]).T@A/S + np.diag(R) + 1e-9*np.eye(k); beta = np.linalg.solve(H, A.T@(w*y)/S)
    return beta[:-1], float(beta[-1])
def _pick_lambda(Z, y, w, kind):
    """lambda from LAMBDAS by an inner time split of the (time-ordered) train set: fit on the older 70 %, score the newer 30 %
    (weighted log-loss / MSE); ties and too-small splits -> the largest lambda (most regularised)"""
    n = len(y); k = int(n*0.7)
    if k < 20 or n-k < 8 or (kind == "logit" and not (0 < float(y[:k].sum()) < k)): return max(LAMBDAS)
    best = None; wv = w[k:]; sv = float(wv.sum()) or 1.0
    for lam in LAMBDAS:
        if kind == "logit":
            c, b = _wlogit(Z[:k], y[:k], w[:k], lam); p = np.clip(1/(1+np.exp(-(Z[k:]@c+b))), 1e-6, 1-1e-6)
            loss = float(-(wv*(y[k:]*np.log(p)+(1-y[k:])*np.log(1-p))).sum()/sv)
        else:
            c, b = _wridge(Z[:k], y[:k], w[:k], lam); loss = float((wv*(Z[k:]@c+b-y[k:])**2).sum()/sv)
        if best is None or loss < best[0]-1e-12 or (abs(loss-best[0]) <= 1e-12 and lam > best[1]): best = (loss, lam)
    return best[1]
def _feat_spec(keys, rows):
    """standardisation of the full vector [booleans + XC]: winsor limits (p1/p99 of the train set) for the continuous columns,
    mu/sd for every column, src_top = the 6 most frequent sources; returns (spec, Z)"""
    src = collections.Counter(x.get("src") for x in (_xrow(d) for d in rows) if x.get("src")); src_top = [s for s, _ in src.most_common(6)]
    X = np.array([xvec(_xrow(d), src_top) for d in rows], float)
    lo_, hi_ = np.percentile(X, 1, axis=0), np.percentile(X, 99, axis=0)
    for i, name in enumerate(XC):
        if name not in WINSOR: lo_[i], hi_[i] = -1e9, 1e9
    B = np.array([[1.0 if d["S"].get(k) else 0.0 for k in keys] for d in rows], float).reshape(len(rows), len(keys))
    V = np.hstack([B, np.clip(X, lo_, hi_)]); mu = V.mean(0); sd = V.std(0); sd[sd < 1e-9] = 1.0
    return {"keys": list(keys), "xc": list(XC), "src_top": src_top, "lo": lo_.tolist(), "hi": hi_.tolist(), "mu": mu.tolist(), "sd": sd.tolist()}, (V-mu)/sd
def _vec(S, x, F):
    b = [1.0 if S.get(k) else 0.0 for k in F["keys"]]; xv = xvec(x, F.get("src_top") or ())
    xv = [min(h, max(l, v)) for v, l, h in zip(xv, F["lo"], F["hi"])]
    return (np.array(b + xv) - np.array(F["mu"]))/np.array(F["sd"])
def _feat_ok(st):
    F = st.get("feat")
    return bool(F) and np is not None and F.get("xc") == list(XC) and isinstance(F.get("keys"), list)
# ---------------- archive ----------------
def _read_archive(path):
    """labelled rows, deduplicated by rid (first line wins); unparsable or incomplete lines are skipped"""
    out = []; seen = set()
    if not os.path.exists(path): return out
    for l in open(path, encoding="utf-8", errors="replace"):
        try: a = json.loads(l)
        except Exception: continue
        if not isinstance(a, dict) or not a.get("rid") or a["rid"] in seen or not isinstance(a.get("S"), dict) or not isinstance(a.get("t"), (int, float)): continue
        if not a.get("mint") or not isinstance(a.get("ret"), (int, float)): continue
        seen.add(a["rid"]); out.append(a)
    return out
def _append_archive(path, rows):
    d = os.path.dirname(path)
    if d: os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f: f.write("".join(json.dumps(r, separators=(",", ":"), default=str) + "\n" for r in rows))
def _hard_fails(r):
    """vetoes that take a sighting out of the tradable universe. veto_class (written by memebot) decides when present: 'policy'
    fails (score / model / director / sellability skipped) keep the row, 'hard' and 'soft' remove it; a fail without a class
    falls back to the name rule (unknown -> hard, fail-closed)"""
    vc = r.get("veto_class") if isinstance(r.get("veto_class"), dict) else {}; out = []
    for f in (r.get("fail") or []):
        c = vc.get(f)
        if c is None: c = "policy" if (f.startswith("score") or f.startswith("brain_ev") or f.startswith("director") or f == "no_sellability_check") else "hard"
        if c != "policy": out.append(f)
    return out
def _training_rows(arch, chash, now):
    """archive -> training rows: per-mint caps (MAX_ROWS_MINT_DAY per UTC day, the newest MAX_ROWS_MINT overall), decay weight
    0.5^(age/HALF_LIFE_D) x MISMATCH_W when labelled under other exit parameters; sorted by t"""
    by = collections.defaultdict(list)
    for a in sorted(arch, key=lambda a: a["t"]): by[a["mint"]].append(a)
    out = []
    for m, L in by.items():
        pd = collections.Counter(); keep = []
        for a in L:
            day = int(a["t"]//86400)
            if pd[day] >= MAX_ROWS_MINT_DAY: continue
            pd[day] += 1; keep.append(a)
        for a in keep[-MAX_ROWS_MINT:]:
            w = 0.5**(max(0.0, now-a["t"])/(HALF_LIFE_D*86400))*(MISMATCH_W if a.get("cfg_hash") != chash else 1.0)
            out.append({"t": a["t"], "t_exit": a.get("t_exit", a["t"]), "S": a["S"], "x": a.get("x") or {}, "ret": a["ret"], "score": a.get("score"), "mint": m,
                        "w": round(w, 4), "cfg_hash": a.get("cfg_hash"), "rid": a["rid"], "pair": a.get("pair"), "rt": a.get("rt")})
    return sorted(out, key=lambda d: d["t"])
def _episodes(data):
    """episode id per row: sightings of one mint separated by < EPISODE_GAP_S belong together (their labels share bars);
    returns ([(mint, k)] aligned with data, {episode: first sighting t})"""
    ep, first, last, ids = {}, {}, {}, []
    for d in data:
        m, t = d["mint"], d["t"]
        if m not in last or t-last[m] >= EPISODE_GAP_S: ep[m] = ep.get(m, -1)+1; first[(m, ep[m])] = t
        last[m] = t; ids.append((m, ep[m]))
    return ids, first
def folds(data, cuts=FOLD_CUTS):
    """rolling-origin folds on time-ordered rows: cut = t0 + f*(t1-t0). An episode goes to the side of its FIRST sighting, never
    straddling the cut: train = episodes first seen before the cut, PURGED of labels whose exit lies beyond the cut; test = episodes
    first seen at or after cut + EMBARGO_S. Returns [(cut, train, test, purged_n)]"""
    if not data: return []
    ids, first = _episodes(data); t0, t1 = data[0]["t"], data[-1]["t"]; out = []
    for f in cuts:
        cut = t0 + f*(t1-t0)
        tr = [d for d, e in zip(data, ids) if first[e] < cut and d.get("t_exit", d["t"]) <= cut]
        purged = sum(1 for d, e in zip(data, ids) if first[e] < cut and d["t"] < cut and d.get("t_exit", d["t"]) > cut)
        te = [d for d, e in zip(data, ids) if first[e] >= cut + EMBARGO_S]
        out.append((cut, tr, te, purged))
    return out
def _migrate(st):
    """older brain_state.json -> v3: renamed Beta signals, pre-v3 linear models dropped (their feature layout differs), defaults filled"""
    if not isinstance(st, dict): return dict(DEFAULT_ST)
    st = dict(st); W = dict(st.get("weights")) if isinstance(st.get("weights"), dict) else {}
    for old, new in RENAMED.items():
        if old in W:
            v = W.pop(old)
            if new not in W: W[new] = v
    st["weights"] = W
    if not str(st.get("code_version") or "").startswith(CODE):
        for k in ("logit", "ridge", "feat", "bool_rows", "lambda"): st.pop(k, None)
        if st.get("model_choice") in ("logit", "ridge"): st["model_choice"] = "beta"
    for k, v in DEFAULT_ST.items(): st.setdefault(k, v)
    if "model_choice" in st and st["model_choice"] not in MODELS: st["model_choice"] = "beta"
    return st
class Brain:
    signals = staticmethod(signals)
    def __init__(s, path="brain_state.json"):
        s.path = path; s.st = dict(DEFAULT_ST); s.archive = ARCHIVE; s.paths = []
        if os.path.exists(path):
            try: s.st = json.load(open(path))
            except Exception as e: log.warning("[brain] %s unreadable (%s): shadow mode until the next refit", path, e)
        s.st = _migrate(s.st); s.ctx = {}
    @property
    def playbook(s): return s.ctx.get("playbook") or {"score_adj": 0, "size_mult": 1.0, "name": "sin contexto"}
    # ---------------- context (regime / heat / narratives) ----------------
    def update_context(s, gecko_pools, sol_change24, btc_on):
        now = time.time(); ctx = s.ctx
        newp = [p for p in gecko_pools if p.get("new")]
        vol = sum(p.get("vol_h1", 0) for p in newp); n = len(newp)
        hist = ctx.setdefault("heat_hist", []); hist.append((now, vol)); ctx["heat_hist"] = [h for h in hist if now-h[0] < 6*3600]
        med = sorted(v for _, v in ctx["heat_hist"])[len(ctx["heat_hist"])//2] if ctx["heat_hist"] else vol
        ctx["heat"] = "hot" if vol > 1.3*med and len(ctx["heat_hist"]) > 10 else "cold" if vol < 0.7*med and len(ctx["heat_hist"]) > 10 else "normal"
        ctx["heat_vol_h1"], ctx["new_pools"] = round(vol), n
        ctx["sol_trend"] = "up" if sol_change24 > 2 else "down" if sol_change24 < -4 else "flat"; ctx["sol_24h"] = round(sol_change24, 2)
        ctx["btc_on"] = btc_on
        words = ctx.setdefault("words", [])
        for p in gecko_pools:
            for w in set(re.findall(r"[a-z]{3,}", (p.get("name", "") + " " + p.get("sym", "")).lower())) - STOP: words.append((now, w))
        ctx["words"] = [x for x in words if now-x[0] < 2*3600]
        cnt = collections.Counter(w for _, w in ctx["words"]); ctx["narratives"] = [w for w, c in cnt.most_common(8) if c >= 4]
        pb = {"hot": (-5, 1.0), "normal": (0, 0.8), "cold": (8, 0.5)}[ctx["heat"]]
        mult = pb[1]*(0.6 if ctx["sol_trend"] == "down" else 1.0)*(0.8 if btc_on is False else 1.0)
        ctx["playbook"] = {"score_adj": pb[0], "size_mult": round(mult, 2), "name": f"{ctx['heat']}/SOL-{ctx['sol_trend']}"}
        return ctx
    def narrative(s, name, sym):
        ws = set(re.findall(r"[a-z]{3,}", (name + " " + sym).lower())); return sorted(ws & set(s.ctx.get("narratives", [])))
    # ---------------- microstructure ----------------
    def depth_curve(s, quote, mint, usdc):
        """Jupiter quotes at several sizes -> price impact curve; returns max size with impact <= 1.5% (MEV/sandwich-aware cap)"""
        curve = {}
        for usd in (50, 200, 1000):
            q = quote(usdc, mint, usd*1e6)
            if q: curve[usd] = round(float(q.get("priceImpactPct") or 0)*100, 3)
            time.sleep(0.25)
        ok = [u for u, imp in curve.items() if imp <= 1.5]
        cap = max(ok) if ok else 0
        if cap == 1000: cap = 1500
        return curve, cap
    # ---------------- decision ----------------
    def _p_beta(s, S, st=None):
        """Beta-Bernoulli log-odds model -> (p, n_eff); n_eff = smallest (weight-effective) sample behind an active signal (pessimism source)"""
        st = st or s.st; W = st.get("weights", {}); base = st.get("base", 0.35); z = lo(base); ns = []
        for k, on in S.items():
            w = W.get(k)
            if not w: continue
            z += DAMP*(lo(w["p_on"] if on else w["p_off"])-lo(base)); ns.append(w.get("ne_on" if on else "ne_off", w["n_on" if on else "n_off"]))
        return sg(z), (min(ns) if ns else st.get("n", 0))
    @staticmethod
    def local_n(S, st):
        """LOCAL sample size behind a linear prediction: train rows within Hamming distance LOCAL_HAMMING on the boolean block
        (min LOCAL_MIN_N); no stored rows -> the minimum (fail-closed)"""
        keys = st.get("keys") or (st.get("logit") or {}).get("keys") or []; rows = st.get("bool_rows") or []
        if not rows or not keys: return LOCAL_MIN_N
        b = _bits(S, keys); return max(LOCAL_MIN_N, sum(1 for r in rows if bin(b ^ int(r)).count("1") <= LOCAL_HAMMING))
    def _p_logit(s, S, score, st=None, x=None):
        """L2 logistic regression (numpy) on the booleans + continuous block -> (p, local n_eff); (None, 0) when not fitted"""
        st = st or s.st; L = st.get("logit")
        if not L or not _feat_ok(st) or st["feat"]["keys"] != L.get("keys"): return None, 0
        x = dict(x or {})
        if x.get("score") is None: x["score"] = _num(score)
        z = _vec(S, x, st["feat"]); return float(sg(float(z@np.array(L["w"]) + L["b"]))), Brain.local_n(S, st)
    def _ret(s, S, score, st=None, x=None):
        """ridge regression on the winsorised return -> (ret_hat, ret_lb = ret_hat - resid_sd/sqrt(local n_eff)); (None, None) when not fitted"""
        st = st or s.st; R = st.get("ridge")
        if not R or not _feat_ok(st): return None, None
        x = dict(x or {})
        if x.get("score") is None: x["score"] = _num(score)
        z = _vec(S, x, st["feat"]); rh = float(z@np.array(R["w"]) + R["b"])
        return rh, rh - float(R["resid_sd"])/math.sqrt(Brain.local_n(S, st))
    def _p(s, S, score, st=None, x=None):
        st = st or s.st
        if st.get("model_choice") in ("logit", "ridge"):
            p, n = s._p_logit(S, score, st, x)
            if p is not None: return p, n
        return s._p_beta(S, st)
    @staticmethod
    def p_low(p, n, z=1.0):
        """pessimistic win probability: one standard error below p for the sample size behind the estimate"""
        return max(0.01, p - z*math.sqrt(max(p*(1-p), 1e-6)/max(n, 1)))
    def _ev(s, S, score=None, cfg=None, st=None, x=None):
        """pessimistic NET expected value per unit of position minus the director's fixed-cost share: p_low x avg_win - (1-p_low) x
        avg_loss (beta / logit) or the ridge lower bound of the return (ridge)"""
        st = st or s.st; fixed = float((cfg or {}).get("director_fixed_share") or 0.0)
        if st.get("model_choice") == "ridge":
            rh, rl = s._ret(S, score, st, x)
            if rl is not None: return rl - fixed
        p, n = s._p(S, score, st, x); pl = Brain.p_low(p, n)
        return pl*st["avg_win"] - (1-pl)*st["avg_loss"] - fixed
    def decide(s, rec, equity, cfg):
        S = signals(rec)
        if S is None: return None
        st = s.st; score = score_brain(rec); x = xraw(rec); choice = st.get("model_choice", "beta"); model = "beta"
        p = n = None
        if choice in ("logit", "ridge"):
            p, n = s._p_logit(S, score, st, x)
            if p is not None: model = "logit"
        if p is None: p, n = s._p_beta(S, st)
        pl = Brain.p_low(p, n); rh, rl = s._ret(S, score, st, x)
        aw, al = st.get("avg_win", 0.15), st.get("avg_loss", 0.08); fixed = float(cfg.get("director_fixed_share") or 0.0)
        if choice == "ridge" and rl is not None: ev = rl - fixed; model = "ridge"
        else: ev = pl*aw - (1-pl)*al - fixed
        ev_min = float(cfg.get("brain_ev_min", EV_MIN)); b = aw/al if al else 1
        kelly = max(0.0, (pl*b-(1-pl))/b)*KELLY_FRAC
        mult = s.ctx.get("playbook", {}).get("size_mult", 1.0)
        size = min(cfg["position_pct"], kelly)*mult*equity
        return {"p": round(p, 3), "p_low": round(pl, 3), "n_eff": int(n), "ev_pct": round(ev*100, 2), "ev_min_pct": round(ev_min*100, 2), "ev_ok": ev > ev_min,
                "kelly_pct": round(kelly*100, 2), "size": round(size, 2), "active": st.get("active", False), "model": model,
                "ret_hat": round(rh, 4) if rh is not None else None, "ret_lb": round(rl, 4) if rl is not None else None, "on": [k for k, v in S.items() if v]}
    # ---------------- learning ----------------
    def build_dataset(s, cfg, max_fetch=40, cfg_base=None):
        """training rows = the labelled ARCHIVE (expanding, never relabelled) + the tradable sightings of the last MAX_ROW_AGE_H that
        are not archived yet, labelled now (bars fetched/cached, replay with the BASE exit rules of cfg_base when given) and appended
        once per rid. Returns [{t, t_exit, S, x, ret, score, mint, w, cfg_hash, rid, pair, rt}] sorted by t after the per-mint caps,
        with the decay weights; sets s._archive_n, s._cfg_mismatch and s.paths = [(bars, rt)] for the rows whose candles are cached."""
        lab = label_cfg(cfg, cfg_base); chash = cfg_hash(lab); now = time.time(); arch_f = getattr(s, "archive", ARCHIVE); arch = _read_archive(arch_f); rids = {a["rid"] for a in arch}
        cache_f = "ohlcv_cache.json"
        try: oc = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
        except Exception as e: log.warning("[brain] %s unreadable (%s): rebuilding", cache_f, e); oc = {}
        rows = []; last = {}; per_day = collections.Counter((a["mint"], int(a["t"]//86400)) for a in arch)
        lines = open("candidates_solana.jsonl") if os.path.exists("candidates_solana.jsonl") else []
        if not lines: log.info("[brain] candidates_solana.jsonl ausente: solo el archivo (%d filas)", len(arch))
        for l in lines:
            try: r = json.loads(l)
            except Exception: continue
            if r.get("liq", 0) < cfg["min_liquidity_usd"] or not r.get("pair") or score_brain(r) is None or not r.get("mint"): continue
            # tradable universe = no hard veto; the model's own rejections (brain_ev<=0), director gates and book-state skips
            # (no_sellability_check: positions full / halted) stay in, otherwise the model only ever learns from what it already liked
            if _hard_fails(r): continue
            t = _ts(r)
            if t is None: continue
            rid = r.get("rid") or f"{r['mint']}:{r.get('ts')}"
            if rid in rids: last[r["mint"]] = max(last.get(r["mint"], 0), t); continue   # archived: never relabelled, keeps the 10-min spacing
            if now-t > MAX_ROW_AGE_H*3600: continue
            if t-last.get(r["mint"], 0) < 600: continue          # one sample per token per 10 min
            last[r["mint"]] = t; r["_t"] = t; r["_rid"] = rid; rows.append(r)
        need = {}
        for r in rows:   # pairs whose rows still lack candles, oldest unlabelled row first; a (mint, day) already at the cap fetches nothing
            if per_day[(r["mint"], int(r["_t"]//86400))] >= MAX_ROWS_MINT_DAY: continue
            if now-r["_t"] > 1200 and (r["pair"] not in oc or oc[r["pair"]]["at"] < r["_t"]+1200): need[r["pair"]] = min(need.get(r["pair"], r["_t"]), r["_t"])
        for pair in sorted(need, key=need.get)[:max_fetch]:
            time.sleep(2.5)
            d = get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair}/ohlcv/minute", aggregate=1, limit=1000, currency="usd")
            try:
                bars = {b[0]: b for b in (oc.get(pair) or {}).get("bars", [])}
                bars.update({x[0]: x[:5] for x in d["data"]["attributes"]["ohlcv_list"]})   # MERGE: a refetch used to replace the bars with the latest 1000, so older rows lost their first candles
                cut = time.time()-MAX_ROW_AGE_H*3600
                oc[pair] = {"at": time.time(), "bars": sorted(b for b in bars.values() if b[0] >= cut)[-12000:]}   # prune: the merged cache must not grow without bound inside the live process
            except Exception: pass
        oc = {k: v for k, v in oc.items() if time.time()-v["at"] < 3*86400}
        _atomic_json(cache_f, oc)
        def path_of(pair, t):
            o = oc.get(pair)
            if not o or o["at"]-t < 1200: return None
            p = [b for b in o["bars"] if b[0] >= t]
            return p if len(p) >= 15 and p[0][0]-t <= 300 else None   # the replay must start within 5 min of the sighting
        new = []
        for r in rows:
            path = path_of(r["pair"], r["_t"])
            if not path: continue
            rt = _num(r.get("roundtrip_loss_pct")); rt_src = r.get("rt_src") if r.get("rt_src") in ("measured", "imputed") else ("measured" if rt is not None else None)
            info = {}; ret = sim(path, rt if rt is not None else 3.0, lab, info); S = signals(r)
            if ret is None or S is None: continue
            if info.get("exit") in (None, "open") and path[-1][0]-path[0][0] < lab.get("max_hold_hours", 3)*3600: continue   # a 20-minute mark-to-market is not a label
            day = (r["mint"], int(r["_t"]//86400))
            if per_day[day] >= MAX_ROWS_MINT_DAY: continue       # cap AFTER labelling: an established token (144 sightings/day) must not define the base rate
            per_day[day] += 1
            row = {"rid": r["_rid"], "t": r["_t"], "t_exit": info.get("t_exit", path[-1][0]), "mint": r["mint"], "pair": r["pair"], "S": S, "x": xraw(r), "ret": ret,
                   "exit": info.get("exit"), "rt": rt if rt is not None else 3.0, "rt_src": rt_src, "cfg_hash": chash, "code": CODE, "score": score_brain(r)}
            if isinstance(r.get("ctx"), dict): row["ctx"] = r["ctx"]
            if isinstance(r.get("st_f"), dict): row["st_f"] = r["st_f"]
            new.append(row)
        if new: _append_archive(arch_f, new); arch += new
        s._archive_n = len(arch); s._cfg_mismatch = sum(1 for a in arch if a.get("cfg_hash") != chash); s._cfg_hash = chash
        data = _training_rows(arch, chash, now)
        s.paths = [(p, d["rt"] if d.get("rt") is not None else 3.0) for d in data for p in [path_of(d.get("pair"), d["t"])] if p]
        return data
    def fit(s, data):
        """weighted Beta model (+ feature spec, logistic and ridge models when numpy and >= 30 rows with both outcomes)"""
        n = len(data); ws = [float(d.get("w", 1.0) or 0.0) for d in data]; ys = [1.0 if d["ret"] > 0 else 0.0 for d in data]
        sw = sum(ws); wins = sum(w*y for w, y in zip(ws, ys)); nw = int(sum(ys))
        base = (wins+K*0.35)/(sw+K); keys = sorted({k for d in data for k in d["S"]})
        W = {}
        for k in keys:
            on = [(w, y, d["ret"]) for d, w, y in zip(data, ws, ys) if d["S"].get(k)]; off = [(w, y, d["ret"]) for d, w, y in zip(data, ws, ys) if not d["S"].get(k)]
            so, sf = sum(w for w, _, _ in on), sum(w for w, _, _ in off)
            p_on = (sum(w*y for w, y, _ in on)+K*base)/(so+K); p_off = (sum(w*y for w, y, _ in off)+K*base)/(sf+K)
            W[k] = {"p_on": round(p_on, 3), "p_off": round(p_off, 3), "n_on": len(on), "n_off": len(off),
                    "ne_on": round(_kish([w for w, _, _ in on]), 1), "ne_off": round(_kish([w for w, _, _ in off]), 1),
                    "ret_on_%": round(sum(w*r for w, _, r in on)/so*100, 2) if so > 0 else None}
        win = [(w, d["ret"]) for d, w in zip(data, ws) if d["ret"] > 0]; los = [(w, -d["ret"]) for d, w in zip(data, ws) if d["ret"] <= 0]
        aw = (sum(w*r for w, r in win)+5*0.15)/(sum(w for w, _ in win)+5); al = (sum(w*r for w, r in los)+5*0.08)/(sum(w for w, _ in los)+5)
        out = {"base": round(base, 3), "weights": W, "avg_win": round(aw, 4), "avg_loss": round(al, 4), "n": n, "keys": keys, "bool_rows": [_bits(d["S"], keys) for d in data]}
        if np is not None and n >= 30 and 0 < nw < n:
            F, Z = _feat_spec(keys, data); y = np.array(ys); w = np.array(ws); yr = np.clip(np.array([d["ret"] for d in data], float), *RET_CLIP)
            lam = _pick_lambda(Z, y, w, "logit"); c, b = _wlogit(Z, y, w, lam)
            lam_r = _pick_lambda(Z, yr, w, "ridge"); cr, br = _wridge(Z, yr, w, lam_r); res = yr-(Z@cr+br)
            sd = math.sqrt(float((w*res*res).sum()/max(float(w.sum()), 1e-9)))
            out["feat"] = F; out["lambda"] = {"logit": lam, "ridge": lam_r}
            out["logit"] = {"w": [round(float(v), 5) for v in c], "b": round(b, 5), "n": n, "lambda": lam, "keys": keys}
            out["ridge"] = {"w": [round(float(v), 5) for v in cr], "b": round(br, 5), "n": n, "lambda": lam_r, "resid_sd": round(max(sd, 0.01), 5)}
        return out
    def learn(s, cfg, cfg_base=None):
        """hourly refit: archive + new labels (cfg_base = the owner's base exit rules; the director-tightened cfg still defines the
        policy floors), 3-fold rolling-origin validation of the deployed policy, model choice with SWITCH_WINS consecutive wins,
        vote accounting (>= VOTE_NEW_ROWS new archived rows per counted vote), HYSTERESIS, atomic state write"""
        data = s.build_dataset(cfg, cfg_base=cfg_base) if cfg_base is not None else s.build_dataset(cfg)
        prev = s.st if isinstance(s.st, dict) else {}; poos = prev.get("oos") if isinstance(prev.get("oos"), dict) else {}
        hist = [m for m in (poos.get("models_hist") or []) if m in MODELS][-(MODELS_HIST-1):]
        choice = prev.get("model_choice") if prev.get("model_choice") in MODELS else "beta"
        arch_n = getattr(s, "_archive_n", None); vote_n = poos.get("vote_archive_n"); streak = max(0, int(prev.get("active_votes", 0) or 0)); active = bool(prev.get("active", False))
        out = {"updated": dt.datetime.now().isoformat(timespec="seconds"), "code_version": CODE_VERSION, "n_labelled": len(data), "active": active, "active_votes": streak,
               "archive_n": arch_n, "decay_half_life_d": HALF_LIFE_D, "cfg_hash": cfg_hash(label_cfg(cfg, cfg_base)), "cfg_hash_mismatch_n": getattr(s, "_cfg_mismatch", 0), "folds": []}
        avg = lambda rows: (sum(d["ret"] for d in rows)/len(rows)) if rows else None
        pct = lambda v: round(v*100, 2) if v is not None else None
        if len(data) >= MIN_TRAIN + MIN_TEST:
            floor = cfg.get("brain_min_score", 45); ev_min = float(cfg.get("brain_ev_min", EV_MIN)); base_floor = cfg["min_score"]
            tmp = Brain.__new__(Brain); tmp.ctx = {}; FR = []
            for cut, tr, te, purged in folds(data):
                m = s.fit(tr) if tr else {"base": 0.35, "weights": {}, "avg_win": 0.15, "avg_loss": 0.08, "n": 0}; stats = {}
                for ch in MODELS:
                    if ch != "beta" and not m.get(ch): continue
                    tmp.st = {**m, "model_choice": ch}
                    sel = [d for d in te if tmp._ev(d["S"], d.get("score"), cfg, x=_xrow(d)) > ev_min and (d.get("score") or 0) >= floor]
                    q = {"trades": len(sel), "mints": len({d["mint"] for d in sel}), "avg": avg(sel)}
                    if te and ch != "ridge": q["brier"] = round(sum((tmp._p(d["S"], d.get("score"), x=_xrow(d))[0]-(1.0 if d["ret"] > 0 else 0.0))**2 for d in te)/len(te), 4)
                    elif te: q["mse"] = round(sum((min(RET_CLIP[1], max(RET_CLIP[0], d["ret"]))-tmp._ret(d["S"], d.get("score"), x=_xrow(d))[0])**2 for d in te)/len(te), 5)
                    stats[ch] = q
                basel = [d for d in te if (d.get("score") or 0) >= base_floor]
                FR.append({"cut": cut, "tr": tr, "te": te, "purged": purged, "m": m, "stats": stats, "base_avg": avg(basel), "base_n": len(basel), "all_avg": avg(te),
                           "valid": len(tr) >= FOLD_MIN_TRAIN and len(te) >= FOLD_MIN_TEST})
            H = FR[-1]
            # model choice: a candidate wins a refit when its deployed policy beats Beta's on EVERY fold (>= 8 trades on the
            # headline fold; the logit also needs Brier <= Beta's); it is deployed only after SWITCH_WINS consecutive wins
            ok = {}
            for ch in ("logit", "ridge"):
                if any(ch not in fr["stats"] or "beta" not in fr["stats"] for fr in FR): continue
                hs = H["stats"][ch]
                if hs["trades"] < 8 or (ch == "logit" and (hs.get("brier") is None or hs["brier"] > H["stats"]["beta"].get("brier", 1e9))): continue
                if all(fr["stats"][ch]["avg"] is not None and (fr["stats"]["beta"]["avg"] is None or fr["stats"][ch]["avg"] > fr["stats"]["beta"]["avg"]) for fr in FR):
                    ok[ch] = sum(fr["stats"][ch]["avg"] for fr in FR)/len(FR)
            winner = max(ok, key=ok.get) if ok else "beta"; hist.append(winner); switched = False
            if winner != choice and len(hist) >= SWITCH_WINS and all(h == winner for h in hist[-SWITCH_WINS:]): choice, switched, streak, active = winner, True, 0, False
            if choice != "beta" and any(choice not in fr["stats"] for fr in FR): choice = "beta"   # the model is not fitted everywhere -> Beta (fail-closed)
            # the deployed policy must beat the baseline and be positive on EVERY (valid) fold; the headline fold also needs
            # >= 8 trades over >= MIN_MINTS mints (31-oct rule)
            folds_ok = all(fr["valid"] and fr["stats"][choice]["trades"] >= 1 and fr["stats"][choice]["avg"] > 0 and (fr["base_avg"] is None or fr["stats"][choice]["avg"] > fr["base_avg"]) for fr in FR)
            hs = H["stats"][choice]; vote = bool(folds_ok and hs["trades"] >= 8 and hs["mints"] >= MIN_MINTS)
            counted = vote and (arch_n is None or vote_n is None or arch_n - vote_n >= VOTE_NEW_ROWS)   # arch_n None = dataset injected (tests / research): no archive to count
            if not vote: streak = 0
            elif counted: streak += 1; vote_n = arch_n
            active = vote and (active or streak >= HYSTERESIS)   # fail-closed: ONE failing refit deactivates; HYSTERESIS counted votes activate
            tmp.st = {**H["m"], "model_choice": choice}; bins = collections.defaultdict(lambda: [0, 0.0, 0])
            for d in H["te"]:
                pp = tmp._p(d["S"], d.get("score"), x=_xrow(d))[0]; b_ = min(4, int(pp*5)); bins[b_][0] += 1; bins[b_][1] += pp; bins[b_][2] += 1 if d["ret"] > 0 else 0
            out["calibration"] = [{"bin": f"{b_*20}-{b_*20+20}%", "n": v[0], "p_avg": round(v[1]/v[0], 3), "win_rate": round(v[2]/v[0], 3)} for b_, v in sorted(bins.items())]
            out["folds"] = [{"cut": dt.datetime.fromtimestamp(fr["cut"]).isoformat(timespec="minutes"), "frac": f, "n_train": len(fr["tr"]), "n_test": len(fr["te"]), "purged": fr["purged"], "valid": fr["valid"],
                             "brain_n": fr["stats"][choice]["trades"], "brain_avg_ret_%": pct(fr["stats"][choice]["avg"]), "baseline_n": fr["base_n"], "baseline_avg_ret_%": pct(fr["base_avg"]),
                             "all_avg_ret_%": pct(fr["all_avg"]), "models": {ch: {"n": q["trades"], "avg_ret_%": pct(q["avg"])} for ch, q in fr["stats"].items()}} for fr, f in zip(FR, FOLD_CUTS)]
            cand = {ch: {"trades": q["trades"], "mints": q["mints"], "avg_ret_%": pct(q["avg"]), **({"brier": q["brier"]} if "brier" in q else {}), **({"mse": q["mse"]} if "mse" in q else {})} for ch, q in H["stats"].items()}
            out["oos"] = {"n_test": len(H["te"]), "brain_trades": hs["trades"], "brain_mints": hs["mints"], "brain_avg_ret_%": pct(hs["avg"]),
                          "baseline_trades": H["base_n"], "baseline_avg_ret_%": pct(H["base_avg"]), "all_avg_ret_%": pct(H["all_avg"]), "purged_train_rows": H["purged"],
                          "policy": f"ev>{ev_min:g} and score>={floor}", "models": cand, "model_choice": choice, "winner": winner, "models_hist": hist[-MODELS_HIST:], "switched": switched,
                          "folds_ok": folds_ok, "vote": vote, "vote_counted": bool(counted), "vote_archive_n": vote_n, "n_folds": len(FR)}
            out["active_votes"] = streak; out["active"] = bool(active)
        else:
            out["oos"] = {"note": f"necesita {MIN_TRAIN+MIN_TEST} muestras etiquetadas (tiene {len(data)}) -> modo sombra", "models_hist": hist, "vote_archive_n": vote_n}; out["active"] = False; out["active_votes"] = 0
        full = s.fit(data) if data else {"base": 0.35, "weights": {}, "avg_win": 0.15, "avg_loss": 0.08, "n": 0}
        out.update(full); out["model_choice"] = choice if (choice == "beta" or full.get(choice)) else "beta"; s.st = out; _atomic_json(s.path, out, indent=1)
        log.info("[brain] learned n=%d archive=%s active=%s model=%s oos=%s", len(data), arch_n, out["active"], out["model_choice"], {k: v for k, v in out["oos"].items() if k != "models"}); return out
def _logit_fit(X, y, l2=1.0, w=None):
    """v2-style helper kept for research scripts: standardised L2 logistic regression on a raw design -> {mu, sd, w, b, n}"""
    X = np.array(X, float); y = np.array(y, float); mu = X.mean(0); sd = X.std(0); sd[sd < 1e-9] = 1.0
    c, b = _wlogit((X-mu)/sd, y, np.ones(len(y)) if w is None else np.array(w, float), l2)
    return {"mu": mu.tolist(), "sd": sd.tolist(), "w": [round(float(v), 5) for v in c], "b": round(b, 5), "n": int(len(y))}
if __name__ == "__main__":
    c = json.load(open("config.json"))["exchanges"]["solana"]; b = Brain(); o = b.learn(c)
    print(json.dumps({k: o[k] for k in ("n_labelled", "archive_n", "active", "oos", "folds", "base", "avg_win", "avg_loss", "lambda") if k in o}, indent=1))
    print(sorted(((k, v["p_on"], v["n_on"], v["ret_on_%"]) for k, v in o["weights"].items()), key=lambda x: -x[1]))
