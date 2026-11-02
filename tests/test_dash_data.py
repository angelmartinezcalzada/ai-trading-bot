"""Tests for dash_data.build_overview (panel v2, DASHBOARD.md section 1) and the /api/overview wiring in dashboard.py.
Offline and fast: everything comes from the synthetic fixture in tests/dash_fixture.py (symbols FIX*, mints 'Fixture…')."""
import os, sys, json, time, math, shutil, subprocess, importlib.util
import pytest
import dash_data
from tests.dash_fixture import make_fixture, make_empty, MINT1, WALLET

SECTIONS = ("meta", "health", "solana", "insider", "copytrade", "hl", "cex", "activity")
SOL_SUB = ("equity_curve", "daily_pnl", "kpi_30d", "trades", "scan", "funnel", "brain", "eval", "limits")
HDR = ("available", "source", "ts", "age_s", "fresh", "fresh_after_s")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- synthetic files of the v3 modules (context.py, insider_rank.py, brain v3, director v2)
# Clearly labelled fixtures (FixtureRank…, 'fixture'); the layouts follow the schemas documented in DASHBOARD.md section 1b.
def ctx_now(now, **over):
    """a data/context_now.json document as context.py writes it; `over` replaces whole top-level blocks"""
    c = {"ts": now - 600, "code": "context/1", "hour_utc": 13, "dow": 2,
         "sol": {"usd": 171.2, "r1h": 0.4, "r4h": -1.1, "r24h": 3.2, "rv24h": 1.9},
         "btc": {"usd": 101500.0, "r1h": 0.1, "r4h": -0.3, "r24h": -1.0, "rv24h": 0.8, "regime": "range", "regime_age_s": 7200},
         "news": {"risk_off": False, "fng": 42, "sentiment": -0.1, "sources_ok": 4, "age_s": 120},
         "market": {"new_pools_1h": 35, "graduations_1h": 4, "agg_vol_h1_usd": 1250000.0, "n_cands_1h": 12, "heat": "normal", "heat_ratio": 1.1},
         "breadth": {"n_entry": 12, "n_universe": 80, "share": 0.15, "med_atr_ratio": 1.05},
         "hl": {"sol_bias": 0.2, "btc_bias": -0.1, "stress": "low"},
         "health": {"insider_age_s": 30, "st_budget_used": 120, "st_budget_cap": 300, "x_buzz_age_s": 900, "brain_active": False, "director_shadow": True},
         "regime": {"sol_trend": "up", "btc_on": True, "risk_off": False, "heat": "normal"}, "stale": []}
    c.update(over); return c


def write_context(d, now, rows=24, riskoff_last=0, jsonl=True, **over):
    """data/context_now.json (+ data/context.jsonl: one row per hour, newest at now-600; the newest `riskoff_last` rows carry risk_off=True)"""
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    json.dump(ctx_now(now, **over), open(os.path.join(d, "data", "context_now.json"), "w"))
    if not jsonl: return
    with open(os.path.join(d, "data", "context.jsonl"), "w") as f:
        for i in range(rows):
            k = rows - 1 - i; r = ctx_now(now); r["ts"] = now - 600 - k * 3600
            r["sol"]["r1h"] = round(math.sin(i / 3), 3); r["news"]["risk_off"] = k < riskoff_last; r["market"]["new_pools_1h"] = 20 + i
            f.write(json.dumps(r) + "\n")


def rank_addr(i): return f"FixtureRank{i:02d}" + "r" * 20 + f"{i:04d}"      # unique 4…4 short form


def rank_json(now, n=14):
    """an insider_rank.json document (insider_rank.py): n wallets, rel descending with i, tiers elite/good/watch/None, wallet 1 is a bot"""
    ws = {}
    for i in range(n):
        ws[rank_addr(i)] = {"rel": round(0.9 - 0.05 * i, 3), "tier": "elite" if i < 3 else "good" if i < 8 else "watch" if i < 12 else None, "h": 20 - i, "m": 5 + i,
                            "h_eff": 15.5 - i, "m_eff": 4.0 + i, "hr_post": round(0.7 - 0.03 * i, 3), "part": round(0.2 - 0.01 * i, 3), "bot": i == 1, "bot_why": "burst" if i == 1 else None,
                            "early": 0.5, "days": 30 + i, "med_dt": 12.5, "med_dslot": 30.0, "avg_sol": 0.8, "last_hit_t": now - 3600 * i, "last_seen_t": now - 60 * i,
                            "cluster": "c1" if i < 2 else None, "live_n": 10 + i, "live_hit": 6, "live_mean": round(2.5 - 0.2 * i, 2),
                            "pnl": {"realized": 1.2, "unrealized": 0.3, "win_pct": 61.0, "n_tokens": 9, "src": "st"} if i % 2 == 0 else None, "why": f"fixture wallet {i}"}
    return {"t": now - 900, "code": "insider_rank/1", "base_rate": 0.21, "half_life_d": 7, "n_launches": 340, "wallets": ws, "tiers": {"elite": 3, "good": 5, "watch": 4},
            "top": sorted(ws, key=lambda a: -ws[a]["rel"])[:200], "prev_tiers": {}, "discovery": {"t": now - 1800, "n_candidates": 40, "n_added": 2, "note": "fixture"}}


STATUS_V4 = {"rank_t": None, "rank_tiers": {"elite": 3, "good": 5, "watch": 4}, "tracked_by_tier": {"elite": 3, "good": 5, "watch": 4, "none": 2},
             "rotation_slice": [2, 12], "rpc_err_n": 7, "sells_n_by_mint": {"FixtureSellMint1" + "s" * 28: 5, "FixtureSellMint2" + "s" * 28: 2}}


def write_rank(d, now, status_extra=True):
    """insider_rank.json next to insider_status.json (+ the v4 keys inside insider_status.json when it exists)"""
    json.dump(rank_json(now), open(os.path.join(d, "insider_rank.json"), "w"))
    p = os.path.join(d, "insider_status.json")
    if status_extra and os.path.exists(p):
        st = json.load(open(p)); st.update(STATUS_V4, rank_t=now - 900); json.dump(st, open(p, "w"))


