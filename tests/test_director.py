"""director.py: the invariant 'never looser than config' on random inputs, every decision function on synthetic evidence,
and an end-to-end compute() on a temporary bot folder. Offline, no wallet, no network."""
import json, os, random, time, csv
import pytest
import director as D
from eval_solana import sim

BASE = {"min_score": 45, "brain_min_score": 45, "size_pct": 8, "live_target_max_usd": 5, "live_target_min_usd": 3, "hard_stop_pct": 6, "trail_pct_tt": 12,
        "max_positions": 8, "pump_paper": True, "pump_play": False, "max_position_pct": 0.1, "max_gap_loss_pct": 0.1, "max_trade_loss_pct": 0.015,
        "max_stop_pct": 0.15, "daily_max_drawdown_pct": 0.05, "exit_mode": "trail"}


def rand_state(rng):
    return {"ts": time.time(), "shadow": False,
            "plays": {"scanner": rng.choice(["on", "off"]), "insider_elite": rng.choice(["on", "off"]), "pump": rng.choice(["paper", "off"])},
            "min_score_eff": rng.choice([None, 30, 45, 55, 70]), "ev_min_eff": rng.choice([None, 0.005, 0.01, 0.03, 0.08]),
            "size_policy": {"target_usd": rng.choice([None, 0.0, 1.5, 4.8, 12.0]), "max_frac": rng.choice([None, 0.0, 0.03, 0.1, 0.25])},
            "exit_profile": {"hard_stop_pct": rng.choice([None, 3.0, 6.0, 9.0]), "trail_pct": rng.choice([None, 8.0, 12.0, 20.0])},
            "windows": rng.sample(range(24), rng.randint(0, 24)), "max_trades_day": rng.choice([None, 0, 3, 50])}


def test_apply_never_loosens_any_risk_key():
    rng = random.Random(7)
    for _ in range(500):
        cfg = dict(BASE, min_score=rng.choice([30, 45, 60]), size_pct=rng.choice([4, 8, 12]), hard_stop_pct=rng.choice([4, 6, 8]),
                   trail_pct_tt=rng.choice([8, 12, 15]), pump_play=rng.choice([True, False]), pump_paper=rng.choice([True, False]), brain_ev_min=rng.choice([0.01, 0.02]))
        st = rand_state(rng); c2, changes = D.apply_director(cfg, st)
        for k, mode in D.TIGHTER.items():
            if k not in cfg: continue
            if mode == "max": assert c2[k] >= cfg[k], (k, cfg[k], c2[k])
            elif mode == "min": assert c2[k] <= cfg[k], (k, cfg[k], c2[k])
            else: assert (not c2[k]) or cfg[k], (k, cfg[k], c2[k])
        assert c2["pump_play"] is False                                    # the director never puts the pump play live
        assert set(c2["director_windows"]) <= set(range(24)) and set(c2["director_plays"]) >= {"scanner", "insider_elite", "pump"}
        for k, old, new in changes: assert k in D.TIGHTER


def test_apply_is_identity_without_state_or_in_shadow():
    c, ch = D.apply_director(BASE, None); assert c == BASE and ch == []
    c, ch = D.apply_director(BASE, {"ts": time.time(), "shadow": True, "min_score_eff": 90}); assert c["min_score"] == 45 and ch == []


def test_size_policy_and_ev_floor_from_fixed_costs():
    sp = D.size_policy(BASE, 48.0, D.fixed_cost_usd(96.0, rent_lost_prob=0.1))
    assert sp["target_usd"] == pytest.approx(3.84, abs=0.01) and sp["binding"] == "size_pct"      # 8 % of 48 $ binds before the 10 % caps
    assert D.size_policy(dict(BASE, size_pct=12), 48.0, 0.02)["target_usd"] == pytest.approx(4.8, abs=0.01)
    assert 0 < sp["fixed_share"] < D.FIXED_SHARE_MAX and D.ev_floor(sp) == pytest.approx(max(D.EV_MIN_BASE, 3 * sp["fixed_share"]), abs=1e-6)
    tiny = D.size_policy(BASE, 2.0, 0.05)                                  # 0.2 $ max trade with 5 cents fixed cost: do not trade
    assert tiny["target_usd"] == 0.0 and tiny["max_frac"] == 0.0 and "no merece" in tiny["why"]
    assert D.max_trades_day(BASE, 48.0, 3.84) == int(0.05 * 48 / (3.84 * 0.06)) and D.max_trades_day(BASE, 48.0, 0.0) == 0


