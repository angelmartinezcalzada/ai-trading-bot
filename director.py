#!/usr/bin/env python3
"""Director: the memebot's own decision authority, inside the owner's limits (spec: docs/superpowers/specs/2026-10-31-director-brain-design.md).

Every hour (memebot's learn thread, or `python3 director.py --once`) it reads ONLY local files, measures the evidence and writes
director_state.json with keys that can only TIGHTEN the live config: which plays may trade, the effective score / EV floors,
the trade size that keeps fixed costs small, the hours and regimes with non-negative evidence, the exit profile (never a looser
stop) and a daily trade cap. memebot applies it through apply_director(cfg, state); test_director.py proves the invariant
"never looser than config" on random inputs. Missing / corrupt / stale state (> MAX_AGE_S) => the base config, logged.

Why fixed costs first: with ~3 $ trades the per-trade fixed cost (token-account rent 0.00204 SOL when the account cannot be
closed, plus two tx fees) is a few percent of the position, more than any edge the model has measured. The size policy and
the EV floor are built from that cost, and the memebot closes empty token accounts after every full exit (live_sol).

Governance: every change is appended to director_log.jsonl with its evidence; `--report` prints a Spanish summary for
DECISIONS.md; the dashboard shows the state. The director can NOT: relax a veto, raise a size above a cap, enable the pump
play with real money, or edit config.json. Shadow mode for the first SHADOW_S seconds after the first run: computed and logged,
not applied."""
import os, sys, json, time, math, csv, collections, datetime as dt, logging

log = logging.getLogger("director")
STATE_FILE, LOG_FILE = "director_state.json", "director_log.jsonl"
MAX_AGE_S, SHADOW_S = 3 * 3600, 24 * 3600
PLAYS = ("scanner", "insider_elite", "pump")
EV_MIN_BASE = 0.01            # brain.EV_MIN (the deployed policy's floor); the director can only raise it
FIXED_SHARE_TARGET = 0.005    # size the fixed cost down to <= 0.5 % of the position
FIXED_SHARE_MAX = 0.02        # above 2 % of the position in fixed cost the director refuses to trade (target_usd = 0)
PRIOR_N = 10                  # pseudo-trades for the shrinkage of a play's statistics
MIN_N_OFF, MIN_N_ON = 15, 20  # evidence needed to switch a play off / on
HOUR_MIN_N, DATA_MIN_ROWS = 10, 100
GRID_STOPS, GRID_TRAILS, GRID_MIN_TEST = (3.0, 4.0, 5.0, 6.0), (8.0, 10.0, 12.0), 40
ATA_RENT_SOL = 0.00203928
# risk keys the director may touch, and the direction that counts as "tighter"
TIGHTER = {"min_score": "max", "brain_min_score": "max", "brain_ev_min": "max", "size_pct": "min", "live_target_max_usd": "min",
           "live_target_min_usd": "min", "hard_stop_pct": "min", "trail_pct_tt": "min", "max_positions": "min", "pump_paper": "and", "pump_play": "and"}


def _atomic_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=1, default=str)
    os.replace(tmp, path)


# ---------------------------------------------------------------- evidence from the ledgers
def classify_play(reason):
    r = (reason or "").upper()
    if "PUMP-PLAY" in r or "PUMP_EXIT" in r or "PUMP_PAPER" in r: return "pump"
    if "INSIDER" in r: return "insider_elite"
    return "scanner"