def brain_v3(now):
    return {"updated": "2026-11-02T10:00:00", "n_labelled": 900, "n": 900, "active": False, "base": 0.4, "weights": {}, "avg_win": 0.12, "avg_loss": 0.07,
            "code_version": "brain/3", "model_choice": "logit", "lambda": 0.5, "archive_n": 12,
            "folds": [{"n_train": 500, "n_test": 100, "avg_ret_%": 1.2, "brier": 0.21}, {"n_train": 600, "n_test": 100, "avg_ret_%": -0.4, "brier": 0.24},
                      {"n_train": 700, "n_test": 100, "avg_ret_%": 0.8, "brier": 0.22}, {"n_train": 800, "n_test": 100, "brier": 0.23}],
            "oos": {"n_test": 215, "brain_trades": 30, "brain_avg_ret_%": 0.9, "models_hist": ["beta", "beta", "logit", "beta", "beta"]},
            "calibration": [{"bin": "0-20%", "n": 50, "p_avg": 0.12, "win_rate": 0.1}, {"bin": "20-40%", "n": 90, "p_avg": 0.3, "win_rate": 0.28}, {"bin": "40-60%", "n": 40, "p_avg": 0.5, "win_rate": 0.45}]}


DIRECTOR_V2 = {"ts": None, "first_run": None, "shadow": False, "version": 2, "plays": {"scanner": "on", "pump": "off"}, "min_score_eff": 50, "ev_min_eff": 0.012, "windows": list(range(24)),
               "max_trades_day": 8, "size_policy": {"target_usd": 4.0, "fixed_share": 0.004, "fixed_usd": 0.016, "binding": "size_pct", "why": "fixture"},
               "exit_profile": {"hard_stop_pct": 6.0, "trail_pct": 12.0, "why": "fixture"},
               "regime_gate": {"sol_trend": ["down"], "btc_on": [False], "risk_off": [True], "heat": ["cold"], "why": "fixture: cerrado en bajista / BTC off / riesgo-off / frío"},
               "evidence": {"equity": 48.0, "sol_usd": 170.0, "fixed_cost_usd": 0.016, "rent_lost_prob": 0.1, "cost_pct": 0.9, "dataset_rows": 900, "plays": {}, "plays_why": {}, "score_floor_why": "config",
                            "regime": {"sol_trend": {"up": {"n": 40, "exp_pct": 1.2, "pf": 1.3}, "flat": {"n": 30, "exp_pct": 0.1, "pf": 1.0}, "down": {"n": 25, "exp_pct": -2.1, "pf": 0.6}},
                                       "heat": {"hot": {"n": 20, "exp_pct": 0.5, "pf": 1.1}, "cold": {"n": 15, "exp_pct": -1.4, "pf": 0.7}}}}}


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    d = tmp_path_factory.mktemp("dashfix"); now = time.time()
    return str(d), now, make_fixture(str(d), now)


@pytest.fixture(scope="module")
def ov(fx):
    d, now, _ = fx
    return dash_data.build_overview(d, now)


def _hdr_ok(sec):
    return all(k in sec for k in HDR)


# ---------------------------------------------------------------- shape / never raises
def test_all_sections_present_with_fixture(ov, fx):
    _, now, _ = fx
    for s in SECTIONS: assert s in ov and _hdr_ok(ov[s]), s
    for k in SOL_SUB: assert k in ov["solana"] and _hdr_ok(ov["solana"][k]), k
    assert ov["meta"]["now"] == now
    assert ov["solana"]["available"] and ov["solana"]["fresh"] and ov["solana"]["source"] == "status_solana.json"
    assert all(ov["solana"][k]["available"] for k in SOL_SUB), {k: ov["solana"][k].get("error") for k in SOL_SUB}
    assert all(ov[s]["available"] for s in SECTIONS), {s: ov[s].get("error") for s in SECTIONS}
    json.dumps(ov)                      # JSON-safe (no NaN, no objects)


def test_empty_fixture_available_false_no_keyerror(tmp_path):
    make_empty(str(tmp_path)); o = dash_data.build_overview(str(tmp_path))
    for s in SECTIONS: assert s in o and _hdr_ok(o[s]), s
    for s in ("solana", "insider", "copytrade", "hl", "cex", "activity"):
        assert o[s]["available"] is False and o[s]["error"], s
    for k in SOL_SUB:
        assert k in o["solana"] and _hdr_ok(o["solana"][k]), k
        if k != "limits": assert o["solana"][k]["available"] is False and o["solana"][k]["error"], k
    assert o["solana"]["limits"]["available"] and o["solana"]["limits"]["trail_pct"] == 0.1   # config.json exists in the empty fixture
    assert o["meta"]["available"] and "now" in o["meta"] and set(o["meta"]["exchanges"]) == {"solana", "binance", "coinbase"}
    assert o["health"]["available"] and set(o["health"]["exchanges"]) == {"solana", "binance", "coinbase"}
    assert o["solana"]["real_trades_24h"] is None       # trades_solana_live.csv absent -> unknown, not 0
    json.dumps(o)


def test_no_files_at_all(tmp_path):
    o = dash_data.build_overview(str(tmp_path / "nothing_here"))
    assert o["meta"]["available"] is False and "config.json" in o["meta"]["error"]
    assert all(s in o for s in SECTIONS); json.dumps(o)


def test_corrupt_files_never_raise(tmp_path):
    d = str(tmp_path); make_fixture(d, time.time())
    for f, body in (("status_solana.json", "{"), ("insider_status.json", "[1,2"), ("candidates_solana.jsonl", "not json\n{bad\n"),
                    ("equity_solana.csv", "garbage,,\n"), ("trades_solana_paper.csv", ""), ("state/copytrade_paper.json", "null"),
                    ("data/hl_risk.json", "{\"coins\": 5}"), ("eval_solana.json", "[]"), ("config.json", "{\"exchanges\": \"x\"}")):
        open(os.path.join(d, f), "w").write(body)
    o = dash_data.build_overview(d)
    for s in ("solana", "insider", "copytrade"): assert o[s]["available"] is False and o[s]["error"], s
    assert o["solana"]["equity_curve"]["available"] is False and o["solana"]["funnel"]["available"] is False
    assert o["solana"]["daily_pnl"]["available"] is False and o["solana"]["eval"]["available"] is False
    assert o["hl"]["available"] and o["hl"]["risk"]["coins"] == []      # paper + evidence still readable, risk degraded gracefully
    json.dumps(o)


