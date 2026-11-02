"""director.py: the invariant 'never looser than config' on random inputs, every decision function on synthetic evidence,
and an end-to-end compute() on a temporary bot folder. Offline, no wallet, no network."""
import json, os, random, time, csv, calendar, sys, types
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
            "windows": rng.sample(range(24), rng.randint(0, 24)), "max_trades_day": rng.choice([None, 0, 3, 50]), "hours_utc": rng.choice([True, False, None]),
            "regime_gate": rng.choice([None, {}, "garbage", {"sol_trend": ["up"]}, {"heat": ["hot", "normal"], "btc_on": [True, None, "false"]}, {"risk_off": "false"}])}


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
        g = c2["director_regime_gate"]; assert isinstance(g, dict) and all(isinstance(v, list) and "na" not in v and all(isinstance(x, str) for x in v) for v in g.values())
        assert isinstance(c2["director_hours_utc"], bool)
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
    """state v2 (intended change): hours are UTC, so the rows are built with a UTC epoch (the old test used the machine's local time)"""
    data = []
    for hr in range(24):
        for i in range(12): data.append({"t": calendar.timegm((2026, 10, 31, hr, 10 + i, 0)), "ret": (-0.02 if hr in (3, 4) else 0.01), "score": 50})
    hours, table = D.windows_from_data(data)
    assert 3 not in hours and 4 not in hours and len(hours) == 22 and table[3]["n"] == 12
    assert D.windows_from_data(data[:50])[0] == list(range(24))              # too small: unrestricted
    # `hour_utc` wins over `t`: the rows of UTC hour 3 relabelled as hour 20 -> 3 reopens (n=0) and 20 (12 negative + 12 positive) closes
    data2 = [dict(d, hour_utc=(20 if time.gmtime(d["t"]).tm_hour == 3 else time.gmtime(d["t"]).tm_hour)) for d in data]
    hours2, table2 = D.windows_from_data(data2)
    assert 3 in hours2 and 20 not in hours2 and 4 not in hours2 and table2[20]["n"] == 24 and table2[3]["n"] == 0
    # rows without a usable hour do not vote
    assert D.windows_from_data(data + [{"t": "garbage", "ret": -1.0}] * 50)[0] == hours


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


# ---------------------------------------------------------------- state v2: UTC hours, regime gate from the logged context, exit profile source
def test_row_hour_utc_and_windows_ignore_the_machine_timezone():
    t = calendar.timegm((2026, 10, 31, 3, 5, 0))
    assert D.row_hour_utc({"t": t}) == 3 and D.row_hour_utc({"t": t, "hour_utc": 7}) == 7 and D.row_hour_utc({"t": t, "hour_utc": 24}) == 3   # out-of-range hour_utc: back to t
    assert D.row_hour_utc({"t": "2026-10-31T13:05:00+02:00"}) == 11 and D.row_hour_utc({"t": "2026-10-31 23:10:00"}) == 23 and D.row_hour_utc({"t": "09:30"}) == 9
    assert D.row_hour_utc({"t": "garbage"}) is None and D.row_hour_utc({"hour_utc": True}) is None and D.row_hour_utc({}) is None
    if not hasattr(time, "tzset"): return
    old = os.environ.get("TZ"); os.environ["TZ"] = "JST-9"; time.tzset()          # POSIX zone (UTC+9), no tzdata needed
    try:
        assert time.localtime(t).tm_hour == 12 and D.row_hour_utc({"t": t}) == 3
        hours, table = D.windows_from_data([{"t": t + i, "ret": -0.02} for i in range(120)])
        assert 3 not in hours and 12 in hours and table[3]["n"] == 120
        p = os.path.join(os.path.dirname(__file__), "..", "_tmp_ledger_test.csv")
        try:
            write_ledger(p, [["2026-10-31T12:05:00", "solana", "S", "SELL", "1", "3", "0", "0.1", "meme:trail", "48"]])
            assert D.ledger_rows(p, t + 10, 14)[0]["hour"] == 3                     # local 12:05 JST = 03:05 UTC
        finally:
            if os.path.exists(p): os.remove(p)
    finally:
        if old is None: os.environ.pop("TZ", None)
        else: os.environ["TZ"] = old
        time.tzset()