def _iso(s):
    try: return time.mktime(time.strptime(str(s)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S"))
    except Exception: return None


def ledger_rows(path, now, days):
    """SELL rows of a trades CSV (memebot format) in the last `days`, each tagged with the play of its BUY (matched by symbol)."""
    if not os.path.exists(path): return []
    out, play_of = [], {}
    try: rows = list(csv.DictReader(open(path, encoding="utf-8", errors="replace")))
    except Exception: return []
    for r in rows:
        t = _iso(r.get("time"));
        if t is None: continue
        sym, side, reason = (r.get("symbol") or "").strip(), (r.get("side") or "").strip(), r.get("reason") or ""
        if side == "BUY": play_of[sym] = classify_play(reason); continue
        if side != "SELL" or now - t > days * 86400: continue
        try: pnl, px, qty = float(r.get("pnl") or 0), float(r.get("price") or 0), float(r.get("qty") or 0)
        except ValueError: continue
        size = px * qty
        play = "pump" if classify_play(reason) == "pump" else play_of.get(sym, classify_play(reason))
        out.append({"t": t, "sym": sym, "pnl": pnl, "pct": (pnl / size) if size > 0 else 0.0, "play": play, "hour": dt.datetime.fromtimestamp(t).hour})
    return out


def play_stats(rows, weight=1.0):
    """n, wins, pf (shrunk), expectancy in % of position (shrunk toward 0) for a list of SELL rows."""
    n = len(rows)
    if not n: return {"n": 0, "n_eff": 0.0, "wins": 0, "pf": None, "pf_raw": None, "exp_pct": None, "exp_pct_raw": None, "net": 0.0}
    gw = sum(r["pnl"] for r in rows if r["pnl"] > 0); gl = -sum(r["pnl"] for r in rows if r["pnl"] < 0)
    c = (gw + gl) / n * PRIOR_N / 2          # PRIOR_N pseudo-trades of average size, half winners half losers
    pf = (gw + c) / (gl + c) if (gl + c) > 0 else None
    exp = sum(r["pct"] for r in rows) / n
    return {"n": n, "n_eff": round(n * weight, 1), "wins": sum(1 for r in rows if r["pnl"] > 0), "pf": round(pf, 3) if pf is not None else None,
            "pf_raw": round(gw / gl, 3) if gl > 0 else None, "exp_pct": round(exp * 100 * n / (n + PRIOR_N), 3), "exp_pct_raw": round(exp * 100, 3), "net": round(gw - gl, 4)}


def plays_evidence(root, now, cfg, days=14):
    """per play: real stats (weight 1) + paper stats (weight 0.5) + combined; the decision uses the combined n_eff."""
    real = ledger_rows(os.path.join(root, "trades_solana_live.csv"), now, days)
    paper = ledger_rows(os.path.join(root, "trades_solana_paper.csv"), now, days)
    ev = {}
    for p in PLAYS:
        R = [r for r in real if r["play"] == p]; P = [r for r in paper if r["play"] == p]
        sr, sp = play_stats(R, 1.0), play_stats(P, 0.5)
        comb = play_stats(R + P)
        n_eff = sr["n_eff"] + sp["n_eff"]
        # combined expectancy weights real rows 1 and paper rows 0.5
        wsum = sum(r["pct"] for r in R) + 0.5 * sum(r["pct"] for r in P)
        exp_c = (wsum / n_eff) if n_eff else None
        ev[p] = {"real": sr, "paper": sp, "n_eff": round(n_eff, 1), "pf": comb["pf"], "exp_pct": round(exp_c * 100 * n_eff / (n_eff + PRIOR_N), 3) if exp_c is not None else None}
    return ev


# ---------------------------------------------------------------- the decisions (pure functions)
def fixed_cost_usd(sol_usd, tx_fee_sol=0.00001, rent_lost_prob=0.1):
    """expected fixed USD cost of one round trip: two tx fees + the rent of the token account weighted by the probability that
    the account cannot be closed afterwards (token dead with dust / Token-2022 oddity). rent_lost_prob comes from the ATA log."""
    return (2 * tx_fee_sol + rent_lost_prob * ATA_RENT_SOL) * max(sol_usd, 0.0)


def rent_lost_prob(root, default=0.1):
    """share of attempted token-account closes that failed (research/ata_close.jsonl + memebot ata log), shrunk to the default."""
    p = os.path.join(root, "research", "ata_close.jsonl"); n = f = 0
    if os.path.exists(p):
        for l in open(p, encoding="utf-8", errors="replace"):
            try: r = json.loads(l)
            except Exception: continue
            n += int(r.get("closed") or 0) + len(r.get("failed") or []); f += len(r.get("failed") or [])
    return round((f + default * 10) / (n + 10), 4)


def size_policy(cfg, equity, fixed_usd):
    """largest trade the caps allow, and whether the fixed cost makes it worth trading at all."""
    caps = {"max_position_pct": equity * cfg.get("max_position_pct", 0.08), "max_gap_loss_pct": equity * cfg.get("max_gap_loss_pct", 0.1),
            "max_trade_loss/max_stop": equity * cfg.get("max_trade_loss_pct", 0.015) / max(1e-9, cfg.get("max_stop_pct", 0.15)),
            "live_target_max_usd": float(cfg.get("live_target_max_usd", 5) or 5), "size_pct": equity * cfg.get("size_pct", 8) / 100}
    target = max(0.0, min(caps.values()))
    share = (fixed_usd / target) if target > 0 else None
    out = {"target_usd": round(target, 2), "caps": {k: round(v, 2) for k, v in caps.items()}, "binding": min(caps, key=caps.get) if caps else None,
           "fixed_usd": round(fixed_usd, 4), "fixed_share": round(share, 4) if share is not None else None, "max_frac": round(target / equity, 4) if equity > 0 else 0.0,
           "min_size_for_target_share": round(fixed_usd / FIXED_SHARE_TARGET, 2)}
    if share is None or share > FIXED_SHARE_MAX:
        out.update(target_usd=0.0, max_frac=0.0, why=f"coste fijo {fixed_usd:.3f} $ = {100*(share or 0):.1f} % de la posición máxima ({target:.2f} $): no merece operar")
    else: out["why"] = f"posición máxima {target:.2f} $ (tope: {out['binding']}); coste fijo {100*share:.2f} % de la posición"
    return out


def ev_floor(size_pol):
    """EV floor = max(base floor, 3 x fixed-cost share): the 18:27 rule (EV >= 3 x real round-trip) extended to fixed costs."""
    share = size_pol.get("fixed_share")
    return round(max(EV_MIN_BASE, 3 * share) if share is not None else EV_MIN_BASE, 4)


def plays_decision(ev, prev, cost_pct, cfg):
    """on/off per play from shrunk PF and expectancy vs the cost; pump never leaves paper by itself."""
    out, why = {}, {}
    for p in ("scanner", "insider_elite"):
        e = ev.get(p) or {}; n, pf, ex = e.get("n_eff", 0), e.get("pf"), e.get("exp_pct")
        cur = (prev or {}).get(p, "on")
        if n >= MIN_N_OFF and pf is not None and (pf < 1.0 or (ex is not None and ex <= cost_pct)): out[p] = "off"; why[p] = f"n_eff={n} PF={pf} exp={ex}% <= coste {cost_pct}%"
        elif n >= MIN_N_ON and pf is not None and pf > 1.2 and ex is not None and ex > cost_pct: out[p] = "on"; why[p] = f"n_eff={n} PF={pf} exp={ex}% > coste {cost_pct}%"
        else: out[p] = cur; why[p] = f"sin evidencia suficiente (n_eff={n}); se mantiene {cur}"
    out["pump"] = "paper" if cfg.get("pump_paper", False) or cfg.get("pump_play", False) else "off"
    e = ev.get("pump") or {}
    if e.get("n_eff", 0) >= MIN_N_OFF and e.get("pf") is not None and e["pf"] < 1.0: out["pump"] = "off"; why["pump"] = f"n_eff={e['n_eff']} PF={e['pf']}: pump apagado también en papel"
    else: why["pump"] = "pump nunca pasa a real por decisión del director (regla 17:37); " + ("en papel" if out["pump"] == "paper" else "apagado")
    return out, why


def windows_from_data(data, min_n=HOUR_MIN_N, min_rows=DATA_MIN_ROWS):
    """hours (local) whose labelled replay expectancy is >= 0 with >= min_n rows; all 24 when the dataset is too small."""
    if not data or len(data) < min_rows: return list(range(24)), {"note": f"dataset {len(data or [])} < {min_rows} filas: sin restricción horaria"}
    by = collections.defaultdict(list)
    for d in data: by[dt.datetime.fromtimestamp(d["t"]).hour].append(d["ret"])
    hours, table = [], {}
    for hr in range(24):
        v = by.get(hr, []); m = sum(v) / len(v) if v else None
        table[hr] = {"n": len(v), "avg_%": round(m * 100, 2) if m is not None else None}
        if len(v) < min_n or m >= 0: hours.append(hr)      # unknown hours stay open: the model gate still applies
    return hours, table


def exit_grid(paths, cfg, sim):
    """paths: [(bars, rt_pct)] (1m OHLCV from the sighting, round-trip cost). Replays every profile <= config (never looser) with
    `sim` (eval_solana.sim) and picks the best OOS mean net return on the newest 30 % if it beats config by > 0.2 pp."""
    hs0, tr0 = float(cfg.get("hard_stop_pct", 6)), float(cfg.get("trail_pct_tt", 12))
    grid = [(h, t) for h in GRID_STOPS if h <= hs0 for t in GRID_TRAILS if t <= tr0]
    if (hs0, tr0) not in grid: grid.append((hs0, tr0))
    n = len(paths); cut = int(n * 0.7); test = paths[cut:]
    if len(test) < GRID_MIN_TEST: return {"hard_stop_pct": hs0, "trail_pct": tr0, "why": f"solo {len(test)} trayectorias de test (< {GRID_MIN_TEST}): perfil de config"}, {}
    res = {}
    for h, t in grid:
        c = dict(cfg, exit_mode="trail", hard_stop_pct=h, trail_pct_tt=t)
        rets = [r for r in (sim(b, rt, c) for b, rt in test) if r is not None]
        res[f"{h:g}/{t:g}"] = {"n": len(rets), "avg_%": round(sum(rets) / len(rets) * 100, 3) if rets else None}
    base = res.get(f"{hs0:g}/{tr0:g}", {}).get("avg_%")
    best = max((k for k in res if res[k]["avg_%"] is not None), key=lambda k: res[k]["avg_%"], default=None)
    if best and base is not None and res[best]["avg_%"] > base + 0.2:
        h, t = (float(x) for x in best.split("/"))
        return {"hard_stop_pct": h, "trail_pct": t, "why": f"replay OOS {res[best]['avg_%']}% vs config {base}% ({len(test)} trayectorias)"}, res
    return {"hard_stop_pct": hs0, "trail_pct": tr0, "why": f"ningún perfil más cerrado supera a config por > 0,2 pp (config {base}%)"}, res


def max_trades_day(cfg, equity, target_usd, avg_loss_pct=None):
    """daily risk budget / expected loss of one losing trade at the hard stop."""
    budget = equity * cfg.get("daily_max_drawdown_pct", 0.05)
    loss = target_usd * max(float(cfg.get("hard_stop_pct", 6)) / 100, (avg_loss_pct or 0) / 100)
    if target_usd <= 0 or loss <= 0: return 0
    return int(max(0, min(budget / loss, cfg.get("max_positions", 8) * 3)))


# ---------------------------------------------------------------- apply (the only path into memebot)
def apply_director(cfg, state):
    """effective config = base config tightened by the director state; returns (cfg2, changes). Never loosens anything."""
    c = dict(cfg); changes = []
    if not state or state.get("shadow"): return c, changes
    def tighten(k, v):
        if v is None or k not in TIGHTER: return
        old = c.get(k); mode = TIGHTER[k]
        if mode == "and": new = bool(old) and bool(v)
        elif old is None: new = v
        elif mode == "max": new = max(old, v)
        else: new = min(old, v)
        if new != old: c[k] = new; changes.append((k, old, new))
    tighten("min_score", state.get("min_score_eff")); tighten("brain_ev_min", state.get("ev_min_eff"))
    sp = state.get("size_policy") or {}
    if sp.get("target_usd") is not None:
        tighten("live_target_max_usd", sp["target_usd"]); tighten("live_target_min_usd", sp["target_usd"])
        if sp.get("max_frac") is not None: tighten("size_pct", round(sp["max_frac"] * 100, 3))
    ep = state.get("exit_profile") or {}
    tighten("hard_stop_pct", ep.get("hard_stop_pct")); tighten("trail_pct_tt", ep.get("trail_pct"))
    pl = state.get("plays") or {}
    if pl.get("pump") == "off": tighten("pump_paper", False); tighten("pump_play", False)
    if pl.get("pump") is not None: tighten("pump_play", False)      # pump never goes live through the director
    c["director_plays"] = {k: v for k, v in pl.items()}
    c["director_windows"] = sorted(int(h) for h in (state.get("windows") or range(24)) if 0 <= int(h) < 24)
    c["director_max_trades_day"] = state.get("max_trades_day")
    c["director_regime_gate"] = state.get("regime_gate") or {}
    c["director_ts"] = state.get("ts")
    return c, changes


def load_state(root, now=None, max_age=MAX_AGE_S):
    """(state or None, reason). None when the file is missing, corrupt or older than max_age: the base config then rules."""
    now = now or time.time(); p = os.path.join(root, STATE_FILE)
    if not os.path.exists(p): return None, "sin director_state.json"
    try: st = json.load(open(p))
    except Exception as e: return None, f"director_state.json ilegible: {str(e)[:80]}"
    if not isinstance(st, dict) or not isinstance(st.get("ts"), (int, float)): return None, "director_state.json sin ts"
    if now - st["ts"] > max_age: return None, f"director_state.json obsoleto ({(now - st['ts'])/3600:.1f} h)"
    return st, "ok"


def entry_allowed(c, now_hour, n_trades_today, play="scanner"):
    """memebot gate: play enabled, hour in the window, daily cap not reached. Fail-closed on a malformed state (allowed=True only
    when the director keys are absent, i.e. base config)."""
    pl = c.get("director_plays")
    if pl is not None and pl.get(play, "on") not in ("on", "paper" if play == "pump" else "on"): return False, f"director: jugada {play} apagada"
    w = c.get("director_windows")
    if w is not None and now_hour not in w: return False, f"director: hora {now_hour} fuera de ventana"
    mx = c.get("director_max_trades_day")
    if mx is not None and n_trades_today >= mx: return False, f"director: tope diario {mx} operaciones alcanzado"
    return True, "ok"


# ---------------------------------------------------------------- the hourly computation
def compute(root, cfg, equity, sol_usd, now=None, data=None, paths=None, sim=None, prev=None, write=True):
    """Build the director state from local evidence. `data` = brain.build_dataset rows (t, ret, score, S), `paths` = [(bars, rt)]
    for the exit grid; both optional (None => that decision falls back to config). Writes STATE_FILE and LOG_FILE unless write=False."""
    now = now or time.time(); cfg = dict(cfg); prev = prev if prev is not None else (load_state(root, now, max_age=10 * 86400)[0] or {})
    first_run = prev.get("first_run") or now
    rlp = rent_lost_prob(root)
    fixed = fixed_cost_usd(sol_usd, rent_lost_prob=rlp)
    sp = size_policy(cfg, equity, fixed)
    evf = ev_floor(sp)
    ev = plays_evidence(root, now, cfg)
    cost_pct = round(100 * (sp.get("fixed_share") or 0) + 0.5, 3)      # fixed share + ~0.5 % typical round trip
    plays, why_p = plays_decision(ev, prev.get("plays"), cost_pct, cfg)
    # score floor: best score bucket by labelled expectancy, never below config
    msf, why_s = cfg.get("min_score", 45), "config"
    if data and len(data) >= DATA_MIN_ROWS:
        buckets = collections.defaultdict(list)
        for d in data: buckets[int((d.get("score") or 0) // 10 * 10)].append(d["ret"])
        cands = [(b, sum(v) / len(v)) for b, v in buckets.items() if len(v) >= HOUR_MIN_N and b >= cfg.get("min_score", 45)]
        if cands:
            bb, bm = max(cands, key=lambda x: x[1]); base_m = sum(r for v in buckets.values() for r in v) / len(data)
            if bm > base_m + 0.005 and bb > cfg.get("min_score", 45): msf, why_s = bb, f"bucket {bb}+ media {bm*100:.2f}% vs global {base_m*100:.2f}%"
    windows, wtable = windows_from_data(data)
    ep, grid = (exit_grid(paths, cfg, sim) if (paths and sim) else ({"hard_stop_pct": float(cfg.get("hard_stop_pct", 6)), "trail_pct": float(cfg.get("trail_pct_tt", 12)), "why": "sin trayectorias: perfil de config"}, {}))
    al = (ev.get("scanner") or {}).get("real", {}).get("exp_pct_raw")
    mtd = max_trades_day(cfg, equity, sp["target_usd"], abs(al) if al is not None and al < 0 else None)
    st = {"ts": now, "first_run": first_run, "shadow": (now - first_run) < SHADOW_S, "version": 1,
          "plays": plays, "min_score_eff": msf, "ev_min_eff": evf, "size_policy": sp, "windows": windows, "regime_gate": {},
          "exit_profile": ep, "max_trades_day": mtd,
          "evidence": {"equity": round(equity, 2), "sol_usd": round(sol_usd, 2), "fixed_cost_usd": round(fixed, 4), "rent_lost_prob": rlp, "cost_pct": cost_pct,
                       "plays": ev, "plays_why": why_p, "score_floor_why": why_s, "hours": wtable, "exit_grid": grid, "dataset_rows": len(data or [])}}
    if write:
        changes = _diff(prev, st)
        _atomic_json(os.path.join(root, STATE_FILE), st)
        with open(os.path.join(root, LOG_FILE), "a") as f:
            f.write(json.dumps({"t": now, "shadow": st["shadow"], "changes": changes, "summary": summary_line(st)}, default=str) + "\n")
        log.info("[director] %s%s", "SHADOW " if st["shadow"] else "", summary_line(st))
    return st


def _diff(prev, st):
    out = []
    for k in ("plays", "min_score_eff", "ev_min_eff", "windows", "exit_profile", "max_trades_day"):
        a, b = prev.get(k), st.get(k)
        if k == "exit_profile": a, b = ({x: (a or {}).get(x) for x in ("hard_stop_pct", "trail_pct")}, {x: (b or {}).get(x) for x in ("hard_stop_pct", "trail_pct")})
        if a != b: out.append({"key": k, "before": a, "after": b})
    a, b = (prev.get("size_policy") or {}).get("target_usd"), (st.get("size_policy") or {}).get("target_usd")
    if a != b: out.append({"key": "size_policy.target_usd", "before": a, "after": b})
    return out


def summary_line(st):
    sp = st.get("size_policy") or {}; ep = st.get("exit_profile") or {}
    return (f"jugadas={st.get('plays')} score>={st.get('min_score_eff')} EV>={100*(st.get('ev_min_eff') or 0):.2f}% tamaño={sp.get('target_usd')}$ "
            f"(coste fijo {100*(sp.get('fixed_share') or 0):.2f}%) ventana={len(st.get('windows') or [])}h stop={ep.get('hard_stop_pct')}%/trail={ep.get('trail_pct')}% "
            f"max/día={st.get('max_trades_day')}")


def report(st):
    """Spanish summary for DECISIONS.md"""
    if not st: return "Director: sin estado."
    e = st.get("evidence") or {}; sp = st.get("size_policy") or {}; ep = st.get("exit_profile") or {}
    L = [f"## Director — {dt.datetime.fromtimestamp(st['ts']).isoformat(timespec='minutes')} ({'SOMBRA: calculado, no aplicado' if st.get('shadow') else 'APLICADO'})",
         f"- Capital {e.get('equity')} $ · SOL {e.get('sol_usd')} $ · coste fijo por operación {e.get('fixed_cost_usd')} $ (prob. rent perdido {e.get('rent_lost_prob')}) → coste total estimado {e.get('cost_pct')} % de la posición.",
         f"- Tamaño: {sp.get('why')}. EV mínimo efectivo {100*(st.get('ev_min_eff') or 0):.2f} %. Score mínimo efectivo {st.get('min_score_eff')} ({e.get('score_floor_why')}).",
         f"- Jugadas: " + "; ".join(f"{k}={v} ({(e.get('plays_why') or {}).get(k, '')})" for k, v in (st.get("plays") or {}).items()),
         f"- Ventana horaria: {len(st.get('windows') or [])}/24 horas permitidas" + (f" (dataset {e.get('dataset_rows')} filas)" if e.get("dataset_rows") else " (sin dataset: todas)"),
         f"- Perfil de salida: stop −{ep.get('hard_stop_pct')} % / trail {ep.get('trail_pct')} % ({ep.get('why')}). Tope diario: {st.get('max_trades_day')} operaciones."]
    for p, v in (e.get("plays") or {}).items():
        r, pp = v.get("real") or {}, v.get("paper") or {}
        L.append(f"  - {p}: real n={r.get('n')} PF={r.get('pf_raw')} exp={r.get('exp_pct_raw')} % · papel n={pp.get('n')} PF={pp.get('pf_raw')} exp={pp.get('exp_pct_raw')} %")
    return "\n".join(L)


def main(argv):
    root = os.path.dirname(os.path.abspath(__file__)); os.chdir(root)
    cfg = json.load(open("config.json"))["exchanges"]["solana"]
    if "--report" in argv: print(report(load_state(root, max_age=10 * 86400)[0])); return 0
    equity = sol_usd = None
    try: st = json.load(open("status_solana.json")); equity = float(st.get("equity") or 0); sol_usd = float((st.get("regime") or {}).get("sol_usd") or 0)
    except Exception: pass
    if not equity: equity = float(cfg.get("starting_equity", 48))
    if not sol_usd: sol_usd = 100.0
    data = None
    if "--no-data" not in argv:
        try:
            import brain; b = brain.Brain(); data = b.build_dataset(cfg, max_fetch=0)
        except Exception as e: print("dataset no disponible:", str(e)[:120], file=sys.stderr)
    st = compute(root, cfg, equity, sol_usd, data=data, write="--dry-run" not in argv)
    print(report(st)); return 0


if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