# ---------------------------------------------------------------- freshness
def test_freshness_shift_one_hour(fx, ov):
    d, now, _ = fx; o = dash_data.build_overview(d, now + 3600)
    assert ov["solana"]["fresh"] and ov["insider"]["fresh"] and ov["solana"]["brain"]["fresh"]
    assert o["solana"]["fresh"] is False and o["solana"]["age_s"] > 3600
    assert o["insider"]["fresh"] is False
    assert o["solana"]["brain"]["fresh"] is True and o["solana"]["brain"]["source"] == "data/brain_state.json"
    assert ov["solana"]["brain"]["source"].startswith("status_solana.json")       # fresh status -> brain.model from status
    assert ov["solana"]["brain"]["n_labelled"] == 715 and len(ov["solana"]["brain"]["decisions"]) == 8
    assert ov["solana"]["fresh_after_s"] == 120 and ov["insider"]["fresh_after_s"] == 900 and o["solana"]["brain"]["fresh_after_s"] == 3 * 3600


# ---------------------------------------------------------------- trades-derived
def test_daily_pnl_sums_only_sell_rows(ov, fx):
    _, _, exp = fx; dp = ov["solana"]["daily_pnl"]
    assert len(dp["days"]) == 14 and dp["source"] == "trades_solana_paper.csv"
    by = {x["day"]: x for x in dp["days"]}
    for day, e in exp["daily_pnl"].items():
        assert by[day]["pnl"] == pytest.approx(e["pnl"]) and by[day]["n"] == e["n"] and by[day]["wins"] == e["wins"], day
    assert dp["total_14d"] == pytest.approx(exp["total_14d"])
    assert sum(x["n"] for x in dp["days"]) == 14    # 20 SELL rows in 20 days -> exactly 14 fall in the window (BUY rows never counted)


def test_kpi_30d_profit_factor_and_fees(ov, fx):
    _, _, e = fx; k = ov["solana"]["kpi_30d"]; k2 = e["kpi"]
    assert k["n"] == k2["n"] and k["wins"] == k2["wins"] and k["win_rate"] == 0.5
    assert k["gross_win"] == pytest.approx(k2["gross_win"]) and k["gross_loss"] == pytest.approx(k2["gross_loss"])
    assert k["profit_factor"] == pytest.approx(k2["gross_win"] / k2["gross_loss"], abs=1e-4)
    assert k["fees"] == pytest.approx(k2["fees"])    # fee of EVERY row (BUY and SELL), 40 x 0.05
    assert k["best"]["pnl"] == k2["best_pnl"] and k["worst"]["pnl"] == k2["worst_pnl"] and k["best"]["sym"].startswith("FIX")
    assert k["avg_win"] > 0 and k["avg_loss"] < 0 and k["expectancy"] == pytest.approx((k2["gross_win"] - k2["gross_loss"]) / 20, abs=1e-4)


def test_trades_feed_strips_tx_and_flags_real(ov):
    rows = ov["solana"]["trades"]["rows"]
    assert len(rows) == 40 and rows[0]["time"] >= rows[-1]["time"]            # most recent first
    assert all("tx=" not in r["reason"] and len(r["reason"]) <= 120 for r in rows)
    assert not any(r["is_real"] for r in rows)                                # the paper file has no REAL rows
    assert rows[0]["side"] == "SELL" and isinstance(rows[0]["pnl"], float)


def test_real_trades_24h_in_paper_mode(ov):
    assert ov["solana"]["mode_cfg"] == "paper" and ov["solana"]["real_trades_24h"] == 3


# ---------------------------------------------------------------- equity curve (tail read)
def test_equity_curve_tail_fast_and_correct(fx, ov):
    d, now, exp = fx; e = exp["equity"]
    t0 = time.perf_counter(); ec = dash_data._equity_curve(os.path.join(d, "equity_solana.csv"), now, 300, "equity_solana.csv")
    assert time.perf_counter() - t0 < 0.5
    assert 2 <= len(ec["points_24h"]) <= 300 and len(ec["points_7d"]) <= 300
    assert ec["points_24h"][0][1] == e["first_24h"] and ec["points_24h"][-1][1] == e["last"] and ec["first_24h"] == e["first_24h"]
    assert ec["last"] == e["last"] and ec["min_24h"] == e["min_24h"] and ec["max_24h"] == e["max_24h"]
    assert ec["points_24h"][-1][0] == e["last_ts"] * 1000 and ec["ts"] == e["last_ts"] and ec["fresh"]
    assert 10_000 < ec["n_rows_read"] < e["n_rows_total"] and ec["truncated"]      # tail of 300 KB, never the whole ~23k rows
    assert ov["solana"]["equity_curve"]["last"] == e["last"]
    ms = [p[0] for p in ec["points_24h"]]; assert ms == sorted(ms)


# ---------------------------------------------------------------- scan / funnel
def test_funnel_by_fail_sorted_and_passed(ov, fx):
    _, _, exp = fx; f = ov["solana"]["funnel"]; e = exp["funnel"]
    assert f["rows"] == e["rows"] and f["passed"] == e["passed"]
    assert [(x["reason"], x["n"]) for x in f["by_fail"]] == e["by_fail"]
    assert [x["n"] for x in f["by_fail"]] == sorted((x["n"] for x in f["by_fail"]), reverse=True)
    assert f["last_passed"][0]["sym"] == e["last_passed_sym"] and f["last_passed"][0]["score"] is not None and len(f["last_passed"]) == 5
    assert sum(x["n"] for x in f["by_src"]) == 120 and f["window_from"] < f["window_to"] and f["fresh"]