def regime_rows():
    t0 = calendar.timegm((2026, 10, 31, 12, 0, 0)); rows = []
    rows += [{"t": t0 + i, "ret": -0.03, "ctx": {"sol_trend": "down", "btc_on": True, "risk_off": None, "heat": None}} for i in range(40)]                       # flat ctx dict
    rows += [{"t": t0 + 100 + i, "ret": 0.02, "ctx": {"regime": {"sol_trend": "flat", "btc_on": False, "risk_off": (False if i < 5 else None), "heat": None}}} for i in range(60)]   # nested snapshot
    rows += [{"t": t0 + 200 + i, "ret": -0.05, "ctx": {"sol_trend": "up"}} for i in range(8)]       # n < 10: insufficient evidence -> allowed
    rows += [{"t": t0 + 300 + i, "ret": -0.01} for i in range(12)]                                    # no ctx at all -> 'na'
    return rows


def test_regime_from_data_closes_negative_values_keeps_small_samples_open_and_never_allows_unknown():
    rows = regime_rows(); gate, info = D.regime_from_data(rows, BASE)
    assert gate == {"sol_trend": ["up", "flat"], "btc_on": ["false"]}
    assert info["closed"] == {"sol_trend": ["down"], "btc_on": ["true"]} and info["ungated"] == ["risk_off", "heat"]   # < 10 known rows -> no gate on that key
    assert "na" not in gate["sol_trend"] and info["table"]["sol_trend"]["na"] == {"n": 12, "avg_%": -1.0} and info["table"]["btc_on"]["true"]["n"] == 40
    assert info["table"]["risk_off"]["false"]["n"] == 5 and info["table"]["heat"] == {"na": {"n": 120, "avg_%": pytest.approx(-0.43, abs=0.01)}}
    assert "2 claves" in info["note"] and "2 valores cerrados" in info["note"] and "risk_off, heat" in info["note"]
    assert D.regime_from_data(rows[:60], BASE)[0] == {} and D.regime_from_data(None, BASE)[0] == {} and "sin puerta" in D.regime_from_data([], BASE)[1]["note"]
    assert "down" in D.regime_from_data([dict(r, ret=0.0) for r in rows[:40]] + rows[40:], BASE)[0]["sol_trend"]      # n >= 10 and mean >= 0: open
    assert D.regime_from_data(rows + [{"t": 0, "ret": None, "ctx": {"sol_trend": "flat"}}] * 5, BASE)[0] == gate       # non-numeric ret does not vote
    assert D.regime_closed({"regime_gate": {"heat": ["hot"]}}) == {"heat": ["normal", "cold"]}                          # fallback without evidence


def test_entry_allowed_regime_gate_fails_closed_without_fresh_context():
    now = time.time(); c = dict(BASE, director_plays={"scanner": "on"}, director_windows=list(range(24)), director_hours_utc=True, director_max_trades_day=9,
                                director_regime_gate={"sol_trend": ["up", "flat"], "btc_on": ["false"]})
    ok = {"ts": now - 7199, "regime": {"sol_trend": "up", "btc_on": False, "risk_off": True, "heat": "hot"}}
    assert D.entry_allowed(c, 10, 0) == (False, "director: contexto no disponible")                                                   # gate without snapshot
    assert D.entry_allowed(c, 10, 0, ctx={"regime": ok["regime"]}, now=now) == (False, "director: contexto no disponible")            # no ts
    assert D.entry_allowed(c, 10, 0, ctx=dict(ok, ts=now - 7201), now=now) == (False, "director: contexto no disponible")            # stale
    assert D.entry_allowed(c, 10, 0, ctx=dict(ok, ts="hoy"), now=now)[0] is False and D.entry_allowed(c, 10, 0, ctx="x", now=now)[0] is False
    assert D.entry_allowed(c, 10, 0, ctx=dict(ok, ts=now * 1000), now=now) == (False, "director: contexto no disponible")            # milliseconds / future clock: not fresh
    assert D.entry_allowed(c, 10, 0, ctx=dict(ok, ts=now + 200), now=now) == (True, "ok")                                           # small clock skew tolerated
    assert D.entry_allowed(c, 10, 0, ctx=ok, now=now) == (True, "ok")
    assert D.entry_allowed(c, 10, 0, ctx=dict(ok, regime=dict(ok["regime"], sol_trend="down")), now=now) == (False, "director: regimen sol_trend=down cerrado")
    assert D.entry_allowed(c, 10, 0, ctx=dict(ok, regime=dict(ok["regime"], btc_on=None)), now=now) == (False, "director: regimen btc_on=na cerrado")   # unknown never passes
    assert D.entry_allowed(c, 10, 0, ctx={"ts": now, "sol_trend": "flat", "btc_on": "false"}, now=now) == (True, "ok")              # flat snapshot, string bool
    assert D.entry_allowed(c, 10, 0, ctx={"ts": now, "regime": {"sol_trend": "FLAT", "btc_on": "False"}}, now=now) == (True, "ok")   # case-insensitive
    assert D.entry_allowed(dict(c, director_regime_gate={"btc_on": ["na", "false"]}), 10, 0, ctx={"ts": now, "regime": {"btc_on": None}}, now=now)[0] is False   # 'na' in a list still never passes
    assert D.entry_allowed(dict(c, director_regime_gate={"heat": "hot"}), 10, 0, ctx=ok, now=now) == (False, "director: regimen heat=hot cerrado")     # malformed list: closed
    assert D.entry_allowed(dict(c, director_regime_gate=["x"]), 10, 0, ctx=ok, now=now)[0] is False
    # the other gates still come first, and the hour reason says UTC when the state is v2
    assert D.entry_allowed(dict(c, director_windows=[1]), 10, 0, ctx=ok, now=now) == (False, "director: hora 10 UTC fuera de ventana")
    assert D.entry_allowed(dict(c, director_hours_utc=False, director_windows=[1]), 10, 0, ctx=ok, now=now) == (False, "director: hora 10 fuera de ventana")
    assert D.entry_allowed(c, 10, 9, ctx=ok, now=now) == (False, "director: tope diario 9 operaciones alcanzado")
    assert D.entry_allowed(c, 10, 0, play="insider_elite", ctx=ok, now=now) == (True, "ok") and D.entry_allowed(c, 10, 0, play="pump", ctx=ok, now=now)[0]


