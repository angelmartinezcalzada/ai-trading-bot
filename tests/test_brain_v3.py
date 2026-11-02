"""Brain v3: labelled archive (append-once, never relabelled, decay weights, per-mint caps, cfg_hash down-weighting, labels with the
BASE exit rules), continuous feature block with missing-field flags, lambda selection, local n_eff, ridge lower bound, 3-fold
rolling-origin validation with mint-episode grouping and embargo, vote accounting, 2-win model switch, migration of a v2 state.
Everything offline: the bar fetch is monkeypatched, the whole file runs in well under a second."""
import json, os, sys, time, types, random, shutil
import pytest
import brain, eval_solana, director


def _ctx_available():
    try: import context; return True
    except ImportError: return False

C = {"min_liquidity_usd": 50000, "min_score": 45, "brain_min_score": 45, "position_pct": 0.05, "max_hold_hours": 3, "exit_mode": "trail", "hard_stop_pct": 6, "trail_pct_tt": 12}
iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def _cand(t, mint, pair, score=55, fail=(), liq=100000, **extra):
    r = {"ts": iso(t), "mint": mint, "pair": pair, "score": score, "fail": list(fail), "liq": liq, "price": 1.0, "src": "gecko_trending",
         "parts": {"parts": {"buy_press": 6, "insiders": 0}, "age_h": 2, "h1": 5, "m5": 1, "vol_liq": 1.5, "b_s": "10/5"}, "rug": {"top10": 10, "holders": 6000}}
    r.update(extra); return r


def _bars(start, n, low=1.0): return [[start + 60*i, 1.0, 1.01, low if i == n-1 else 1.0, 1.0] for i in range(n)]   # crash on the last bar -> hard stop (resolved)