def test_scan_parses_prefilter_line(ov, fx):
    _, _, exp = fx; sc = ov["solana"]["scan"]; e = exp["scan"]
    for k in ("ok", "total", "eval", "skipped_hardfail", "rc_fetched", "rc_needed", "rc_past_budget", "secs"): assert sc[k] == e[k], k
    assert sc["prefilter_ts"] == pytest.approx(e["prefilter_ts"], abs=1) and sc["last_scan"]["ts"] == pytest.approx(e["last_scan_ts"], abs=1)
    assert "SCAN 420 mints" in sc["last_scan"]["text"] and len(sc["last_scan"]["text"]) <= 160
    assert "LIVE buy FIX1 blocked" in sc["last_buy_block"]["text"] and sc["last_buy_block"]["ts"] == pytest.approx(e["prefilter_ts"] - 600, abs=1)
    assert sc["fresh"] and sc["age_s"] == pytest.approx(100, abs=1.5) and sc["parse_error"] is None


# ---------------------------------------------------------------- positions
def test_positions_trail_level_dist_stop_and_state_fields(ov, fx):
    _, _, exp = fx; pos = ov["solana"]["positions"]; p0, p1 = pos
    assert p0["sym"] == "FIX1" and p0["trailing"] and p0["best"] == exp["pos0"]["best"]
    assert p0["trail_level"] == exp["pos0"]["best"] * (1 - exp["trail_pct"]) and p0["trail_pct"] == exp["trail_pct"]
    assert p0["dist_stop_pct"] == exp["pos0"]["dist_stop_pct"]
    assert p0["dist_trail_pct"] == pytest.approx((p0["mark"] / p0["trail_level"] - 1) * 100, abs=0.01)
    assert p0["mint"] == MINT1 and p0["mint_short"] == "Fixt…1111" and p0["score"] == 61 and not p0["partial"] and not p0["pump"]
    assert p1["sym"] == "FIX2" and p1["trailing"] is False and p1["trail_level"] is None and p1["dist_trail_pct"] is None
    assert p1["sellfail"] == 2 and p1["noroute"] == 1 and p1["rent_usd"] == 0.34 and p1["partial"] and p1["best"] == 0.52 and p1["score"] == 52
    assert ov["solana"]["state"]["ok"] and ov["solana"]["open_pnl"] == 22.0


def test_positions_without_state_file_have_null_trail(tmp_path):
    d = str(tmp_path); now = time.time(); make_fixture(d, now); os.remove(os.path.join(d, "state_solana_paper.json"))
    o = dash_data.build_overview(d, now); p0 = o["solana"]["positions"][0]
    assert p0["best"] is None and p0["trail_level"] is None and p0["dist_trail_pct"] is None and p0["dist_stop_pct"] is not None
    assert p0["sellfail"] == 0 and p0["noroute"] == 0 and p0["score"] == 61    # score parsed from 'meme s61'
    assert o["solana"]["state"]["ok"] is False and "ausente" in o["solana"]["state"]["error"]


# ---------------------------------------------------------------- status-derived scalars
def test_solana_status_fields(ov, fx):
    _, _, exp = fx; s = ov["solana"]
    assert s["day_pnl_usd"] == pytest.approx(exp["day_pnl_usd"]) and s["equity"] == 1012.5 and s["mode"] == "paper"
    assert s["wallet"] == {"addr_short": "Fixt…AAAA", "sol": 0.42, "usd": 70.14, "t": pytest.approx(exp["now"] - 30)}
    assert s["sol_usd"] == 167.0 and s["universe"] == 120 and s["stats"] == {"closed": 12, "win_rate": 0.5, "net_pnl": 3.2}
    assert s["pump_play"]["trades"] == 2 and len(s["signals"]) == 10 and len(s["movers"]) == 10 and len(s["smart_items"]) == 10 and len(s["ai_pump"]) == 6
    assert s["limits"]["max_positions"] == 8 and s["limits"]["exit_mode"] == "trail" and s["limits"]["pump_play"] is False
    assert s["eval"]["data"]["tokens"] == 10 and s["brain"]["oos"]["brain_avg_ret_%"] == 1.8
    assert WALLET not in json.dumps(ov)          # full wallet address never leaves the machine; only 4…4


# ---------------------------------------------------------------- activity
def test_activity_classification_and_tx_removed(ov):
    items = ov["activity"]["items"]; assert ov["activity"]["available"] and 0 < len(items) <= 80
    kind = lambda needle: next(i["kind"] for i in items if needle in i["msg"])
    assert kind("KILL SWITCH") == "risk" and kind("SCAM block") == "scam" and kind("Traceback") == "error"
    assert kind("TRADE") == "trade" and kind("SCAN 420") == "scan" and kind("aborted") == "skip"
    assert all("tx=" not in i["msg"] and len(i["msg"]) <= 240 for i in items) and "FixtureSig" not in json.dumps(items)
    assert [i["t"] for i in items] == sorted((i["t"] for i in items), reverse=True)
    assert {i["ex"] for i in items} == {"solana", "binance"} and ov["activity"]["fresh"]


# ---------------------------------------------------------------- insider / copytrade / hl / cex
def test_insider_section(ov, fx):
    _, _, exp = fx; ins = ov["insider"]; e = exp["insider"]
    assert ins["tracked"] == e["tracked"] and ins["cycle_s"] == 42.5 and ins["live_ranked"] == 37 and ins["counts"]["smart_buy"] == 16
    assert len(ins["alerts"]) == e["alerts_n"] and ins["alerts"][0]["elite"] == e["first_alert_elite"] and ins["alerts"][0]["t"] > ins["alerts"][1]["t"]
    assert len(ins["conv"]) == e["conv_n"] and ins["conv"][0]["score"] == e["top_conv_score"] and [c["score"] for c in ins["conv"]] == [9, 7, 5, 3, 2]
    assert len(ins["feed"]) == e["feed_n"] and ins["feed"][0]["w_short"] == "Fixt…AAAA" and "…" in ins["feed"][0]["mint_short"]
    assert WALLET not in json.dumps(ins)