def test_entry_allowed_uses_context_keys_when_the_snapshot_has_no_regime(monkeypatch):
    fake = types.ModuleType("context"); fake.keys = lambda ctx: ("flat", None, False, "cold"); monkeypatch.setitem(sys.modules, "context", fake)
    now = time.time(); c = dict(BASE, director_regime_gate={"sol_trend": ["flat"], "heat": ["cold", "normal"]})
    assert D.entry_allowed(c, 10, 0, ctx={"ts": now, "sol": {"chg24": 1.0}}, now=now) == (True, "ok")
    assert D.regime_values({"ts": now, "regime": {"sol_trend": None}})["sol_trend"] == "na" and D.regime_values({"heat": None})["heat"] == "na"   # known shape, unknown values: no fallback
    c["director_regime_gate"]["btc_on"] = ["true", "false"]
    assert D.entry_allowed(c, 10, 0, ctx={"ts": now, "sol": {"chg24": 1.0}}, now=now) == (False, "director: regimen btc_on=na cerrado")
    fake.keys = lambda ctx: 1 / 0
    assert D.entry_allowed(c, 10, 0, ctx={"ts": now, "sol": {}}, now=now) == (False, "director: regimen sol_trend=na cerrado")       # a broken context module never passes
    fake.keys = lambda ctx: ("flat",)
    assert D.entry_allowed(c, 10, 0, ctx={"ts": now, "sol": {}}, now=now)[0] is False                                               # wrong arity: ignored, unknown


def test_entry_allowed_empty_gate_is_unchanged_behaviour():
    c = dict(BASE, director_plays={"scanner": "on"}, director_windows=list(range(24)), director_max_trades_day=5, director_regime_gate={})
    assert D.entry_allowed(c, 10, 0) == (True, "ok") and D.entry_allowed(c, 10, 0, ctx=None) == (True, "ok") and D.entry_allowed(c, 10, 5)[0] is False
    assert D.entry_allowed(BASE, 3, 99, ctx={"ts": 1}) == (True, "ok")       # no director keys at all: base config


def test_apply_director_normalises_the_regime_gate_and_flags_the_hour_unit():
    now = time.time(); st = {"ts": now, "shadow": False, "regime_gate": {"sol_trend": ["Up", True, None, "flat"], "heat": "hot"}, "hours_utc": True, "windows": [1, 2]}
    c, ch = D.apply_director(BASE, st)
    assert c["director_regime_gate"] == {"sol_trend": ["flat", "true", "up"], "heat": []} and c["director_hours_utc"] is True and ch == []
    assert D.entry_allowed(c, 1, 0, ctx={"ts": now, "regime": {"sol_trend": "up", "heat": "hot"}}, now=now) == (False, "director: regimen heat=hot cerrado")
    assert D.entry_allowed(c, 1, 0, ctx={"ts": now, "regime": {"sol_trend": None, "heat": "hot"}}, now=now) == (False, "director: regimen sol_trend=na cerrado")
    c, _ = D.apply_director(BASE, {"ts": now, "shadow": False, "regime_gate": "garbage"}); assert c["director_regime_gate"] == {} and c["director_hours_utc"] is False
    c, _ = D.apply_director(BASE, dict(st, shadow=True)); assert "director_regime_gate" not in c                 # shadow: identity, nothing applied


