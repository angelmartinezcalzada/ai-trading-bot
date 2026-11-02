"""Brain v2: logistic model (numpy), pessimistic probability, cost-aware EV with the director's floor, model choice by OOS evidence
(v3: the choice is deployed only after two consecutive OOS wins; see test_learn_picks_the_logistic_model_only_when_it_beats_beta_oos)."""
import json, os, math
import pytest
import brain

C = {"min_liquidity_usd": 50000, "min_score": 45, "brain_min_score": 45, "position_pct": 0.05, "max_hold_hours": 3, "exit_mode": "trail", "hard_stop_pct": 6, "trail_pct_tt": 12}


def planted(n, seed=0):
    """'good' on -> win 70 %, off -> win 25 %; score carries a weak extra signal; 30 distinct mints"""
    import random; rng = random.Random(seed); out = []
    for i in range(n):
        on = rng.random() < 0.5; sc = rng.choice([50, 60]) if on else rng.choice([40, 50])
        win = rng.random() < (0.7 if on else 0.25)
        out.append({"t": 1000 * i, "t_exit": 1000 * i + 100, "S": {"good": on, "noise": rng.random() < 0.5}, "ret": 0.06 if win else -0.05, "score": sc, "mint": f"m{i % 30}"})
    return out


def test_logit_fit_learns_the_planted_signal_and_is_calibrated():
    data = planted(400); m = brain.Brain.fit(brain.Brain.__new__(brain.Brain), data)
    assert "logit" in m and "good" in m["logit"]["keys"]
    b = brain.Brain.__new__(brain.Brain); b.st = {**m, "model_choice": "logit"}; b.ctx = {}
    p_on, n = b._p({"good": True, "noise": False}, 55); p_off, _ = b._p({"good": False, "noise": False}, 45)
    assert p_on > 0.55 > 0.4 > p_off and n == 400
    pb_on, nb = b._p_beta({"good": True, "noise": False}); assert pb_on > 0.5 and nb <= 400


def test_pessimistic_probability_and_cost_aware_ev():
    assert brain.Brain.p_low(0.6, 10000) == pytest.approx(0.6, abs=0.01) and brain.Brain.p_low(0.6, 10) < 0.5 and brain.Brain.p_low(0.6, 1) >= 0.01
    b = brain.Brain.__new__(brain.Brain); b.ctx = {}
    b.st = {"base": 0.5, "weights": {"good": {"p_on": 0.9, "p_off": 0.2, "n_on": 200, "n_off": 200}}, "avg_win": 0.06, "avg_loss": 0.05, "n": 400, "active": True}
    rec = {"score": 60, "parts": {"parts": {"buy_press": 6}, "age_h": 2}, "liq": 60000}
    d0 = b.decide(rec, 48.0, dict(C, brain_ev_min=0.01))
    assert d0["p_low"] < d0["p"] and d0["model"] == "beta" and d0["n_eff"] > 0
    d1 = b.decide(rec, 48.0, dict(C, brain_ev_min=0.01, director_fixed_share=0.02))
    assert d1["ev_pct"] == pytest.approx(d0["ev_pct"] - 2.0, abs=0.01)                 # the fixed-cost share comes straight off the EV
    d2 = b.decide(rec, 48.0, dict(C, brain_ev_min=0.5))
    assert d2["ev_ok"] is False and d2["ev_min_pct"] == 50.0                           # the director's floor gates the entry
    assert d0["size"] <= 48.0 * C["position_pct"]                                      # Kelly on p_low, still capped by position_pct