def rows(n, pnl_fn, play="scanner", t0=None):
    t0 = t0 or time.time() - 3600
    return [{"t": t0 + i, "sym": f"S{i}", "pnl": pnl_fn(i), "pct": pnl_fn(i) / 3.0, "play": play, "hour": 12} for i in range(n)]


def test_play_stats_shrinks_small_samples_toward_nothing():
    s3 = D.play_stats(rows(3, lambda i: 0.3)); s30 = D.play_stats(rows(30, lambda i: 0.3))
    assert s3["exp_pct_raw"] == s30["exp_pct_raw"] == pytest.approx(10.0) and s3["exp_pct"] < s30["exp_pct"] and s3["pf"] is not None
    assert D.play_stats([])["n"] == 0


def test_plays_decision_switches_on_evidence_and_never_puts_pump_live():
    ev = {"scanner": {"n_eff": 25, "pf": 0.6, "exp_pct": -2.0}, "insider_elite": {"n_eff": 25, "pf": 1.6, "exp_pct": 3.0}, "pump": {"n_eff": 60, "pf": 0.4, "exp_pct": -1.8}}
    pl, why = D.plays_decision(ev, {"scanner": "on", "insider_elite": "off"}, 1.0, dict(BASE, pump_play=True))
    assert {k: pl[k] for k in ("scanner", "insider_elite", "pump")} == {"scanner": "off", "insider_elite": "on", "pump": "off"} and "PF" in why["scanner"] and pl["trend"] == "paper"
    pl, _ = D.plays_decision({"scanner": {"n_eff": 5, "pf": 0.2, "exp_pct": -9}}, {"scanner": "on"}, 1.0, BASE)
    assert pl["scanner"] == "on" and pl["pump"] == "paper"                 # too little evidence: unchanged; pump stays in paper
    pl, _ = D.plays_decision({"scanner": {"n_eff": 25, "pf": 1.5, "exp_pct": 0.9}}, {"scanner": "on"}, 1.0, BASE)
    assert pl["scanner"] == "off"                                            # positive PF but expectancy below the cost: off


def test_windows_from_data_keeps_unknown_hours_open_and_closes_negative_ones():
    data = []
    for hr in range(24):
        for i in range(12): data.append({"t": time.mktime((2026, 10, 31, hr, 10 + i, 0, 0, 0, -1)), "ret": (-0.02 if hr in (3, 4) else 0.01), "score": 50})
    hours, table = D.windows_from_data(data)
    assert 3 not in hours and 4 not in hours and len(hours) == 22 and table[3]["n"] == 12
    assert D.windows_from_data(data[:50])[0] == list(range(24))              # too small: unrestricted


def paths(n, seed):
    rng = random.Random(seed); out = []
    for k in range(n):
        px, bars, drift = 1.0, [], rng.choice([-0.0006, 0.0, 0.0008])
        for i in range(240):
            o = px; c = max(0.2, o * (1 + drift + rng.gauss(0, 0.01))); h, l = max(o, c) * (1 + abs(rng.gauss(0, 0.004))), min(o, c) * (1 - abs(rng.gauss(0, 0.004)))
            bars.append((1_700_000_000 + k * 86400 + i * 60, o, h, l, c)); px = c
        out.append((bars, 1.0))
    return out


def test_exit_grid_never_picks_a_looser_profile_and_needs_enough_test_paths():
    cfg = dict(BASE, max_hold_hours=3)
    ep, grid = D.exit_grid(paths(30, 1), cfg, sim)
    assert (ep["hard_stop_pct"], ep["trail_pct"]) == (6.0, 12.0) and grid == {}            # < 40 test paths -> config profile
    ep, grid = D.exit_grid(paths(200, 2), cfg, sim)
    assert ep["hard_stop_pct"] <= 6.0 and ep["trail_pct"] <= 12.0 and all(k.split("/")[0] in ("3", "4", "5", "6") for k in grid)
    assert all(float(k.split("/")[0]) <= 6 and float(k.split("/")[1]) <= 12 for k in grid)