def test_load_state_v1_file_loads_with_defaults_and_compute_rewrites_it_as_v2(tmp_path):
    root = str(tmp_path); now = time.time()
    v1 = {"ts": now - 600, "first_run": now - 30 * 3600, "shadow": False, "version": 1, "plays": {"scanner": "on", "insider_elite": "on", "pump": "off"},
          "min_score_eff": 50, "ev_min_eff": 0.012, "size_policy": {"target_usd": 3.84, "max_frac": 0.08}, "windows": [9, 10, 11],
          "exit_profile": {"hard_stop_pct": 6.0, "trail_pct": 12.0, "why": "sin trayectorias: perfil de config"}, "max_trades_day": 4}
    json.dump(v1, open(os.path.join(root, D.STATE_FILE), "w"))
    st, why = D.load_state(root, now)
    assert why == "ok" and st["version"] == 1 and st["hours_utc"] is False and st["regime_gate"] == {} and st["exit_profile"]["source"] == "config" and st["windows"] == [9, 10, 11]   # nothing converted
    c, ch = D.apply_director(BASE, st)
    assert c["director_windows"] == [9, 10, 11] and c["director_hours_utc"] is False and c["director_regime_gate"] == {} and c["min_score"] == 50
    assert D.entry_allowed(c, 10, 0) == (True, "ok") and D.entry_allowed(c, 12, 0) == (False, "director: hora 12 fuera de ventana")   # empty gate: no context needed
    assert "hora local, estado v1" in D.report(st) and "sin puerta" in D.report(st) and "salida: config" in D.summary_line(st)
    json.dump({"ts": now, "exit_profile": {"hard_stop_pct": 4.0, "trail_pct": 8.0, "why": "replay OOS 1.2% vs config 0.4% (60 trayectorias)"}, "regime_gate": "x", "version": "2"}, open(os.path.join(root, D.STATE_FILE), "w"))
    st, _ = D.load_state(root, now); assert st["version"] == 1 and st["hours_utc"] is False and st["exit_profile"]["source"] == "replay" and st["regime_gate"] == {}
    json.dump(v1, open(os.path.join(root, D.STATE_FILE), "w"))
    st2 = D.compute(root, BASE, 48.0, 96.0, now=now)                       # the next hourly run rewrites the file as v2 and keeps first_run / hysteresis
    saved = json.load(open(os.path.join(root, D.STATE_FILE)))
    assert st2["version"] == saved["version"] == 2 and st2["hours_utc"] is True and st2["first_run"] == pytest.approx(v1["first_run"]) and st2["shadow"] is False
    assert D.load_state(root, now)[0]["version"] == 2


