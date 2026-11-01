"""Cerebro: meta-controller for the Solana memecoin module.
 dataset : every candidate sighting (liq>=min, hard filters known) labelled by replaying the bot's exit rules on GeckoTerminal 1m OHLCV
 model   : Beta-Bernoulli hit-rate per binary signal (shrunk to base rate, prior strength K), combined in log-odds with
           correlation damping -> calibrated P(win); EV = p*avgWin - (1-p)*avgLoss (costs already inside replay)
 sizing  : fractional Kelly (KELLY_FRAC) capped by position_pct and by microstructure (max size with impact <= max_impact)
 regime  : SOL trend + memecoin heat (new-pool launches / volume) + BTC regime -> playbook (thresholds & size multiplier)
 narrative: hot words in trending names/symbols (last 2h) -> signal
 learning: hourly refit; walk-forward check (train older 70% / test newest 30%) -> brain only drives entries if its
           out-of-sample EV beats the baseline score rule with >= MIN_TEST labelled tests; otherwise shadow mode (logged)."""
import json, os, time, math, re, datetime as dt, collections, requests, logging
try: import numpy as np
except Exception: np = None   # the logistic model is optional; without numpy the Beta model runs alone
from eval_solana import sim, get
log = logging.getLogger("meme")
K, DAMP, KELLY_FRAC, MIN_TRAIN, MIN_TEST = 10, 0.3, 0.25, 60, 25
EV_MIN = 0.01   # 2026-10-31 tuned OOS (was K=20, DAMP=0.5, ev>0)
MIN_MINTS, HYSTERESIS, MAX_ROWS_MINT_DAY, MAX_ROW_AGE_H = 10, 3, 6, 7*24   # 31-oct review: activation needs >= 10 distinct mints and 3 consecutive agreeing refits
def _atomic_json(path, obj, **kw):
    tmp = path + ".tmp"; json.dump(obj, open(tmp, "w"), **kw); os.replace(tmp, path)
STOP = {"the","of","a","to","and","in","on","coin","token","sol","solana","inu","ai","x","by","for","is","it","pump","fun","usd","usdc","wif","meme"}
def lo(p): p = min(0.99, max(0.01, p)); return math.log(p/(1-p))
def sg(x): return 1/(1+math.exp(-x))
def signals(r, ctx=None):
    P = (r.get("parts") or {}); Q = P.get("parts") or {}; ctx = ctx or {}
    if not Q: return None
    S = {
     "buy_press": Q.get("buy_press", 0) >= 5, "momentum": Q.get("momentum", 0) >= 12, "velocity": Q.get("velocity", 0) >= 3,
     "uniq_buyers": Q.get("uniq_buyers", 0) >= 3, "holder_growth": Q.get("holder_growth", 0) >= 3, "liq_growth": Q.get("liq_growth", 0) > 0,
     "conc_falling": Q.get("concentration", 0) > 0, "socials": Q.get("socials", 0) >= 6, "whale_buys": P.get("whale_buys", 0) > 0,
     "whale_sells": P.get("whale_sells", 0) > 0, "bots": Q.get("bots", 0) <= -3, "insiders": Q.get("insiders", 0) < 0,
     "young": (P["age_h"] if P.get("age_h") is not None else 99) <= 24, "vol_liq_hi": (P.get("vol_liq") or 0) >= 3, "h1_hot": (P.get("h1") or 0) >= 20,
     "m5_neg": (P.get("m5") or 0) < 0, "deep_liq": (r.get("liq") or 0) >= 150000, "score_hi": (r.get("score") or 0) >= 45}
    if "narr" in r: S["narrative"] = bool(r["narr"])
    if "heat" in r: S["heat_hot"] = r["heat"] == "hot"
    I = r.get("insider")
    if I:   # on-chain smart-money features (insider.py) -> learned like every other Cerebro signal
        S["insider_conv"] = I.get("conv", 0) >= 3; S["insider_elite"] = I.get("elite", 0) >= 1; S["insider_sell"] = I.get("sells", 0) >= 2
    return S