def test_copytrade_win_rate(ov, fx):
    _, _, exp = fx; c = ov["copytrade"]; e = exp["copytrade"]
    assert c["mode"] == "paper" and c["closed"] == e["closed"] and c["wins"] == e["wins"] and c["win_rate"] == pytest.approx(e["win_rate"], abs=1e-4)
    assert len(c["open"]) == e["open_n"] and c["open"][0]["sym"] == "FIXC1" and c["open"][0]["rug_n"] == 1
    assert len(c["recent"]) == 13 and c["recent"][0]["side"] == "BUY" and c["recent"][0]["symbol"] == "FIXC1" and c["fresh"]


def test_hl_risk_sorted_by_flags(ov, fx):
    _, _, exp = fx; hl = ov["hl"]
    assert [c["coin"] for c in hl["risk"]["coins"]] == exp["hl_risk_order"] and hl["risk"]["coins"][0]["n_flags"] == 3 and hl["risk"]["status"] == "ok"
    assert hl["risk"]["coins"][0]["size_mult"] == 0.5 and hl["fresh"] and hl["fresh_after_s"] == 2 * 3600
    assert hl["paper"]["deployment_id"] == "dep_fixture0001" and hl["paper"]["url"].startswith("https://") and len(hl["paper"]["go_live_criteria"]) == 2
    assert hl["evidence"]["oos"]["sharpe"] == 1.15 and hl["evidence"]["full"]["quarters_positive"] == "6 of 10" and hl["evidence"]["honest_summary"].startswith("Fixture")
    assert len(hl["context_tail"]) == 10 and hl["context_tail"][0]["coin"] in ("BTC", "ETH", "SOL") and hl["context_tail"][0]["time"] > hl["context_tail"][-1]["time"]


def test_cex_section(ov):
    cex = ov["cex"]; b, c = cex["exchanges"]["binance"], cex["exchanges"]["coinbase"]
    assert cex["available"] and b["available"] and b["fresh"] and b["mode"] == "paper" and b["equity"] == 998.1 and b["no_cash"] is False
    assert 0 < len(b["equity_curve"]["points_24h"]) <= 200 and b["equity_curve"]["available"]
    assert b["points_24h"] == b["equity_curve"]["points_24h"] and c["points_24h"] == []      # contract: points_24h directly on the exchange
    assert len(b["trades"]["rows"]) == 5 and b["trades"]["file"] == "trades_binance_paper.csv" and b["positions"][0]["sym"] == "FIXUSDT"
    assert len(b["regime"]) <= 8 and b["fng"] == 55 and b["stats"]["win_rate"] == 40.0
    assert c["available"] and c["fresh"] is False and c["age_s"] > 120 and c["mode"] == "live" and c["no_cash"] is True
    assert c["trades"]["available"] is False and c["equity_curve"]["available"] is False     # coinbase has no csv files in the fixture


# ---------------------------------------------------------------- meta / health
def test_meta_and_health(ov, fx):
    _, now, _ = fx; m, h = ov["meta"], ov["health"]
    assert m["now"] == now and m["host"] and m["tunnel_url"] == "https://fixture-tunnel.invalid" and m["stop_all"] is False
    assert m["exchanges"] == {"solana": {"mode": "paper", "enabled": True}, "binance": {"mode": "paper", "enabled": True}, "coinbase": {"mode": "live", "enabled": True}}
    assert m["fresh_after"]["status"] == 120
    for ex in ("solana", "binance", "coinbase"):
        e = h["exchanges"][ex]; assert e["health"] in ("ok", "arrancando", "caído", "parado") and isinstance(e["pids"], list)
        assert e["stopped"] is False and e["killed"] is False
    assert h["exchanges"]["solana"]["paused"] is False and len(h["supervisor_tail"]) == 12 and h["available"] and h["fresh"]
    assert "insider_pid" in h and "dashboard_pid" in h


def test_pgrep_missing_or_slow_never_raises(monkeypatch):
    def boom(*a, **k): raise FileNotFoundError("pgrep")
    monkeypatch.setattr(dash_data.subprocess, "run", boom); assert dash_data._pgrep("python3 bot.py --exchange solana") == []
    def slow(*a, **k): raise subprocess.TimeoutExpired("pgrep", 3)
    monkeypatch.setattr(dash_data.subprocess, "run", slow); assert dash_data._pgrep("x") == []
    monkeypatch.setattr(dash_data.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="12 34\n", stderr=""))
    assert dash_data._pgrep("x") == [12, 34]


def test_health_rule_matches_api_state(tmp_path, monkeypatch):
    d = str(tmp_path); now = time.time(); make_fixture(d, now)
    monkeypatch.setattr(dash_data, "_pgrep", lambda pat, timeout=3.0: [4242] if "solana" in pat else [])
    o = dash_data.build_overview(d, now); h = o["health"]["exchanges"]
    assert h["solana"]["health"] == "ok" and h["solana"]["pids"] == [4242]          # pid + status younger than 120 s
    assert h["binance"]["health"] == "caído"                                           # no pid
    open(os.path.join(d, "STOP_binance"), "w").close(); open(os.path.join(d, "KILL_solana"), "w").close()
    h = dash_data.build_overview(d, now + 300)["health"]["exchanges"]
    assert h["binance"]["health"] == "parado" and h["binance"]["stopped"] and h["solana"]["health"] == "arrancando" and h["solana"]["killed"]