def test_learn_picks_the_logistic_model_only_when_it_beats_beta_oos(tmp_path, monkeypatch):
    """v3 (deliberate change of a v2 internal): the OOS winner is recorded on every refit (oos.winner / oos.models_hist) but the
    deployed model_choice only switches after SWITCH_WINS consecutive refits name the same winner; v2 switched on the first one.
    The winner rule itself is still the v2 rule: beat Beta's policy return (>= 8 trades) AND Beta's Brier, now on every fold."""
    monkeypatch.chdir(tmp_path)
    data = planted(400, seed=3)
    b = brain.Brain.__new__(brain.Brain); b.st = {"active": False, "active_votes": 0}; b.ctx = {}; b.path = str(tmp_path / "brain_state.json")
    monkeypatch.setattr(brain.Brain, "build_dataset", lambda s, cfg, max_fetch=40: data)
    out = brain.Brain.learn(b, dict(C, brain_ev_min=0.01))
    oos = out["oos"]; assert set(oos["models"]) >= {"beta"} and oos["model_choice"] == "beta" and oos["policy"] == "ev>0.01 and score>=45"   # first refit: never a switch
    assert oos["winner"] in ("beta", "logit", "ridge") and oos["models_hist"] == [oos["winner"]] and oos["switched"] is False
    if "logit" in oos["models"]:
        L, B = oos["models"]["logit"], oos["models"]["beta"]
        if oos["winner"] == "logit": assert L["avg_ret_%"] > (B["avg_ret_%"] or -1e9) and L["brier"] <= B["brier"] and L["trades"] >= 8
        elif oos["winner"] == "beta": assert not (L["avg_ret_%"] is not None and L["trades"] >= 8 and (B["avg_ret_%"] is None or L["avg_ret_%"] > B["avg_ret_%"]) and L["brier"] <= B["brier"]
                                                  and all(f["models"]["logit"]["avg_ret_%"] is not None and (f["models"]["beta"]["avg_ret_%"] is None or f["models"]["logit"]["avg_ret_%"] > f["models"]["beta"]["avg_ret_%"]) for f in out["folds"]))
    assert out["calibration"] and all(0 <= c["win_rate"] <= 1 and c["n"] > 0 for c in out["calibration"])
    st = json.load(open(b.path)); assert st["model_choice"] == out["model_choice"] == "beta"
    out2 = brain.Brain.learn(b, dict(C, brain_ev_min=0.01)); w = out2["oos"]["winner"]
    if w != "beta" and out2["oos"]["models_hist"] == [w, w]: assert out2["model_choice"] == w and out2["oos"]["switched"] is True and out2["active"] is False
    else: assert out2["model_choice"] == "beta"
    assert json.load(open(b.path))["model_choice"] == out2["model_choice"] and ("logit" in json.load(open(b.path))) == ("logit" in out2)


def test_learn_without_numpy_falls_back_to_beta(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); monkeypatch.setattr(brain, "np", None)
    data = planted(300, seed=5)
    b = brain.Brain.__new__(brain.Brain); b.st = {"active": False, "active_votes": 0}; b.ctx = {}; b.path = str(tmp_path / "brain_state.json")
    monkeypatch.setattr(brain.Brain, "build_dataset", lambda s, cfg, max_fetch=40: data)
    out = brain.Brain.learn(b, C)
    assert out["model_choice"] == "beta" and "logit" not in out and list(out["oos"]["models"]) == ["beta"]


def test_dataset_keeps_director_gated_rows(tmp_path, monkeypatch):
    """a candidate the Director refused (window / cap / play) is not a veto: it must keep teaching the model"""
    import time, json as _j
    monkeypatch.chdir(tmp_path); now = time.time(); t0 = now - 6 * 3600
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))
    rows = [{"ts": iso(t0), "mint": "G", "pair": "pG", "score": 55, "fail": ["director_gate"], "liq": 60000, "price": 1.0, "parts": {"parts": {"buy_press": 6}, "age_h": 2}},
            {"ts": iso(t0), "mint": "V", "pair": "pV", "score": 55, "fail": ["mint_authority"], "liq": 60000, "price": 1.0, "parts": {"parts": {"buy_press": 6}, "age_h": 2}}]
    open("candidates_solana.jsonl", "w").write("".join(_j.dumps(r) + "\n" for r in rows))
    bars = [[t0 + 60 * i, 1.0, 1.01, 0.5 if i == 199 else 1.0, 1.0] for i in range(200)]
    _j.dump({"pG": {"at": now, "bars": bars}, "pV": {"at": now, "bars": bars}}, open("ohlcv_cache.json", "w"))
    monkeypatch.setattr(brain.time, "sleep", lambda s: None)
    b = brain.Brain.__new__(brain.Brain); b.st = {}; b.ctx = {}
    mints = [d["mint"] for d in brain.Brain.build_dataset(b, C, max_fetch=0)]
    assert mints == ["G"]
