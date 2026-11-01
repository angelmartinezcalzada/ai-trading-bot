"""Tests for dash_data.build_overview (panel v2, DASHBOARD.md section 1) and the /api/overview wiring in dashboard.py.
Offline and fast: everything comes from the synthetic fixture in tests/dash_fixture.py (symbols FIX*, mints 'Fixture…')."""
import os, sys, json, time, shutil, subprocess, importlib.util
import pytest
import dash_data
from tests.dash_fixture import make_fixture, make_empty, MINT1, WALLET

SECTIONS = ("meta", "health", "solana", "insider", "copytrade", "hl", "cex", "activity")
SOL_SUB = ("equity_curve", "daily_pnl", "kpi_30d", "trades", "scan", "funnel", "brain", "eval", "limits")
HDR = ("available", "source", "ts", "age_s", "fresh", "fresh_after_s")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