# ---------------------------------------------------------------- Flask wiring
def test_api_overview_through_flask(tmp_path, monkeypatch):
    d = str(tmp_path); now = time.time(); make_fixture(d, now)
    for f in ("dashboard.py", "dash_data.py", "live_view.py"): shutil.copy(os.path.join(ROOT, f), os.path.join(d, f))
    monkeypatch.chdir(d); monkeypatch.syspath_prepend(d)
    for m in ("live_view",): monkeypatch.delitem(sys.modules, m, raising=False)
    spec = importlib.util.spec_from_file_location("dashboard_under_test", os.path.join(d, "dashboard.py")); mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                      # D = tmp dir: reads its dashboard_password.txt ("fixture"), writes its .flask_secret
    assert os.path.exists(os.path.join(d, ".flask_secret"))
    app = mod.app; app.config["TESTING"] = True; c = app.test_client()
    r = c.get("/api/overview"); assert r.status_code == 401 and r.get_json() == {"error": "auth"}
    assert c.get("/").status_code == 302                                              # no session -> /login
    assert c.post("/login", data={"pw": "wrong"}).status_code == 200 and c.get("/api/overview").status_code == 401
    r = c.post("/login", data={"pw": "fixture"}); assert r.status_code == 302
    r = c.get("/api/overview"); assert r.status_code == 200
    j = r.get_json(); assert "now" in j["meta"] and j["solana"]["available"] and j["solana"]["positions"][0]["sym"] == "FIX1"
    assert all(s in j for s in SECTIONS)
    secret = open(os.path.join(d, ".flask_secret")).read().strip(); body = r.get_data(as_text=True)
    assert secret not in body and WALLET not in body
    # GET / : dashboard_v2.html missing -> old redirect to /live; present -> served with {{csrf}} substituted; /v1 -> /live
    r = c.get("/"); assert r.status_code == 302 and r.headers["Location"].endswith("/live")
    open(os.path.join(d, "dashboard_v2.html"), "w", encoding="utf-8").write("<!doctype html><html lang=es><body>csrf={{csrf}}</body></html>")
    r = c.get("/"); html = r.get_data(as_text=True)
    assert r.status_code == 200 and "{{csrf}}" not in html and "csrf=" in html and r.mimetype == "text/html"
    with c.session_transaction() as s: csrf = s["csrf"]
    assert f"csrf={csrf}" in html
    r = c.get("/v1"); assert r.status_code == 302 and r.headers["Location"].endswith("/live")
    assert c.get("/api/state").status_code == 200 and c.get("/api/activity").status_code == 200    # existing routes still work
    assert c.post("/api/action", json={"action": "pause", "ex": "solana"}).status_code == 403     # CSRF still enforced
    r = c.post("/api/action", json={"action": "pause", "ex": "solana"}, headers={"X-CSRF": csrf}); assert r.status_code == 200 and r.get_json()["ok"]
    assert mod.ACT is dash_data.ACT


def test_trend_section(ov, fx):
    t = ov["trend"]; assert t["available"] and t["pnl"] == 12.0 and len(t["positions"]) == 1 and t["positions"][0]["sym"] == "FIXJ"
    assert t["signals"][0]["entry"] is True and t["signals"][0]["sym"] == "FIXJ" and t["last_eval_day"] == "2026-10-31"


# ---------------------------------------------------------------- v3 modules: context (context.py)
def test_context_section_present_and_typed(tmp_path):
    d = str(tmp_path); now = time.time(); make_empty(d); write_context(d, now)
    c = dash_data.build_overview(d, now)["context"]
    assert c["available"] and c["fresh"] and c["source"] == "data/context_now.json" and c["fresh_after_s"] == 7200 and c["age_s"] == pytest.approx(600, abs=1)
    assert c["code"] == "context/1" and c["hour_utc"] == 13 and c["dow"] == 2
    assert c["sol"] == {"usd": 171.2, "r1h": 0.4, "r4h": -1.1, "r24h": 3.2, "rv24h": 1.9} and c["btc"]["regime"] == "range" and c["btc"]["regime_age_s"] == 7200
    assert c["news"] == {"risk_off": False, "fng": 42, "sentiment": -0.1, "sources_ok": 4, "age_s": 120}
    assert c["market"] == {"new_pools_1h": 35, "graduations_1h": 4, "agg_vol_h1_usd": 1250000.0, "n_cands_1h": 12, "heat": "normal", "heat_ratio": 1.1}
    assert c["breadth"] == {"n_entry": 12, "n_universe": 80, "share": 0.15, "med_atr_ratio": 1.05} and c["hl"] == {"sol_bias": 0.2, "btc_bias": -0.1, "stress": "low"}
    assert c["health"]["brain_active"] is False and c["health"]["director_shadow"] is True and c["health"]["st_budget_cap"] == 300
    assert c["regime"] == {"sol_trend": "up", "btc_on": True, "risk_off": False, "heat": "normal"} and c["stale"] == []
    hist = c["history"]; assert len(hist) == 24 and [x["ts"] for x in hist] == sorted(x["ts"] for x in hist) and hist[-1]["ts"] == pytest.approx(now - 600, abs=1)
    assert all(isinstance(x["r1h"], float) for x in hist) and c["history_error"] is None and c["riskoff_6h"] == 0 and c["riskoff_6h_n"] == 6
    json.dumps(c)


def test_context_stale_missing_malformed_nothing_invented(tmp_path):
    d = str(tmp_path); now = time.time(); make_empty(d); write_context(d, now)
    c = dash_data.build_overview(d, now + 3 * 3600)["context"]; assert c["available"] and c["fresh"] is False and c["age_s"] > 7200 and c["sol"]["r24h"] == 3.2
    # unknown / foreign values never become a pass: a string bool, an enum outside its domain, a non-list stale
    write_context(d, now, news={"risk_off": "yes", "fng": None}, market={"heat": "lava", "new_pools_1h": "many"}, regime={"btc_on": 1, "sol_trend": "UP"}, breadth={}, stale="x")
    c = dash_data.build_overview(d, now)["context"]
    assert c["news"]["risk_off"] is None and c["news"]["fng"] is None and c["market"]["heat"] is None and c["market"]["new_pools_1h"] is None
    assert c["regime"]["btc_on"] is None and c["regime"]["sol_trend"] is None and c["stale"] == [] and c["breadth"]["n_entry"] is None
    for body in ("{", "[]", "", "null"):
        open(os.path.join(d, "data", "context_now.json"), "w").write(body)
        c = dash_data.build_overview(d, now)["context"]; assert c["available"] is False and c["error"] and "history" not in c, body
    os.remove(os.path.join(d, "data", "context_now.json"))
    c = dash_data.build_overview(d, now)["context"]; assert c["available"] is False and c["error"] == "fichero ausente" and c["fresh_after_s"] == 7200
    assert dash_data.build_overview(str(tmp_path / "nothing"))["context"]["available"] is False


