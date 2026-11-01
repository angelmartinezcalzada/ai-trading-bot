"""Tests for the 2026-10-31 brain/eval fixes: label replay follows the live exit rule, conservative bar order, aligned/resolved
labels only, purged walk-forward evaluated with the deployed policy, hysteresis on activation, atomic state writes."""
import json, os, time
import pytest
import eval_solana, brain

C31 = {"stop_pct": 0.10, "max_stop_pct": 0.15, "partial_tp_pct": 0.25, "partial_tp_frac": 0.5, "trail_activate_pct": 0.20, "trail_pct": 0.10,
       "runner_trail_pct": 0.12, "max_hold_hours": 3, "exit_mode": "volscale"}
CTR = dict(C31, exit_mode="trail", hard_stop_pct=6, trail_pct_tt=12)


def bar(t, o, h, l, c): return [t, o, h, l, c]


def test_sim_trail_mode_hard_stop_net_of_costs():
    info = {}
    # entry 1.0, cost 1% round trip: a low of 0.95 -> net = 0.95*0.99-1 = -5.95% (not yet), 0.94 -> -6.9% -> hard stop
    path = [bar(0, 1.0, 1.02, 0.95, 1.0), bar(60, 1.0, 1.01, 0.94, 0.96)]
    assert eval_solana.sim(path, 1.0, CTR, info) == pytest.approx(-0.06)
    assert info == {"exit": "hard_stop", "t_exit": 60}


def test_sim_trail_mode_trails_12pct_from_previous_best_and_stays_open_otherwise():
    info = {}
    path = [bar(0, 1.0, 1.0, 1.0, 1.0), bar(60, 1.0, 1.50, 1.0, 1.4), bar(120, 1.4, 1.45, 1.30, 1.32)]   # best 1.5 after bar 2; bar 3 low 1.30 <= 1.32 -> trail
    ret = eval_solana.sim(path, 1.0, CTR, info)
    assert info["exit"] == "trail" and info["t_exit"] == 120 and ret == pytest.approx(1.5*0.88*0.99-1)   # best is the PREVIOUS bar's high (1.5), exit on bar 3
    info = {}
    path = [bar(0, 1.0, 1.0, 1.0, 1.0), bar(60, 1.0, 1.05, 0.99, 1.03)]
    assert eval_solana.sim(path, 1.0, CTR, info) == pytest.approx(1.03*0.99-1) and info["exit"] == "open"


def test_sim_gap_bar_is_booked_at_its_close_not_at_the_stop():
    info = {}
    path = [bar(0, 1.0, 1.0, 1.0, 1.0), bar(60, 0.98, 0.99, 0.05, 0.06)]      # liquidity pulled: the bar closes 94% down
    assert eval_solana.sim(path, 1.0, CTR, info) == pytest.approx(0.06*0.99-1) and info["exit"] == "hard_stop"
    info = {}
    assert eval_solana.sim(path, 0.0, C31, info) == pytest.approx(-0.94) and info["exit"] == "stop"


def test_sim_v31_resolves_stop_before_tp_inside_one_candle():
    info = {}
    # one candle that both hits the +25% TP (high 1.30) and the -10% stop (low 0.85): the old code booked the TP first
    path = [bar(0, 1.0, 1.0, 1.0, 1.0), bar(60, 1.0, 1.30, 0.85, 1.0)]
    ret = eval_solana.sim(path, 0.0, C31, info)
    assert info["exit"] == "stop" and ret == pytest.approx(-0.10)


def test_sim_v31_partial_tp_then_breakeven_and_time_exit():
    info = {}
    path = [bar(0, 1.0, 1.0, 1.0, 1.0), bar(60, 1.0, 1.30, 1.0, 1.2), bar(120, 1.2, 1.25, 0.99, 1.0)]   # TP at +25% on bar 2, then low <= entry -> breakeven stop
    ret = eval_solana.sim(path, 0.0, C31, info)
    assert info["exit"] == "stop" and ret == pytest.approx(0.5*0.25)
    info = {}
    path = [bar(0, 1.0, 1.0, 1.0, 1.0), bar(3*3600+1, 1.0, 1.05, 0.98, 1.02)]
    assert eval_solana.sim(path, 0.0, C31, info) == pytest.approx(0.02) and info["exit"] == "time"


def _cand(ts, mint, pair, score=50, fail=(), liq=100000, parts=None):
    return {"ts": ts, "mint": mint, "pair": pair, "score": score, "fail": list(fail), "liq": liq, "price": 1.0,
            "parts": {"parts": parts or {"buy_press": 6}, "age_h": 2, "h1": 5}}