def _write(rows, cache):
    with open("candidates_solana.jsonl", "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    json.dump(cache, open("ohlcv_cache.json", "w"))


def _offline(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(brain, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network in tests")))
    monkeypatch.setattr(brain.time, "sleep", lambda s: None)
    return brain.Brain(str(tmp_path / "brain_state.json"))


def _day0(now):
    d = int(now // 86400) * 86400 + 2*3600
    return d if now - d > 4*3600 else d - 86400     # 02:00 UTC of a day old enough that 10-min sightings stay inside one UTC day


def good_data(n=200, windfall=None):
    """'good' on -> +5 %, off -> -5 %; score 60/40 so the floor matters; 30 cycling mints 8 h apart (one episode per row).
    windfall=(a, b): the score>=45 LOSERS inside that fraction of the time span win +50 % instead (the baseline beats the brain there)"""
    out = []
    for i in range(n):
        on = i % 2 == 0; t = 1000*i; ret = 0.05 if on else -0.05
        if windfall and not on and i % 4 == 1 and windfall[0]*1000*(n-1) <= t < windfall[1]*1000*(n-1): ret = 0.5
        out.append({"t": t, "t_exit": t + (5000 if i == 139 else 100), "S": {"good": on}, "ret": ret, "score": 60 if i % 4 in (0, 1) else 40, "mint": f"m{i % 30}"})
    return out


def planted(n, seed=0):
    rng = random.Random(seed); out = []
    for i in range(n):
        on = rng.random() < 0.5; sc = rng.choice([50, 60]) if on else rng.choice([40, 50]); win = rng.random() < (0.7 if on else 0.25)
        out.append({"t": 1000*i, "t_exit": 1000*i + 100, "S": {"good": on, "noise": rng.random() < 0.5}, "ret": 0.06 if win else -0.05, "score": sc, "mint": f"m{i % 30}"})
    return out


# ---------------------------------------------------------------- archive
def test_archive_append_once_never_relabels_and_exposes_paths(tmp_path, monkeypatch):
    b = _offline(monkeypatch, tmp_path); now = time.time(); t0 = now - 6*3600
    rows = [_cand(t0, "A", "pA", rid="A:r1", ctx={"hour_utc": 9, "sol_trend": "up"}, st_f={"snipers_pct": 1.0, "holders": None}, rt_src="imputed", roundtrip_loss_pct=1.5),
            _cand(t0 + 900, "B", "pB")]
    _write(rows, {"pA": {"at": now, "bars": _bars(t0, 200, low=0.5)}, "pB": {"at": now, "bars": _bars(t0 + 900, 200, low=0.5)}})
    data = b.build_dataset(C, max_fetch=0)
    assert [d["mint"] for d in data] == ["A", "B"] and b._archive_n == 2 and b._cfg_mismatch == 0 and b._cfg_hash == brain.cfg_hash(C)
    arch = [json.loads(l) for l in open("data/labels_solana.jsonl")]
    a = arch[0]; assert a["rid"] == "A:r1" and arch[1]["rid"] == f"B:{iso(t0 + 900)}"          # rid written by memebot, else mint:ts
    assert a["code"] == "brain/3" and a["cfg_hash"] == brain.cfg_hash(C) and a["exit"] == "hard_stop" and a["rt"] == 1.5 and a["rt_src"] == "imputed"
    assert a["ctx"] == {"hour_utc": 9, "sol_trend": "up"} and a["st_f"]["snipers_pct"] == 1.0 and a["x"]["hour"] == 9 and a["x"]["st"]["holders"] is None
    assert set(a) >= {"rid", "t", "t_exit", "mint", "S", "x", "ret", "exit", "rt", "rt_src", "cfg_hash", "code", "score", "pair"}
    assert arch[1]["rt"] == 3.0 and arch[1]["rt_src"] is None and arch[1]["x"]["rt"] is None       # no sellability quote -> default cost, flagged missing
    # paths for the director's exit grid: (bars from the sighting, round-trip cost) in time order
    assert len(b.paths) == 2 and b.paths[0][1] == 1.5 and b.paths[1][1] == 3.0 and b.paths[0][0][0][0] >= t0 and len(b.paths[0][0]) == 200
    prof, grid = director.exit_grid(b.paths, C, eval_solana.sim); assert prof["hard_stop_pct"] == 6 and prof["trail_pct"] == 12   # too few paths -> config profile, no crash
    # append-once + never relabel: new candles that would change the label do not touch the archived row
    _write(rows, {"pA": {"at": now, "bars": _bars(t0, 200, low=1.0)}, "pB": {"at": now, "bars": _bars(t0 + 900, 200, low=1.0)}})
    data2 = b.build_dataset(C, max_fetch=0)
    assert len(open("data/labels_solana.jsonl").read().splitlines()) == 2 and [d["ret"] for d in data2] == [d["ret"] for d in data] and b._archive_n == 2
    # a new sighting later joins the archive; an older rid stays as it was
    _write(rows + [_cand(t0 + 3600, "A", "pA")], {"pA": {"at": now, "bars": _bars(t0, 400, low=0.5)}, "pB": {"at": now, "bars": _bars(t0 + 900, 200, low=0.5)}})
    data3 = b.build_dataset(C, max_fetch=0)
    assert len(data3) == 3 and b._archive_n == 3 and data3[0]["ret"] == data[0]["ret"] and all(0 < d["w"] <= 1 for d in data3)


def test_build_dataset_fetches_missing_bars_offline_and_caches_them(tmp_path, monkeypatch):
    """the GeckoTerminal fetch is injected: the merged/pruned cache and the label come from the fake payload (no network)"""
    monkeypatch.chdir(tmp_path); now = time.time(); t0 = now - 2*3600; calls = []
    def fake_get(url, **p):
        calls.append(url); return {"data": {"attributes": {"ohlcv_list": [[t0 + 60*i, 1.0, 1.02, 0.4 if i == 59 else 1.0, 1.0, 1234.0] for i in range(60)]}}}
    monkeypatch.setattr(brain, "get", fake_get); monkeypatch.setattr(brain.time, "sleep", lambda s: None)
    _write([_cand(t0, "F", "pF"), _cand(t0, "G", "pG", fail=["mint_authority"])], {})
    b = brain.Brain(str(tmp_path / "brain_state.json")); data = b.build_dataset(C, max_fetch=5)
    assert len(calls) == 1 and "pF" in calls[0] and [d["mint"] for d in data] == ["F"] and data[0]["ret"] < -0.05
    oc = json.load(open("ohlcv_cache.json")); assert len(oc["pF"]["bars"]) == 60 and len(oc["pF"]["bars"][0]) == 5 and not os.path.exists("ohlcv_cache.json.tmp")
    assert b.build_dataset(C, max_fetch=0) and len(calls) == 1                                  # archived: no refetch, no relabel


def test_training_rows_decay_caps_and_cfg_hash_downweight():
    now = 1_800_000_000; h = brain.cfg_hash(C); other = brain.cfg_hash(dict(C, hard_stop_pct=3))
    row = lambda rid, t, mint, ch=h: {"rid": rid, "t": t, "t_exit": t + 60, "mint": mint, "S": {"good": True}, "x": {}, "ret": 0.01, "score": 50, "cfg_hash": ch}
    arch = [row("a0", now - 10*86400, "A"), row("a1", now - 20*86400, "A"), row("a2", now, "A"), row("o", now, "O", other)]
    arch += [row(f"z{i}", now - 86400*2 + 600*i, "Z") for i in range(10)]                     # 10 sightings in one UTC day -> 6
    arch += [row(f"y{d}_{i}", now - 86400*(12 - d) + 7200 + 600*i, "Y") for d in range(10) for i in range(4)]   # 40 over 10 days -> newest 30
    rows = brain._training_rows(arch, h, now); W = {d["rid"]: d["w"] for d in rows}
    assert W["a2"] == 1.0 and W["a0"] == pytest.approx(0.5, abs=0.001) and W["a1"] == pytest.approx(0.25, abs=0.001)   # half-life 10 d
    assert W["o"] == 0.5                                                                        # labelled under another exit rule: x0.5
    assert sum(1 for d in rows if d["mint"] == "Z") == 6 and sum(1 for d in rows if d["mint"] == "Y") == 30
    ys = [d["rid"] for d in rows if d["mint"] == "Y"]; assert "y0_0" not in ys and "y9_3" in ys     # the oldest day dropped, the newest kept
    assert [d["t"] for d in rows] == sorted(d["t"] for d in rows)


def test_labels_use_the_base_exit_rules_and_learn_passes_cfg_base(tmp_path, monkeypatch):
    b = _offline(monkeypatch, tmp_path); now = time.time(); t0 = now - 6*3600
    # dip to -4.96 % net (hits a director-tightened 3 % stop, not the owner's 6 %), then +50 % and a 12 % trail exit
    bars = [[t0, 1.0, 1.0, 1.0, 1.0], [t0 + 60, 1.0, 1.0, 0.96, 0.97], [t0 + 120, 0.97, 1.5, 0.97, 1.45], [t0 + 180, 1.45, 1.46, 1.30, 1.31]] + [[t0 + 60*i, 1.31, 1.31, 1.31, 1.31] for i in range(4, 30)]
    _write([_cand(t0, "A", "pA", roundtrip_loss_pct=1.0)], {"pA": {"at": now, "bars": bars}})
    tight = dict(C, hard_stop_pct=3); base = dict(C)
    data = b.build_dataset(tight, max_fetch=0, cfg_base=base)
    a = json.loads(open("data/labels_solana.jsonl").readline())
    assert a["exit"] == "trail" and a["ret"] == pytest.approx(1.31*0.99 - 1) and a["cfg_hash"] == brain.cfg_hash(base) != brain.cfg_hash(tight)
    dec = 0.5**((time.time() - t0)/(10*86400))                                                        # 6 h of decay
    assert data[0]["cfg_hash"] == brain.cfg_hash(base) and data[0]["w"] == pytest.approx(dec, abs=0.002) and b._cfg_mismatch == 0   # labelled with the base rule = the current hash
    assert b.build_dataset(tight, max_fetch=0)[0]["w"] == pytest.approx(0.5*dec, abs=0.002) and b._cfg_mismatch == 1                # read with the tightened hash: reported and down-weighted, never relabelled
    seen = []; monkeypatch.setattr(brain.Brain, "build_dataset", lambda s, cfg, max_fetch=40, cfg_base=None: seen.append(cfg_base) or good_data())
    out = b.learn(tight, cfg_base=base); assert seen == [base] and out["cfg_hash"] == brain.cfg_hash(base) and out["code_version"].startswith("brain/3@")
    assert out["decay_half_life_d"] == 10 and "archive_n" in out and out["lambda"] and set(out["lambda"]) == {"logit", "ridge"}


def test_veto_class_and_optional_fields_in_the_universe(tmp_path, monkeypatch):
    b = _offline(monkeypatch, tmp_path); now = time.time(); t0 = now - 6*3600
    vc = {"top10": "soft", "score<50": "policy", "director_gate": "policy", "odd_new_veto": "hard"}
    rows = [_cand(t0, "P", "pP", fail=["score<50", "director_gate"], veto_class=vc),   # policy fails: tradable universe
            _cand(t0, "S", "pS", fail=["top10"], veto_class=vc),                        # soft: out (the normal entry needs no fail at all)
            _cand(t0, "H", "pH", fail=["odd_new_veto"], veto_class=vc),                 # hard: out
            _cand(t0, "U", "pU", fail=["unknown_name"]),                                # no class, unknown name -> hard (fail-closed)
            _cand(t0, "N", "pN", fail=["no_sellability_check"])]                        # name rule keeps book-state skips
    _write(rows, {p: {"at": now, "bars": _bars(t0, 200, low=0.5)} for p in ("pP", "pS", "pH", "pU", "pN")})
    assert sorted(d["mint"] for d in b.build_dataset(C, max_fetch=0)) == ["N", "P"]
    assert brain._hard_fails({"fail": ["brain_ev<=0", "score<45", "director_gate"]}) == [] and brain._hard_fails({"fail": ["mint_authority"]}) == ["mint_authority"]


def test_per_mint_day_cap_counts_archived_rows(tmp_path, monkeypatch):
    b = _offline(monkeypatch, tmp_path); now = time.time(); t0 = _day0(now)
    rows = [_cand(t0 + 600*i, "A", "pA") for i in range(4)]
    _write(rows, {"pA": {"at": now, "bars": _bars(t0, 400, low=0.5)}})
    assert len(b.build_dataset(C, max_fetch=0)) == 4
    _write(rows + [_cand(t0 + 600*i, "A", "pA") for i in range(4, 12)], {"pA": {"at": now, "bars": _bars(t0, 400, low=0.5)}})
    data = b.build_dataset(C, max_fetch=0)
    assert len(data) == 6 and b._archive_n == 6 and len(open("data/labels_solana.jsonl").read().splitlines()) == 6   # 4 archived + 2 new, the rest capped


# ---------------------------------------------------------------- features
def test_signals_renamed_and_insider_tier():
    base = {"parts": {"parts": {"buy_press": 1, "insiders": -3}, "age_h": 2}, "liq": 1000, "score": 60, "score_brain": 40}
    S = brain.signals(base)
    assert S["rc_insiders"] is True and "insiders" not in S and S["score_hi"] is False          # score_hi reads score_brain, not the adjusted score
    assert brain.signals({**base, "insider": {"conv": 3, "elite": 0}}).items() >= {"insider_t1": True, "insider_t2": False}.items()
    assert brain.signals({**base, "insider": {"conv": 0, "elite": 1}}).items() >= {"insider_t1": True, "insider_t2": True}.items()
    st = brain.signals({**base, "insider": {"conv": 5, "elite": 2, "sells": 3, "stale": True, "age_s": 9999}})
    assert st["insider_t1"] is False and st["insider_t2"] is False and st["insider_sell"] is True   # stale: no positive evidence, the sell signal stays
    assert "insider_t1" not in brain.signals(base) and len(brain.signals({**base, "insider": {"conv": 0}, "narr": [], "heat": "hot"})) == 23


def test_feature_block_shapes_with_missing_fields(monkeypatch):
    assert len(brain.XC) == 49 and len(brain.xvec({})) == len(brain.XC) and len(brain.xvec(None)) == len(brain.XC)
    v = dict(zip(brain.XC, brain.xvec({})))
    assert v["rt"] == 3.0 and v["rt_missing"] == 1.0 and v["buys"] == 0.5 and v["buys_missing"] == 1.0 and v["ctx_missing"] == 1.0
    assert all(v[f"st_{k}_missing"] == 1.0 and v[f"st_{k}"] == 0.0 for k in brain.ST_F) and v["hour_sin"] == 0.0 and v["score"] == 0.0 and v["src_0"] == 0.0
    rec = {"ts": "2026-11-02T10:00:00", "src": "dex_boosts", "liq": 120000, "score": 58, "score_brain": 55, "roundtrip_loss_pct": 1.2,
           "parts": {"parts": {"buy_press": 6}, "age_h": 5, "vol_liq": 2.1, "h1": 250, "m5": -90, "b_s": "120/80"}, "rug": {"top10": 12.5, "holders": 8000},
           "insider": {"tok": 4, "w": 0.5}, "st_f": {"snipers_pct": 2.0, "bundlers_pct": None, "holders": 8000, "migrated": True}, "ctx": {"hour_utc": 3}}
    x = brain.xraw(rec); v = dict(zip(brain.XC, brain.xvec(x, ["gecko_trending", "dex_boosts"])))
    assert x["ins"] == 2.0 and x["buys"] == 0.6 and x["hour"] == 3 and x["score"] == 55 and x["st"]["bundlers_pct"] is None
    assert x["cx"] is None or {k for k, v in x["cx"].items() if v} <= {"night_utc"}   # context.py present (merged): no regime data -> only night_utc (hour 3) can be True; absent -> None
    assert v["h1"] == 100.0 and v["m5"] == -30.0 and v["rt"] == 1.2 and v["rt_missing"] == 0.0 and v["src_1"] == 1.0 and v["src_0"] == 0.0
    assert v["st_snipers_pct"] == 2.0 and v["st_bundlers_pct_missing"] == 1.0 and v["st_migrated"] == 1.0 and v["st_holders"] == pytest.approx(8.987, abs=0.01)
    assert v["liq_log"] == pytest.approx(11.695, abs=0.01) and v["hour_sin"] == pytest.approx(0.7071, abs=1e-3) and v["score"] == 0.55 and v["ctx_missing"] == (0.0 if _ctx_available() else 1.0)   # ctx present + context.py importable -> not missing
    assert brain.xraw({**rec, "insider": {"tok": 4, "w": 0.5, "stale": True}})["ins"] is None                      # stale insider -> 0 (after xvec)
    assert brain.xraw({"ts": "2026-11-02T10:00:00"})["hour"] is not None and brain.xraw({})["hour"] is None             # hour from ts when ctx has none
    # the context helper: present -> booleans; broken -> treated as missing
    fake = types.ModuleType("context"); fake.signals = lambda c: {"sol_up": c.get("sol_trend") == "up", "risk_off": bool(c.get("risk_off"))}
    monkeypatch.setitem(sys.modules, "context", fake)
    x = brain.xraw({**rec, "ctx": {"sol_trend": "up", "risk_off": False, "hour_utc": 3}}); v = dict(zip(brain.XC, brain.xvec(x)))
    assert x["cx"]["sol_up"] is True and x["cx"]["risk_off"] is False and x["cx"]["weekend"] is False and v["sol_up"] == 1.0 and v["ctx_missing"] == 0.0
    monkeypatch.setitem(sys.modules, "context", types.ModuleType("context"))                   # no signals() -> AttributeError -> {}
    x = brain.xraw({**rec, "ctx": {"sol_trend": "up"}}); assert x["cx"] is None and dict(zip(brain.XC, brain.xvec(x)))["ctx_missing"] == 1.0


# ---------------------------------------------------------------- models
def test_lambda_from_the_grid_and_local_n_eff():
    b = brain.Brain.__new__(brain.Brain); b.ctx = {}
    m = b.fit(planted(300, seed=1))
    assert m["lambda"]["logit"] in brain.LAMBDAS and m["lambda"]["ridge"] in brain.LAMBDAS and m["logit"]["lambda"] == m["lambda"]["logit"]
    assert m["feat"]["xc"] == list(brain.XC) and len(m["feat"]["mu"]) == len(brain.XC) + 2 and len(m["bool_rows"]) == 300 and m["keys"] == ["good", "noise"]
    import numpy as np
    assert brain._pick_lambda(np.zeros((10, 2)), np.array([0.0, 1.0]*5), np.ones(10), "logit") == max(brain.LAMBDAS)   # too small an inner split -> most regularised
    st = {"keys": ["a", "b", "c", "d"], "bool_rows": [0b1111, 0b1110, 0b1100, 0b1000, 0b0000, 0b0001]}
    assert brain.Brain.local_n({"a": 1, "b": 1, "c": 1, "d": 1}, st) == 5     # 3 rows within Hamming 2 -> floor 5
    assert brain.Brain.local_n({"a": 1, "b": 1, "c": 1, "d": 1}, {"keys": ["a", "b", "c", "d"], "bool_rows": [0b1111]*8 + [0b0000]}) == 8
    assert brain.Brain.local_n({"a": 1}, {}) == brain.LOCAL_MIN_N
    m["model_choice"] = "logit"; b.st = m
    p, n = b._p({"good": True, "noise": False}, 55); assert 0 < p < 1 and n == 300                          # 2 booleans: every row is a neighbour
    pb, nb = b._p_beta({"good": True, "noise": False}); assert nb <= 300 and "ne_on" in m["weights"]["good"]
    assert b._p_logit({"good": True}, 55, {**m, "feat": {**m["feat"], "xc": ["other"]}})[0] is None               # feature layout mismatch -> not fitted (fail-closed)


def test_ridge_lower_bound_and_decide_keys():
    b = brain.Brain.__new__(brain.Brain); b.ctx = {}
    m = b.fit(planted(300, seed=2)); b.st = {**m, "model_choice": "ridge", "active": True}
    rh, rl = b._ret({"good": True, "noise": False}, 55); assert rh is not None and rl <= rh and rh - rl == pytest.approx(m["ridge"]["resid_sd"]/300**0.5)
    rec = {"score": 60, "parts": {"parts": {"buy_press": 6}, "age_h": 2}, "liq": 60000}
    d = b.decide(rec, 48.0, dict(C, brain_ev_min=0.01)); d2 = b.decide(rec, 48.0, dict(C, brain_ev_min=0.01, director_fixed_share=0.02))
    assert set(d) >= {"p", "p_low", "n_eff", "ev_pct", "ev_min_pct", "ev_ok", "kelly_pct", "size", "active", "model", "on", "ret_hat", "ret_lb"}
    assert d["model"] == "ridge" and d["ret_lb"] <= d["ret_hat"] and d["ev_pct"] == pytest.approx(100*d["ret_lb"], abs=0.02) and d["ev_ok"] == (d["ev_pct"] > 1.0)
    assert d2["ev_pct"] == pytest.approx(d["ev_pct"] - 2.0, abs=0.02) and d["p_low"] < d["p"] and d["size"] <= 48.0 * C["position_pct"]
    b.st = {**m, "model_choice": "logit"}; dl = b.decide(rec, 48.0, C); assert dl["model"] == "logit" and dl["ret_hat"] is not None and dl["n_eff"] >= brain.LOCAL_MIN_N
    b.st = {**m, "model_choice": "ridge", "ridge": None}; assert b.decide(rec, 48.0, C)["model"] == "logit"      # ridge missing -> the logit EV rule
    b.st = {"base": 0.5, "weights": {}, "avg_win": 0.06, "avg_loss": 0.05, "n": 50}; d0 = b.decide(rec, 48.0, C)
    assert d0["model"] == "beta" and d0["ret_hat"] is None and d0["ret_lb"] is None and d0["n_eff"] == 50


def test_fit_uses_sample_weights():
    b = brain.Brain.__new__(brain.Brain); b.ctx = {}
    rows = [{"t": i, "S": {"g": True}, "ret": 0.05 if i < 10 else -0.05, "score": 50, "mint": "m", "w": 1.0 if i < 10 else 0.01} for i in range(20)]
    m = b.fit(rows); u = b.fit([{**r, "w": 1.0} for r in rows])                                 # the same rows unweighted: 10 wins / 10 losses
    assert m["weights"]["g"]["n_on"] == 20 and m["weights"]["g"]["ne_on"] < 11 and u["weights"]["g"]["ne_on"] == 20
    assert m["base"] > u["base"] and m["weights"]["g"]["p_on"] > u["weights"]["g"]["p_on"]           # the down-weighted losers barely count...
    assert u["avg_loss"] == pytest.approx(0.06, abs=1e-3) and 0.05 < u["avg_loss"] < m["avg_loss"] <= 0.08   # ...so avg_loss shrinks toward its 0.08 prior (more pessimistic, never less)


# ---------------------------------------------------------------- validation
def test_folds_group_mint_episodes_and_respect_the_embargo():
    E = 3*3600; rows = []
    rows += [{"t": t, "t_exit": t + 900, "S": {}, "ret": 0.0, "score": 50, "mint": "E"} for t in range(0, 200_001, 600)]      # one continuous episode across every cut
    rows += [{"t": 100_000 + 3600, "t_exit": 100_000 + 3700, "S": {}, "ret": 0.0, "score": 50, "mint": "N1"}]               # first seen inside the embargo
    rows += [{"t": 100_000 + 4*3600 + k, "t_exit": 100_000 + 4*3600 + k + 60, "S": {}, "ret": 0.0, "score": 50, "mint": "N2"} for k in (0, 600, 90_000)]
    rows += [{"t": 10_000, "t_exit": 10_060, "S": {}, "ret": 0.0, "score": 50, "mint": "R"}, {"t": 150_000, "t_exit": 150_060, "S": {}, "ret": 0.0, "score": 50, "mint": "R"}]   # re-sighted 39 h later: a new episode
    data = sorted(rows, key=lambda d: d["t"]); F = brain.folds(data); t1 = data[-1]["t"]
    assert len(F) == 3 and [round(c) for c, *_ in F] == [round(f*t1) for f in (0.5, 0.6, 0.7)]                                        # cuts on the time span (t0 = 0)
    cut, tr, te, purged = F[0]
    assert all(d["mint"] != "E" for d in te) and all(d["t_exit"] <= cut for d in tr if d["mint"] == "E")                              # E never straddles
    assert purged == sum(1 for d in data if d["mint"] == "E" and d["t"] < cut < d["t_exit"]) == 2                                   # E rows whose exit lies past the cut
    assert all(d["mint"] != "N1" for d in tr + te) and sum(1 for d in te if d["mint"] == "N2") == 3                                  # embargo; N2 whole episode in test
    assert all(d["t"] >= cut + E for d in te) and all(d["t"] < cut for d in tr) and len(te) == 4
    assert any(d["mint"] == "R" for d in tr) and any(d["mint"] == "R" and d["t"] == 150_000 for d in te)                             # a mint re-seen after a 3 h gap is a new episode
    for cut, tr, te, _ in F:
        assert not ({d["mint"] for d in tr if d["mint"] == "E"} & {d["mint"] for d in te}) and all(d["t"] >= cut + E for d in te)
    assert brain.folds([]) == []


def test_vote_needs_25_new_archived_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); data = good_data()
    b = brain.Brain.__new__(brain.Brain); b.st = {"active": False, "active_votes": 0}; b.ctx = {}; b.path = str(tmp_path / "brain_state.json")
    monkeypatch.setattr(brain.Brain, "build_dataset", lambda s, cfg, max_fetch=40: data)
    seq = []
    for n in (100, 100, 124, 125, 130, 150, 175):
        b._archive_n = n; out = b.learn(C); o = out["oos"]; seq.append((o["vote"], o["vote_counted"], out["active_votes"], out["active"], o["vote_archive_n"]))
    assert seq == [(True, True, 1, False, 100), (True, False, 1, False, 100), (True, False, 1, False, 100), (True, True, 2, False, 125),
                   (True, False, 2, False, 125), (True, True, 3, True, 150), (True, True, 4, True, 175)]
    assert out["folds"] and all(f["valid"] and f["brain_avg_ret_%"] > f["baseline_avg_ret_%"] for f in out["folds"]) and o["n_folds"] == 3
    b._archive_n = 200; out = b.learn(dict(C, brain_min_score=99)); assert out["active"] is False and out["active_votes"] == 0 and out["oos"]["vote"] is False   # one failing refit deactivates
    b._archive_n = 300; out = b.learn(C); assert out["active_votes"] == 1 and out["active"] is False                                                      # and the count restarts


def test_activation_impossible_when_any_fold_fails(tmp_path, monkeypatch):
    """the headline (70 %) fold alone would vote (v2 behaviour); the 50 % fold's baseline wins a windfall -> no vote, ever"""
    monkeypatch.chdir(tmp_path); data = good_data(windfall=(0.51, 0.70))
    b = brain.Brain.__new__(brain.Brain); b.st = {"active": False, "active_votes": 0}; b.ctx = {}; b.path = str(tmp_path / "brain_state.json")
    monkeypatch.setattr(brain.Brain, "build_dataset", lambda s, cfg, max_fetch=40: data)
    for _ in range(3): out = b.learn(C)
    o, F = out["oos"], out["folds"]
    assert o["brain_trades"] >= 8 and o["brain_mints"] >= 10 and o["brain_avg_ret_%"] > 0 and o["brain_avg_ret_%"] > o["baseline_avg_ret_%"]
    assert F[0]["brain_avg_ret_%"] <= F[0]["baseline_avg_ret_%"] and all(f["brain_avg_ret_%"] > f["baseline_avg_ret_%"] for f in F[1:])
    assert o["folds_ok"] is False and o["vote"] is False and out["active"] is False and out["active_votes"] == 0
    assert json.load(open(b.path))["active"] is False and not os.path.exists(b.path + ".tmp")


def test_model_switch_needs_two_consecutive_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); data = planted(400, seed=3)     # the planted signal lifts the linear models above Beta (Beta's pessimism finds no trade)
    b = brain.Brain.__new__(brain.Brain); b.st = {"active": False, "active_votes": 0}; b.ctx = {}; b.path = str(tmp_path / "brain_state.json")
    monkeypatch.setattr(brain.Brain, "build_dataset", lambda s, cfg, max_fetch=40: data)
    o1 = b.learn(C); w = o1["oos"]["winner"]
    assert w in ("logit", "ridge") and o1["model_choice"] == "beta" and o1["oos"]["model_choice"] == "beta" and o1["oos"]["models_hist"] == [w] and o1["oos"]["switched"] is False
    for ch in ("logit", "ridge"):
        q, bq = o1["oos"]["models"][ch], o1["oos"]["models"]["beta"]; assert q["trades"] >= 8 and (bq["avg_ret_%"] is None or q["avg_ret_%"] > bq["avg_ret_%"])
    o2 = b.learn(C)
    assert o2["oos"]["models_hist"] == [w, w] and o2["oos"]["switched"] is True and o2["model_choice"] == w and o2["oos"]["model_choice"] == w
    assert o2["active"] is False and o2["active_votes"] <= 1                                 # a switch restarts the activation count
    assert json.load(open(b.path))["model_choice"] == w and b.decide({"score": 60, "parts": {"parts": {"buy_press": 6}, "age_h": 2}, "liq": 60000}, 48.0, C)["model"] == w
    b.st["oos"]["models_hist"] = ["beta", "logit", "ridge", "logit"]; o3 = b.learn(C)         # alternating winners never switch away from the deployed model
    assert o3["model_choice"] == w and len(o3["oos"]["models_hist"]) == 5 and (o3["oos"]["switched"] is False or o3["oos"]["models_hist"][-2:] == [o3["oos"]["winner"]]*2)


# ---------------------------------------------------------------- compatibility
def test_migration_of_a_v2_state_and_backward_compatible_decide(tmp_path, monkeypatch):
    src = os.path.join(os.path.dirname(os.path.abspath(brain.__file__)), "data", "brain_state.json")
    p = tmp_path / "brain_state.json"; shutil.copy(src, p); old = json.load(open(src))
    b = brain.Brain(str(p)); W = b.st["weights"]
    assert "rc_insiders" in W and "insider_t1" in W and "insider_t2" in W and not {"insiders", "insider_conv", "insider_elite"} & set(W)
    assert W["rc_insiders"] == old["weights"]["insiders"] and W["insider_t2"] == old["weights"]["insider_elite"] and b.st["active"] is False and b.st.get("model_choice", "beta") == "beta"
    assert "logit" not in b.st and b.st["n_labelled"] == old["n_labelled"] and b.st["oos"] == old["oos"]          # dashboard keys survive
    rec = {"score": 60, "parts": {"parts": {"buy_press": 6, "insiders": -3}, "age_h": 2}, "liq": 60000, "insider": {"conv": 3, "elite": 1, "sells": 0}}
    d = b.decide(rec, 48.0, dict(C, brain_ev_min=0.01))
    assert d["model"] == "beta" and set(d) >= {"p", "p_low", "n_eff", "ev_pct", "ev_min_pct", "ev_ok", "kelly_pct", "size", "active", "model", "on", "ret_hat", "ret_lb"}
    assert {"rc_insiders", "insider_t1", "insider_t2"} <= set(d["on"]) and d["n_eff"] > 0
    monkeypatch.chdir(tmp_path); monkeypatch.setattr(brain.Brain, "build_dataset", lambda s, cfg, max_fetch=40: good_data())
    out = b.learn(C); st = json.load(open(p))
    assert st["code_version"].startswith("brain/3") and st["active"] is False and st["active_votes"] == 1 and st["model_choice"] == "beta" and "folds" in st
    for k in ("active", "updated", "n_labelled", "base", "avg_win", "avg_loss", "oos", "weights"): assert k in st                 # dash_data / memebot status keys
    assert brain._migrate("garbage")["active"] is False and brain._migrate({"model_choice": "logit", "logit": {"w": []}})["model_choice"] == "beta"
    assert brain.Brain.__new__(brain.Brain).__class__.signals is brain.signals and brain.Brain(str(tmp_path / "none.json")).playbook["size_mult"] == 1.0



# ---------------------------------------------------------------- 02-nov risk review: regressions
def test_universe_rule_excludes_policy_vetoed_rows_even_when_tagged_policy():
    """the OOS baseline must run on the universe the live gate can trade: token/policy vetoes remove the row whatever veto_class says"""
    assert brain._hard_fails({"fail": ["score<50", "brain_ev<=0", "director_gate", "no_sellability_check"]}) == []
    for f in ("honeypot/high_tax", "st_snipers", "already_pumped_h1", "news_negative", "insider_negative", "no_momentum_m5", "lp_unlocked"):
        assert brain._hard_fails({"fail": [f], "veto_class": {f: "policy"}}) == [f]


def test_training_rows_carry_ctx_and_hour_utc_for_the_director():
    import director
    now = 1_800_000_000.0
    arch = [{"rid": f"M{i}:{i}", "t": now - 3600 * (i + 1), "t_exit": now - 3600 * i, "S": {}, "x": {}, "ret": -0.05, "score": 50, "mint": f"M{i}", "cfg_hash": "h",
             "ctx": {"sol_trend": "down", "btc_on": True, "risk_off": False, "heat": "normal", "hour_utc": 5}} for i in range(12)]
    rows = brain._training_rows(arch, "h", now)
    assert all(r["ctx"]["sol_trend"] == "down" and r["hour_utc"] == 5 for r in rows)
    gate, info = director.regime_from_data(rows, {}, min_n=10, min_rows=12)
    assert "sol_trend" in gate and "down" not in gate["sol_trend"] and "down" in info["closed"]["sol_trend"]   # 12 rows, mean -5 % -> 'down' closed


def test_decide_stores_the_scored_vector_and_the_archive_reuses_it():
    """train/serve skew (02-nov review): the archived x is the vector decide() scored, not a recomputation on the enriched row"""
    b = brain.Brain(); rec = {"score": 50, "liq": 120000, "parts": {"parts": {"buy_press": 6}, "age_h": 5, "vol_liq": 2.1, "h1": 10, "m5": 1, "b_s": "120/80"}, "rug": {"top10": 12.5, "holders": 8000}}
    d = b.decide(rec, 100.0, {"position_pct": 0.05}); assert d is not None and isinstance(rec.get("x_dec"), dict) and rec["x_dec"]["cx"] in (None, {}) or isinstance(rec["x_dec"]["cx"], dict)
    later = dict(rec, st_f={"snipers_pct": 2.0, "holders": 8000}, roundtrip_loss_pct=1.2, ctx={"hour_utc": 3, "sol_trend": "up"})   # fields attached AFTER decide
    assert later["x_dec"] == rec["x_dec"] and brain.xraw(later) != rec["x_dec"]                                        # the enriched row would differ: the archive must take x_dec


def test_local_n_vectorised_matches_the_python_loop():
    keys = ["a", "b", "c", "d"]; rows = [0b0000, 0b0001, 0b0011, 0b0111, 0b1111, 0b1000]
    st = {"keys": keys, "bool_rows": rows}
    for S in ({"a": True}, {"a": True, "b": True, "c": True, "d": True}, {}):
        b = brain._bits(S, keys); ref = max(brain.LOCAL_MIN_N, sum(1 for r in rows if bin(b ^ r).count("1") <= brain.LOCAL_HAMMING))
        assert brain.Brain.local_n(S, st) == ref


def test_training_rows_drop_rows_older_than_the_age_cap():
    now = 1_800_000_000.0
    arch = [{"rid": "M:1", "t": now - 100 * 86400, "S": {}, "x": {}, "ret": 0.1, "score": 50, "mint": "M", "cfg_hash": "h"},
            {"rid": "M:2", "t": now - 10 * 86400, "S": {}, "x": {}, "ret": 0.1, "score": 50, "mint": "M", "cfg_hash": "h"}]
    assert [r["rid"] for r in brain._training_rows(arch, "h", now)] == ["M:2"]


def test_local_n_cache_follows_the_list_object_not_its_id():
    keys = ["a", "b"]; S = {"a": True}
    r1 = [0b01] * 7; r2 = [0b10] * 7                                                     # same length, different content
    n1 = brain.Brain.local_n(S, {"keys": keys, "bool_rows": r1}); n2 = brain.Brain.local_n(S, {"keys": keys, "bool_rows": r2})
    assert n1 == 7 and n2 == 7                                                             # Hamming(01,10)=2 <= 2 -> all 7 count either way
    r3 = [0b11] * 3 + [0b00] * 4; assert brain.Brain.local_n({"a": True, "b": True}, {"keys": keys, "bool_rows": r3}) == 7
    assert brain.Brain.local_n({"a": True, "b": True}, {"keys": keys, "bool_rows": [0b00] * 6}) == 6