def test_entry_allowed_gates():
    c = dict(BASE, director_plays={"scanner": "on", "insider_elite": "off", "pump": "paper"}, director_windows=[10, 11], director_max_trades_day=2)
    assert D.entry_allowed(c, 10, 0)[0] and not D.entry_allowed(c, 12, 0)[0] and not D.entry_allowed(c, 10, 2)[0]
    assert not D.entry_allowed(c, 10, 0, play="insider_elite")[0] and D.entry_allowed(c, 10, 0, play="pump")[0]
    assert D.entry_allowed(BASE, 3, 99)[0]                                      # no director keys: base config rules


def test_load_state_rejects_missing_corrupt_and_stale(tmp_path):
    root = str(tmp_path); assert D.load_state(root)[0] is None
    open(os.path.join(root, D.STATE_FILE), "w").write("{broken"); assert D.load_state(root)[0] is None
    json.dump({"ts": time.time() - 5 * 3600}, open(os.path.join(root, D.STATE_FILE), "w")); assert "obsoleto" in D.load_state(root)[1]
    json.dump({"ts": time.time() - 60, "plays": {}}, open(os.path.join(root, D.STATE_FILE), "w")); assert D.load_state(root)[1] == "ok"


def write_ledger(path, rows_):
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow("time,exchange,symbol,side,price,qty,fee,pnl,reason,equity".split(","))
        for r in rows_: w.writerow(r)


def test_compute_end_to_end_writes_state_and_log(tmp_path):
    root = str(tmp_path); now = time.time(); ts = lambda s: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - s))
    real = []
    for i in range(30):   # 30 pump trades, all losers -> pump off even in paper; 2 scanner trades (too few to decide)
        real += [[ts(7200 - i * 60), "solana", f"P{i}", "BUY", "0.01", "300", "0.001", "0", "meme score=10 PUMP-PLAY liq=1 REAL tx=a", "48"],
                 [ts(7000 - i * 60), "solana", f"P{i}", "SELL", "0.0095", "300", "0.001", "-0.15", "meme:pump_exit:time REAL tx=b", "48"]]
    real += [[ts(500), "solana", "SC", "BUY", "1", "3", "0.001", "0", "meme score=60 liq=100000 REAL tx=c", "48"], [ts(400), "solana", "SC", "SELL", "1.1", "3", "0.001", "0.3", "meme:trail REAL tx=d", "48"]]
    write_ledger(os.path.join(root, "trades_solana_live.csv"), real)
    st = D.compute(root, BASE, 48.0, 96.0, now=now)
    assert os.path.exists(os.path.join(root, D.STATE_FILE)) and os.path.exists(os.path.join(root, D.LOG_FILE))
    assert st["shadow"] is True and st["plays"]["pump"] == "off" and st["plays"]["scanner"] == "on"
    assert st["evidence"]["plays"]["pump"]["real"]["n"] == 30 and st["evidence"]["plays"]["scanner"]["real"]["n"] == 1
    assert st["size_policy"]["target_usd"] == pytest.approx(3.84, abs=0.01) and st["ev_min_eff"] >= D.EV_MIN_BASE and st["max_trades_day"] > 0
    # second run 25 h later: no longer shadow, state carries first_run, log has two lines
    st2 = D.compute(root, BASE, 48.0, 96.0, now=now + 25 * 3600)
    assert st2["shadow"] is False and st2["first_run"] == pytest.approx(st["first_run"]) and sum(1 for _ in open(os.path.join(root, D.LOG_FILE))) == 2
    c2, ch = D.apply_director(BASE, st2)
    assert c2["pump_paper"] is False and c2["pump_play"] is False and c2["live_target_max_usd"] <= 5 and "director_windows" in c2
    assert "Director" in D.report(st2) and "pump" in D.report(st2)