def test_compute_with_paths_sim_and_ctx_wires_exit_grid_regime_gate_and_context(tmp_path):
    root = str(tmp_path); now = time.time(); t0 = calendar.timegm((2026, 10, 31, 12, 0, 0))
    data = [{"t": t0 + i * 60, "ret": (-0.03 if i % 3 == 0 else 0.02), "score": 55, "hour_utc": i % 24,
             "ctx": {"sol_trend": ("down" if i % 3 == 0 else "up"), "btc_on": (i % 2 == 0), "risk_off": None, "heat": "normal"}} for i in range(150)]
    ctx = {"ts": now - 60, "regime": {"sol_trend": "up", "btc_on": True, "risk_off": None, "heat": "normal"}}
    st = D.compute(root, dict(BASE, max_hold_hours=3), 48.0, 96.0, now=now, data=data, paths=paths(200, 3), sim=sim, ctx=ctx)
    assert st["version"] == 2 and st["hours_utc"] is True and st["windows"] == list(range(24))                         # ~6 rows per hour: no hour closes
    assert st["regime_gate"] == {"sol_trend": ["up", "flat"], "btc_on": ["true", "false"], "heat": ["hot", "normal", "cold"]}
    assert st["evidence"]["regime"]["closed"] == {"sol_trend": ["down"], "btc_on": [], "heat": []} and st["evidence"]["regime"]["ungated"] == ["risk_off"]
    assert st["exit_profile"]["source"] in ("replay", "config") and st["evidence"]["exit_grid"] and st["exit_profile"]["hard_stop_pct"] <= 6 and st["exit_profile"]["trail_pct"] <= 12
    assert st["evidence"]["context"] == {"ts": ctx["ts"], "age_s": 60, "fresh": True, "regime": {"sol_trend": "up", "btc_on": "true", "risk_off": "na", "heat": "normal"}}
    line = D.summary_line(st); assert "regimen=3 claves/1 valores cerrados" in line and "salida: " + st["exit_profile"]["source"] in line and "ventana=24h UTC" in line
    rep = D.report(st); assert "Régimen" in rep and "sol_trend: cerrado [down]" in rep and "down n=50" in rep and "risk_off (sin evidencia: sin puerta)" in rep and "Contexto actual" in rep and "fresco" in rep
    saved = json.load(open(os.path.join(root, D.STATE_FILE))); assert saved["regime_gate"] == st["regime_gate"] and saved["version"] == 2 and saved["evidence"]["context"]["regime"]["btc_on"] == "true"
    logl = json.loads(open(os.path.join(root, D.LOG_FILE)).readline()); assert {"key": "regime_gate", "before": {}, "after": st["regime_gate"]} in logl["changes"]
    c, _ = D.apply_director(BASE, dict(st, shadow=False))
    assert c["director_regime_gate"] == {"sol_trend": ["flat", "up"], "btc_on": ["false", "true"], "heat": ["cold", "hot", "normal"]} and c["director_hours_utc"] is True
    assert D.entry_allowed(c, 5, 0, ctx=ctx, now=now) == (True, "ok") and D.entry_allowed(c, 5, 0, now=now) == (False, "director: contexto no disponible")
    assert D.entry_allowed(c, 5, 0, ctx=dict(ctx, regime=dict(ctx["regime"], sol_trend="down")), now=now) == (False, "director: regimen sol_trend=down cerrado")
    # a stale snapshot is recorded as not fresh (information only: compute never trades) and _diff stays quiet on an unchanged gate
    st2 = D.compute(root, BASE, 48.0, 96.0, now=now + 60, data=data, ctx={"ts": now - 9000, "regime": ctx["regime"]}, write=False)
    assert st2["evidence"]["context"]["fresh"] is False and st2["evidence"]["context"]["age_s"] == 9060 and "NO disponible" in D.report(st2)
    assert D._diff(st, st2) == [] and D._diff({}, {"regime_gate": {}}) == [] and D._diff({"regime_gate": {}}, {"regime_gate": {"heat": ["hot"]}})[0]["key"] == "regime_gate"


def test_compute_without_paths_sim_or_ctx_falls_back_to_config_and_no_gate(tmp_path):
    root = str(tmp_path); now = time.time()
    st = D.compute(root, BASE, 48.0, 96.0, now=now, data=None, write=False)
    assert st["exit_profile"] == {"hard_stop_pct": 6.0, "trail_pct": 12.0, "source": "config", "why": "sin trayectorias: perfil de config"}
    assert st["regime_gate"] == {} and st["evidence"]["context"] is None and st["evidence"]["regime"]["table"] == {} and st["windows"] == list(range(24)) and st["hours_utc"] is True
    assert not os.path.exists(os.path.join(root, D.STATE_FILE))                                                         # write=False
    assert "salida: config" in D.summary_line(st) and "regimen=0 claves/0 valores cerrados" in D.summary_line(st) and "- Régimen (puerta por contexto registrado): sin puerta (dataset 0" in D.report(st)
    st = D.compute(root, BASE, 48.0, 96.0, now=now, paths=paths(100, 4), sim=None, write=False)                        # paths without sim: config profile
    assert st["exit_profile"]["source"] == "config" and st["evidence"]["exit_grid"] == {}
    st = D.compute(root, dict(BASE, max_hold_hours=3), 48.0, 96.0, now=now, paths=paths(30, 5), sim=sim, write=False)   # too few test paths: config profile, grid empty
    assert st["exit_profile"]["source"] == "config" and st["evidence"]["exit_grid"] == {} and "trayectorias" in st["exit_profile"]["why"]
    # a dataset >= 100 rows without any ctx: every key unknown -> no gate (never a blanket block), while the UTC hours still count
    data = [{"t": calendar.timegm((2026, 10, 31, 3, 0, 0)) + i, "ret": -0.02} for i in range(120)]
    st = D.compute(root, BASE, 48.0, 96.0, now=now, data=data, write=False)
    assert st["regime_gate"] == {} and st["evidence"]["regime"]["ungated"] == list(D.REGIME_KEYS) and 3 not in st["windows"] and len(st["windows"]) == 23
    assert st["evidence"]["regime"]["table"]["heat"] == {"na": {"n": 120, "avg_%": -2.0}}
    c, _ = D.apply_director(BASE, dict(st, shadow=False)); assert D.entry_allowed(c, 4, 0) == (True, "ok") and D.entry_allowed(c, 3, 0)[0] is False