def test_context_history_riskoff_window_and_missing_jsonl(tmp_path):
    d = str(tmp_path); now = time.time(); make_empty(d)
    write_context(d, now, rows=24, riskoff_last=6); c = dash_data.build_overview(d, now)["context"]
    assert c["riskoff_6h"] == 6 and c["riskoff_6h_n"] == 6 and sum(1 for x in c["history"] if x["risk_off"]) == 6
    write_context(d, now, rows=24, riskoff_last=3); c = dash_data.build_overview(d, now)["context"]; assert c["riskoff_6h"] == 3 and c["riskoff_6h_n"] == 6
    write_context(d, now, rows=3, riskoff_last=3); c = dash_data.build_overview(d, now)["context"]; assert c["riskoff_6h"] == 3 and c["riskoff_6h_n"] == 3 and len(c["history"]) == 3
    # rows older than 7 h are not bridged into the 6-row window; garbage lines are skipped; more than 24 rows -> the newest 24
    with open(os.path.join(d, "data", "context.jsonl"), "w") as f:
        f.write("not json\n[1,2]\n" + json.dumps({"ts": now - 10 * 3600, "news": {"risk_off": True}}) + "\n")
    c = dash_data.build_overview(d, now)["context"]; assert len(c["history"]) == 1 and c["riskoff_6h"] is None and c["riskoff_6h_n"] == 0
    write_context(d, now, rows=40); c = dash_data.build_overview(d, now)["context"]; assert len(c["history"]) == 24 and c["history"][0]["ts"] == pytest.approx(now - 600 - 23 * 3600, abs=1)
    os.remove(os.path.join(d, "data", "context.jsonl")); write_context(d, now, jsonl=False); c = dash_data.build_overview(d, now)["context"]
    assert c["available"] and c["history"] == [] and c["history_error"] == "data/context.jsonl ausente" and c["riskoff_6h"] is None and c["riskoff_6h_n"] == 0


# ---------------------------------------------------------------- v3 modules: insider rank (insider_rank.py) + status v4 keys
def test_insider_rank_wallets_top10_and_status_keys(tmp_path):
    d = str(tmp_path); now = time.time(); make_fixture(d, now); write_rank(d, now)
    ins = dash_data.build_overview(d, now)["insider"]; rk = ins["rank"]; W = ins["wallets"]
    assert ins["available"] and rk["available"] and rk["fresh"] and rk["source"] == "insider_rank.json" and rk["fresh_after_s"] == 7200 and rk["age_s"] == pytest.approx(900, abs=1)
    assert rk["code"] == "insider_rank/1" and rk["base_rate"] == 0.21 and rk["half_life_d"] == 7 and rk["n_launches"] == 340 and rk["n_wallets"] == 14 and rk["n_bots"] == 1
    assert rk["tiers"] == {"elite": 3, "good": 5, "watch": 4} and rk["discovery"]["n_added"] == 2 and "wallets" not in rk
    assert len(W) == 10 and [w["rel"] for w in W] == sorted((w["rel"] for w in W), reverse=True) and W[0]["rel"] == 0.9
    assert W[0]["addr_short"] == "Fixt…0000" and W[1]["addr_short"] == "Fixt…0001" and W[0]["tier"] == "elite" and W[9]["tier"] == "watch"
    assert W[1]["bot"] is True and W[1]["bot_why"] == "burst" and W[0]["bot"] is False and W[0]["h"] == 20 and W[0]["m"] == 5 and W[0]["part"] == 0.2
    assert W[0]["live_n"] == 10 and W[0]["live_hit"] == 6 and W[0]["live_mean"] == 2.5 and W[0]["pnl_win_pct"] == 61.0 and W[1]["pnl_win_pct"] is None
    assert W[0]["cluster"] == "c1" and W[0]["why"] == "fixture wallet 0" and W[0]["days"] == 30
    assert ins["rank_t"] == pytest.approx(now - 900, abs=1) and ins["rank_tiers"] == {"elite": 3, "good": 5, "watch": 4} and ins["tracked_by_tier"]["none"] == 2
    assert ins["rotation_slice"] == [2, 12] and ins["rpc_err_n"] == 7 and ins["sells_n_total"] == 7 and ins["sells_n_by_mint"][0] == {"mint_short": "Fixt…ssss", "n": 5}
    body = json.dumps(ins); assert "FixtureRank00" not in body and "FixtureSellMint1" not in body     # only 4…4 forms leave the machine
    assert WALLET not in body


def test_insider_rank_stale_missing_malformed(tmp_path):
    d = str(tmp_path); now = time.time(); make_fixture(d, now); write_rank(d, now)
    ins = dash_data.build_overview(d, now + 3 * 3600)["insider"]; assert ins["rank"]["available"] and ins["rank"]["fresh"] is False and len(ins["wallets"]) == 10
    for body in ("{", "[]", "null", json.dumps({"t": now, "wallets": "x", "tiers": 3})):
        open(os.path.join(d, "insider_rank.json"), "w").write(body)
        ins = dash_data.build_overview(d, now)["insider"]
        if body.startswith('{"t"'): assert ins["rank"]["available"] and ins["wallets"] == [] and ins["rank"]["tiers"] == {"elite": 0, "good": 0, "watch": 0} and ins["rank"]["n_wallets"] == 0
        else: assert ins["rank"]["available"] is False and ins["rank"]["error"] and ins["wallets"] == [], body
        assert ins["available"] and ins["tracked"] == 150            # the status part of the section is untouched by a bad rank file
    os.remove(os.path.join(d, "insider_rank.json"))
    ins = dash_data.build_overview(d, now)["insider"]
    assert ins["rank"]["available"] is False and ins["rank"]["error"] == "fichero ausente" and ins["wallets"] == [] and ins["rank"]["fresh_after_s"] == 7200
    # status without the v4 keys (the fixture as shipped): nulls / empties, never a number
    st = json.load(open(os.path.join(d, "insider_status.json"))); [st.pop(k, None) for k in list(STATUS_V4) + ["rank_t"]]; json.dump(st, open(os.path.join(d, "insider_status.json"), "w"))
    ov0 = dash_data.build_overview(d, now)["insider"]
    assert ov0["rank_t"] is None and ov0["rank_tiers"] == {} and ov0["tracked_by_tier"] == {} and ov0["rotation_slice"] is None and ov0["rpc_err_n"] is None and ov0["sells_n_by_mint"] is None
    json.dumps(ov0)