class Brain:
    def __init__(s, path="brain_state.json"):
        s.path = path; s.st = {"active": False, "weights": {}, "base": 0.35, "avg_win": 0.15, "avg_loss": 0.08}
        if os.path.exists(path):
            try: s.st = json.load(open(path))
            except Exception as e: log.warning("[brain] %s unreadable (%s): shadow mode until the next refit", path, e)
        s.ctx = {}
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
        """Beta-Bernoulli log-odds model -> (p, n_eff); n_eff = smallest sample behind an active signal (pessimism source)"""
        st = st or s.st; W = st.get("weights", {}); base = st.get("base", 0.35); z = lo(base); ns = []
        for k, on in S.items():
            w = W.get(k)
            if not w: continue
            z += DAMP*(lo(w["p_on"] if on else w["p_off"])-lo(base)); ns.append(w["n_on"] if on else w["n_off"])
        return sg(z), (min(ns) if ns else st.get("n", 0))
    def _p_logit(s, S, score, st=None):
        """L2 logistic regression (numpy) on the same binary signals + score/100 -> (p, n_train); None when not fitted"""
        st = st or s.st; L = st.get("logit")
        if not L or np is None: return None, 0
        x = np.array([1.0 if S.get(k) else 0.0 for k in L["keys"]] + [(score or 0)/100.0]); x = (x-np.array(L["mu"]))/np.array(L["sd"])
        return float(sg(float(np.dot(x, np.array(L["w"])) + L["b"]))), L["n"]
    def _p(s, S, score, st=None):
        st = st or s.st
        if st.get("model_choice") == "logit":
            p, n = s._p_logit(S, score, st)
            if p is not None: return p, n
        return s._p_beta(S, st)
    @staticmethod
    def p_low(p, n, z=1.0):
        """pessimistic win probability: one standard error below p for the sample size behind the estimate"""
        return max(0.01, p - z*math.sqrt(max(p*(1-p), 1e-6)/max(n, 1)))
    def _ev(s, S, score=None, cfg=None, st=None):
        """pessimistic NET expected value per unit of position: p_low x avg_win - (1-p_low) x avg_loss - fixed-cost share (director)"""
        st = st or s.st; p, n = s._p(S, score, st); pl = Brain.p_low(p, n)
        return pl*st["avg_win"] - (1-pl)*st["avg_loss"] - float((cfg or {}).get("director_fixed_share") or 0.0)
    def decide(s, rec, equity, cfg):
        S = signals(rec)
        if S is None: return None
        p, n = s._p(S, rec.get("score"), s.st); pl = Brain.p_low(p, n)
        aw, al = s.st["avg_win"], s.st["avg_loss"]; fixed = float(cfg.get("director_fixed_share") or 0.0)
        ev = pl*aw - (1-pl)*al - fixed; ev_min = float(cfg.get("brain_ev_min", EV_MIN)); b = aw/al if al else 1
        kelly = max(0.0, (pl*b-(1-pl))/b)*KELLY_FRAC
        mult = s.ctx.get("playbook", {}).get("size_mult", 1.0)
        size = min(cfg["position_pct"], kelly)*mult*equity
        return {"p": round(p, 3), "p_low": round(pl, 3), "n_eff": int(n), "ev_pct": round(ev*100, 2), "ev_min_pct": round(ev_min*100, 2), "ev_ok": ev > ev_min,
                "kelly_pct": round(kelly*100, 2), "size": round(size, 2), "active": s.st.get("active", False), "model": s.st.get("model_choice", "beta"),
                "on": [k for k, v in S.items() if v]}
    # ---------------- learning ----------------
    def build_dataset(s, cfg, max_fetch=40):
        cache_f = "ohlcv_cache.json"
        try: oc = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
        except Exception as e: log.warning("[brain] %s unreadable (%s): rebuilding", cache_f, e); oc = {}
        rows = []; last = {}; per_day = collections.Counter()
        for l in open("candidates_solana.jsonl"):
            try: r = json.loads(l)
            except Exception: continue
            if r.get("liq", 0) < cfg["min_liquidity_usd"] or not r.get("pair") or r.get("score") is None: continue
            # tradable universe = no hard veto; the model's own rejections (brain_ev<=0) and book-state skips (no_sellability_check:
            # positions full / halted) stay in, otherwise the model only ever learns from what it already liked (feedback loop)
            hard = [f for f in r["fail"] if not (f.startswith("score") or f.startswith("brain_ev") or f.startswith("director") or f == "no_sellability_check")]   # director gates (window / cap / play) are not vetoes: those rows must keep teaching the model
            if hard: continue
            t = dt.datetime.fromisoformat(r["ts"]).timestamp()
            if time.time()-t > MAX_ROW_AGE_H*3600: continue
            if t-last.get(r["mint"], 0) < 600: continue          # one sample per token per 10 min
            last[r["mint"]] = t; r["_t"] = t; rows.append(r)
        need = {}
        for r in rows:   # pairs whose rows still lack candles, oldest unlabelled row first (a fetch lottery over every pair starved new rows of their first candles)
            if time.time()-r["_t"] > 1200 and (r["pair"] not in oc or oc[r["pair"]]["at"] < r["_t"]+1200): need[r["pair"]] = min(need.get(r["pair"], r["_t"]), r["_t"])
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
        data = []
        for r in rows:
            o = oc.get(r["pair"])
            if not o or o["at"]-r["_t"] < 1200: continue
            path = [b for b in o["bars"] if b[0] >= r["_t"]]
            if len(path) < 15 or path[0][0]-r["_t"] > 300: continue   # the replay must start within 5 min of the sighting (used to start hours later after a cache refetch)
            info = {}; ret = sim(path, r.get("roundtrip_loss_pct") or 3.0, cfg, info)
            S = signals(r)
            if ret is None or S is None: continue
            if info.get("exit") in (None, "open") and path[-1][0]-path[0][0] < cfg["max_hold_hours"]*3600: continue   # a 20-minute mark-to-market is not a label
            day = (r["mint"], int(r["_t"]//86400))
            if per_day[day] >= MAX_ROWS_MINT_DAY: continue       # cap AFTER labelling: an established token (144 sightings/day) must not define the base rate
            per_day[day] += 1
            data.append({"t": r["_t"], "S": S, "ret": ret, "score": r["score"], "mint": r["mint"], "t_exit": info.get("t_exit", path[-1][0])})
        return sorted(data, key=lambda x: x["t"])
    def fit(s, data):
        base_n = len(data); wins = sum(d["ret"] > 0 for d in data)
        base = (wins+K*0.35)/(base_n+K)
        W = {}
        for k in {k for d in data for k in d["S"]}:
            on = [d for d in data if d["S"].get(k)]; off = [d for d in data if not d["S"].get(k)]
            p_on = (sum(d["ret"] > 0 for d in on)+K*base)/(len(on)+K); p_off = (sum(d["ret"] > 0 for d in off)+K*base)/(len(off)+K)
            W[k] = {"p_on": round(p_on, 3), "p_off": round(p_off, 3), "n_on": len(on), "n_off": len(off),
                    "ret_on_%": round(sum(d["ret"] for d in on)/len(on)*100, 2) if on else None}
        win = [d["ret"] for d in data if d["ret"] > 0]; los = [-d["ret"] for d in data if d["ret"] <= 0]
        aw = (sum(win)+5*0.15)/(len(win)+5); al = (sum(los)+5*0.08)/(len(los)+5)
        out = {"base": round(base, 3), "weights": W, "avg_win": round(aw, 4), "avg_loss": round(al, 4), "n": base_n}
        if np is not None and base_n >= 30 and 0 < wins < base_n:
            keys = sorted({k for d in data for k in d["S"]})
            X = np.array([[1.0 if d["S"].get(k) else 0.0 for k in keys] + [(d.get("score") or 0)/100.0] for d in data], float); y = np.array([1.0 if d["ret"] > 0 else 0.0 for d in data])
            out["logit"] = {**_logit_fit(X, y), "keys": keys}
        return out
    def learn(s, cfg):
        data = s.build_dataset(cfg)
        out = {"updated": dt.datetime.now().isoformat(timespec="seconds"), "n_labelled": len(data), "active": s.st.get("active", False), "active_votes": s.st.get("active_votes", 0)}
        choice = "beta"
        if len(data) >= MIN_TRAIN + MIN_TEST:
            cut = int(len(data)*0.7); t_cut = data[cut]["t"]
            tr = [d for d in data[:cut] if d.get("t_exit", d["t"]) <= t_cut]; te = data[cut:]   # PURGE: a train label may not use bars inside the test window
            m = s.fit(tr); tmp = Brain.__new__(Brain); tmp.ctx = {}
            floor = cfg.get("brain_min_score", 0); ev_min = float(cfg.get("brain_ev_min", EV_MIN))
            def policy(ch):   # the DEPLOYED policy: pessimistic net EV > floor AND score >= brain_min_score
                tmp.st = {**m, "model_choice": ch}
                return [d for d in te if tmp._ev(d["S"], d["score"], cfg) > ev_min and d["score"] >= floor]
            def brier(ch):
                tmp.st = {**m, "model_choice": ch}
                return sum((tmp._p(d["S"], d["score"])[0]-(1.0 if d["ret"] > 0 else 0.0))**2 for d in te)/len(te)
            cand = {}
            for ch in ("beta", "logit"):
                if ch == "logit" and not m.get("logit"): continue
                sel_ = policy(ch); cand[ch] = {"trades": len(sel_), "mints": len({d["mint"] for d in sel_}), "avg_ret_%": round(sum(d["ret"] for d in sel_)/len(sel_)*100, 2) if sel_ else None, "brier": round(brier(ch), 4)}
            L = cand.get("logit"); B = cand["beta"]   # the logistic model is deployed only if it beats Beta on BOTH the policy's OOS return and calibration
            if L and L["avg_ret_%"] is not None and L["trades"] >= 8 and (B["avg_ret_%"] is None or L["avg_ret_%"] > B["avg_ret_%"]) and L["brier"] <= B["brier"]: choice = "logit"
            sel = policy(choice)
            basel = [d for d in te if d["score"] >= cfg["min_score"]]
            ev_b = sum(d["ret"] for d in sel)/len(sel) if sel else None; ev_s = sum(d["ret"] for d in basel)/len(basel) if basel else None
            n_mints = len({d["mint"] for d in sel})
            tmp.st = {**m, "model_choice": choice}; bins = collections.defaultdict(lambda: [0, 0.0, 0])
            for d in te:
                pp = tmp._p(d["S"], d["score"])[0]; b_ = min(4, int(pp*5)); bins[b_][0] += 1; bins[b_][1] += pp; bins[b_][2] += 1 if d["ret"] > 0 else 0
            out["calibration"] = [{"bin": f"{b_*20}-{b_*20+20}%", "n": v[0], "p_avg": round(v[1]/v[0], 3), "win_rate": round(v[2]/v[0], 3)} for b_, v in sorted(bins.items())]
            out["oos"] = {"n_test": len(te), "brain_trades": len(sel), "brain_mints": n_mints, "brain_avg_ret_%": round(ev_b*100, 2) if ev_b is not None else None,
                          "baseline_trades": len(basel), "baseline_avg_ret_%": round(ev_s*100, 2) if ev_s is not None else None,
                          "all_avg_ret_%": round(sum(d["ret"] for d in te)/len(te)*100, 2), "purged_train_rows": cut-len(tr), "policy": f"ev>{ev_min:g} and score>={floor}",
                          "models": cand, "model_choice": choice}
            vote = bool(sel) and len(sel) >= 8 and n_mints >= MIN_MINTS and ev_b > 0 and (ev_s is None or ev_b > ev_s)
            streak = (max(0, s.st.get("active_votes", 0))+1) if vote else 0
            out["active_votes"] = streak
            out["active"] = vote and (bool(s.st.get("active", False)) or streak >= HYSTERESIS)   # fail-closed: ONE failing refit deactivates; HYSTERESIS consecutive passing refits activate
        else:
            out["oos"] = {"note": f"necesita {MIN_TRAIN+MIN_TEST} muestras etiquetadas (tiene {len(data)}) -> modo sombra"}; out["active"] = False; out["active_votes"] = 0
        full = s.fit(data) if data else {"base": 0.35, "weights": {}, "avg_win": 0.15, "avg_loss": 0.08, "n": 0}
        out.update(full); out["model_choice"] = choice if full.get("logit") else "beta"; s.st = out; _atomic_json(s.path, out, indent=1)
        log.info("[brain] learned n=%d active=%s model=%s oos=%s", len(data), out["active"], out["model_choice"], out["oos"]); return out
def _logit_fit(X, y, l2=1.0, iters=400, lr=0.2):
    """standardised L2 logistic regression by gradient descent (numpy only; no sklearn in production)"""
    mu = X.mean(0); sd = X.std(0); sd[sd < 1e-9] = 1.0; Z = (X-mu)/sd
    w = np.zeros(Z.shape[1]); b = math.log(max(y.mean(), 1e-3)/max(1-y.mean(), 1e-3)); n = len(y)
    for _ in range(iters):
        p = 1/(1+np.exp(-(Z@w+b))); g = Z.T@(p-y)/n + l2*w/n; w -= lr*g; b -= lr*float((p-y).mean())
    return {"mu": mu.tolist(), "sd": sd.tolist(), "w": [round(float(v), 5) for v in w], "b": round(float(b), 5), "n": int(n)}
if __name__ == "__main__":
    c = json.load(open("config.json"))["exchanges"]["solana"]; b = Brain(); o = b.learn(c)
    print(json.dumps({k: o[k] for k in ("n_labelled", "active", "oos", "base", "avg_win", "avg_loss")}, indent=1))
    print(sorted(((k, v["p_on"], v["n_on"], v["ret_on_%"]) for k, v in o["weights"].items()), key=lambda x: -x[1]))