def test_build_dataset_alignment_cap_and_resolution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    now = time.time(); day0 = int(now//86400)*86400
    t0 = day0 + 2*3600 if now - (day0 + 2*3600) > 4*3600 else day0 - 86400 + 2*3600   # 02:00 UTC of a day that is >= 4 h old: the 12 sightings stay in one UTC day
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))
    rows = [_cand(iso(t0), "A", "pA"),                                   # aligned, resolved (stop) -> kept
            _cand(iso(t0), "B", "pB"),                                   # first candle 2 h after the sighting -> dropped (misaligned)
            _cand(iso(now-1500), "C", "pC"),                             # aligned but only 25 min of bars and no exit -> dropped (unresolved)
            _cand(iso(t0), "D", "pD", fail=["brain_ev<=0"]),             # model rejection stays in the tradable universe -> kept
            _cand(iso(t0), "E", "pE", fail=["mint_authority"])]          # hard veto -> dropped
    rows += [_cand(iso(t0+600*i), "A", "pA") for i in range(1, 12)]      # 12 sightings of A in one day -> capped at 6
    with open("candidates_solana.jsonl", "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    def bars(start, n, low=1.0): return [[start+60*i, 1.0, 1.01, low if i == n-1 else 1.0, 1.0] for i in range(n)]
    cache = {"pA": {"at": now, "bars": bars(t0, 200, low=0.5)}, "pB": {"at": now, "bars": bars(t0+7200, 100)},
             "pC": {"at": now, "bars": bars(now-1500, 25)}, "pD": {"at": now, "bars": bars(t0, 200, low=0.5)}}
    json.dump(cache, open("ohlcv_cache.json", "w"))
    monkeypatch.setattr(brain, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fetch expected")))
    monkeypatch.setattr(brain.time, "sleep", lambda s: None)
    b = brain.Brain.__new__(brain.Brain); b.st = {}; b.ctx = {}
    cfg = dict(C31, min_liquidity_usd=50000)
    data = brain.Brain.build_dataset(b, cfg, max_fetch=0)
    mints = [d["mint"] for d in data]
    assert "B" not in mints and "C" not in mints and "E" not in mints
    assert "D" in mints and mints.count("A") == 6
    assert all("t_exit" in d for d in data)


def test_learn_purges_overlap_uses_deployed_policy_and_hysteresis(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    n = 200
    data = []
    for i in range(n):   # signal 'good' on -> win; score alternates so the score floor matters
        on = i % 2 == 0
        data.append({"t": 1000*i, "t_exit": 1000*i + (5000 if i == 139 else 100), "S": {"good": on}, "ret": 0.05 if on else -0.05,
                     "score": 60 if i % 4 in (0, 1) else 40, "mint": f"m{i % 30}"})   # baseline (score>=45) holds losers the model filters out
    b = brain.Brain.__new__(brain.Brain); b.st = {"active": False, "active_votes": 0}; b.ctx = {}; b.path = str(tmp_path / "brain_state.json")
    monkeypatch.setattr(brain.Brain, "build_dataset", lambda s, cfg, max_fetch=40: data)
    cfg = dict(C31, min_liquidity_usd=50000, min_score=45, brain_min_score=45)
    out = brain.Brain.learn(b, cfg)
    assert out["oos"]["purged_train_rows"] == 1 and out["oos"]["policy"] == "ev>0.01 and score>=45"
    assert out["oos"]["brain_trades"] > 0 and out["oos"]["brain_mints"] >= 10 and out["oos"]["brain_avg_ret_%"] > 0
    assert out["active"] is False and out["active_votes"] == 1          # one positive refit is not enough
    for _ in range(2): out = brain.Brain.learn(b, cfg)
    assert out["active"] is True and out["active_votes"] == 3           # three consecutive agreeing refits flip it
    assert json.load(open(b.path))["active"] is True and not os.path.exists(b.path + ".tmp")
    # fail-closed: ONE failing refit (here: the score floor removes every row the model likes) deactivates immediately
    out = brain.Brain.learn(b, dict(cfg, brain_min_score=99))
    assert out["active"] is False and out["active_votes"] == 0 and out["oos"]["brain_trades"] == 0
    # ...and a shadow (not enough data) refit resets the streak
    monkeypatch.setattr(brain.Brain, "build_dataset", lambda s, cfg, max_fetch=40: data[:50])
    out = brain.Brain.learn(b, cfg)
    assert out["active"] is False and out["active_votes"] == 0


def test_brain_init_survives_corrupt_state(tmp_path):
    p = tmp_path / "brain_state.json"; p.write_text("{ not json")
    b = brain.Brain(str(p))
    assert b.st["active"] is False


def test_young_signal_true_for_brand_new_pool():
    r = {"parts": {"parts": {"buy_press": 1}, "age_h": 0.0}, "liq": 1000, "score": 10}
    assert brain.signals(r)["young"] is True