# ---------------------------------------------------------------- v3 modules: brain v3 fields + director v2 fields
def test_brain_v3_fields_and_code_age(tmp_path):
    d = str(tmp_path); now = time.time(); make_empty(d); os.makedirs(os.path.join(d, "data"))
    json.dump(brain_v3(now), open(os.path.join(d, "data", "brain_state.json"), "w"))
    b = dash_data.build_overview(d, now)["solana"]["brain"]
    assert b["available"] and b["model_choice"] == "logit" and b["code_version"] == "brain/3" and b["lambda"] == 0.5 and b["archive_n"] == 12
    assert b["folds_n"] == 4 and b["folds_pos"] == 2 and b["folds_mean_ret"] == pytest.approx((1.2 - 0.4 + 0.8) / 3, abs=1e-3) and len(b["folds"]) == 4
    assert b["models_hist_n"] == 5 and b["models_hist_flips"] == 2 and b["models_hist_last"] == "beta"
    assert len(b["calibration"]) == 3 and b["calibration"][1] == {"bin": "20-40%", "n": 90, "p_avg": 0.3, "win_rate": 0.28}
    assert b["updated_ts"] == dash_data._iso_ts("2026-11-02T10:00:00") and b["code_mtime"] is None and b["code_newer_s"] is None     # no brain.py in the test root
    open(os.path.join(d, "brain.py"), "w").write("# fixture\n"); os.utime(os.path.join(d, "brain.py"), (b["updated_ts"] + 3 * 86400, b["updated_ts"] + 3 * 86400))
    b = dash_data.build_overview(d, now)["solana"]["brain"]; assert b["code_newer_s"] == pytest.approx(3 * 86400, abs=2)
    # malformed v3 fields: nulls, never a crash or an invented number
    st = brain_v3(now); st.update(folds="x", lambda_="y", calibration={"a": 1}, model_choice=5); st["oos"]["models_hist"] = {"beta": 1}; st["lambda"] = "nan"
    json.dump(st, open(os.path.join(d, "data", "brain_state.json"), "w")); b = dash_data.build_overview(d, now)["solana"]["brain"]
    assert b["available"] and b["folds_n"] is None and b["folds"] is None and b["lambda"] is None and b["calibration"] is None and b["models_hist_n"] is None and b["model_choice"] == "5"
    json.dumps(b)


def test_brain_v2_state_leaves_v3_fields_null(ov):
    b = ov["solana"]["brain"]
    assert b["model_choice"] is None and b["code_version"] is None and b["lambda"] is None and b["archive_n"] is None and b["folds_n"] is None
    assert b["models_hist_n"] is None and b["models_hist_flips"] is None and b["calibration"] is None and b["code_newer_s"] is None


def test_director_v2_regime_gate_and_table(tmp_path, ov):
    assert ov["director"]["version"] == 1 and ov["director"]["regime_gate"] is None and ov["director"]["regime_gate_n"] == 0 and ov["director"]["regime_table"] is None
    d = str(tmp_path); now = time.time(); make_empty(d); st = dict(DIRECTOR_V2, ts=now - 300, first_run=now - 90000)
    json.dump(st, open(os.path.join(d, "director_state.json"), "w"))
    D = dash_data.build_overview(d, now)["director"]
    assert D["available"] and D["version"] == 2 and D["regime_gate"] == DIRECTOR_V2["regime_gate"] and D["regime_gate_n"] == 5
    assert D["regime_table"]["sol_trend"]["down"] == {"n": 25, "exp_pct": -2.1, "pf": 0.6} and set(D["regime_table"]) == {"sol_trend", "heat"}
    assert D["shadow"] is False and D["plays"] == {"scanner": "on", "pump": "off"}
    st["regime_gate"] = {"k" + str(i): list(range(40)) for i in range(30)}; st["evidence"]["regime"] = [{"deep": {"deeper": {"deepest": {"x": 1}}}}] * 40
    json.dump(st, open(os.path.join(d, "director_state.json"), "w")); D = dash_data.build_overview(d, now)["director"]
    assert len(D["regime_gate"]) == 12 and len(D["regime_gate"]["k0"]) == 12 and len(D["regime_table"]) == 16 and isinstance(D["regime_table"][0]["deep"]["deeper"], str)   # bounded
    st["regime_gate"] = "closed"; st["evidence"]["regime"] = 7; json.dump(st, open(os.path.join(d, "director_state.json"), "w"))
    D = dash_data.build_overview(d, now)["director"]; assert D["regime_gate"] is None and D["regime_table"] is None and D["available"]


def test_new_fresh_thresholds_and_html_sections(ov):
    assert dash_data.FRESH["context"] == 7200 and dash_data.FRESH["insider_rank"] == 7200 and ov["meta"]["fresh_after"]["context"] == 7200
    assert ov["context"]["available"] is False and ov["insider"]["rank"]["available"] is False and ov["insider"]["wallets"] == []   # the base fixture ships neither file
    html = open(os.path.join(ROOT, "dashboard_v2.html"), encoding="utf-8").read()
    for needle in ('id="context"', "renderContext", "Contexto de mercado", "cx-body", "ins.wallets", "regime_gate", "models_hist_flips", "code_version"):
        assert needle in html, needle
    assert "http://" not in html.replace("http://127.0.0.1", "").replace("https?:", "") and "<script src" not in html and "<link" not in html    # no external resources
