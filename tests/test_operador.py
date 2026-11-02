"""operator.py: the automatic hourly review on the synthetic fixture (never real data), its gated actions and its writings."""
import json, os, time
import pytest
import dash_data, operador as op
from tests.dash_fixture import make_fixture, make_empty


@pytest.fixture
def root(tmp_path):
    now = time.time(); make_fixture(str(tmp_path), now); return str(tmp_path), now


def test_review_finds_down_processes_errors_and_director_shadow(root):
    d, now = root; ov = dash_data.build_overview(d, now); cfg = json.load(open(os.path.join(d, "config.json")))
    F, S = op.review(ov, cfg, now); codes = {f["code"]: f["level"] for f in F}
    assert codes.get("solana_down") == "crit" and codes.get("binance_down") == "crit"      # no pids in the test container
    assert codes.get("errors_1h") == "warn" and codes.get("director_shadow") == "info"
    assert S["legs"] and "Solana papel" in S["legs"][-1] and S["today"]["n"] >= 0 and "candidatos" in S["funnel"]


def test_review_on_empty_root_is_informative_not_crashing(tmp_path):
    make_empty(str(tmp_path)); now = time.time(); ov = dash_data.build_overview(str(tmp_path), now)
    F, S = op.review(ov, json.load(open(tmp_path / "config.json")), now)
    assert any(f["code"] == "director_missing" for f in F) and S["scan"] == "sin línea de escaneo"


def test_actions_are_gated_and_dry_run_touches_nothing(root, monkeypatch):
    d, now = root; ov = dash_data.build_overview(d, now); cfg = json.load(open(os.path.join(d, "config.json")))
    F, _ = op.review(ov, cfg, now)
    big = os.path.join(d, "bot_binance.log"); open(big, "wb").write(b"x" * (op.LOG_ROTATE_BYTES + 10))
    A = op.act(d, ov, F, cfg, {}, now, dry_run=True)
    acts = {a["action"] for a in A}
    assert "rotate_logs" in acts and all(a["dry_run"] for a in A) and os.path.getsize(big) == op.LOG_ROTATE_BYTES + 10
    assert "close_atas" not in acts                                                        # fixture is paper mode: never touches a wallet
    assert "restart_hung" not in acts                                                      # down (no pids) is not hung
    A = op.act(d, ov, F, cfg, {}, now, dry_run=False)
    assert os.path.getsize(big) == op.LOG_KEEP_BYTES and any(a["action"] == "rotate_logs" for a in A)


def test_restart_hung_once_per_hour_and_never_when_stopped(root, monkeypatch):
    d, now = root; cfg = json.load(open(os.path.join(d, "config.json")))
    ov = {"health": {"available": True, "exchanges": {"solana": {"pids": [4242], "status_age_s": 1200, "stopped": False}}}, "solana": {"available": False}, "director": {"available": True, "age_s": 10}}
    killed = []; monkeypatch.setattr(op.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    F = [{"level": "warn", "code": "solana_hung", "msg": "x"}]; st = {}
    A = op.act(d, ov, F, cfg, st, now); assert killed == [(4242, op.signal.SIGTERM)] and st["last_restart"]["solana"] == now
    A = op.act(d, ov, F, cfg, st, now + 600); assert not any(a["action"] == "restart_hung" for a in A)   # within the hour: no
    ov["health"]["exchanges"]["solana"]["stopped"] = True; st = {}
    A = op.act(d, ov, F, cfg, st, now); assert not any(a["action"] == "restart_hung" for a in A)         # STOP_solana: never


def test_close_atas_only_live_with_wallet_and_every_6h(root, monkeypatch):
    d, now = root; cfg = json.load(open(os.path.join(d, "config.json"))); cfg["exchanges"]["solana"]["ata_autoclose"] = True
    ov = {"health": {"available": True, "exchanges": {}}, "solana": {"available": True, "mode": "live", "positions": [{"mint": "HELD"}]}, "director": {"available": True, "age_s": 10}}
    calls = []
    import types, sys
    m = types.ModuleType("live_sol"); m.close_empty_atas = lambda dry_run, skip: (calls.append((dry_run, set(skip))) or {"closed": 2, "found": 3, "sol_recovered": 0.004, "failed": [("M", "x")], "mints": ["A", "B", "M"], "dry_run": dry_run})
    monkeypatch.setitem(sys.modules, "live_sol", m)
    st = {}; A = op.act(d, ov, [], cfg, st, now)                                               # no wallet file: skipped
    assert not any(a["action"].startswith("close_atas") for a in A)
    open(os.path.join(d, "solana_wallet.json"), "w").write("[]")
    A = op.act(d, ov, [], cfg, st, now)
    assert calls == [(False, {"HELD"})] and st["last_ata"] == now and os.path.exists(os.path.join(d, "research", "ata_close.jsonl"))
    A = op.act(d, ov, [], cfg, st, now + 3600); assert len(calls) == 1                           # 6 h cadence
    ov["solana"]["mode"] = "paper"; st = {}; A = op.act(d, ov, [], cfg, st, now); assert len(calls) == 1   # paper: never


def test_run_once_writes_decisions_state_log_and_alerts(root):
    d, now = root
    r = op.run_once(d, now=now)
    assert "revisión horaria" in r["text"] and "(operador automático)" in r["text"] and "- Salud:" in r["text"] and "- Acciones:" in r["text"]
    txt = open(os.path.join(d, op.DIARY), encoding="utf-8").read(); assert "(operador automático)" in txt
    st = json.load(open(os.path.join(d, op.STATE))); assert st["ts"] == now and st["findings"] and "solana_down" in st["alerted_now"]
    al = [json.loads(l) for l in open(os.path.join(d, op.ALERTS))]; assert any(a["code"] == "solana_down" for a in al)
    r2 = op.run_once(d, now=now + 60); assert "solana_down" not in r2["alerted"]              # deduped for 6 h
    r3 = op.run_once(d, now=now + 120, force_daily=True)
    assert r3["daily"] and "informe diario" in r3["text"] and "Decisiones que siguen siendo de Àngel" in r3["text"]
    assert json.load(open(os.path.join(d, op.STATE)))["last_daily"] == op._tz_now(now + 120)[0].strftime("%Y-%m-%d")


def test_dry_run_writes_nothing(root):
    d, now = root; before = os.path.exists(os.path.join(d, op.DIARY)); st0 = open(os.path.join(d, op.STATE)).read()   # the fixture ships a state file
    r = op.run_once(d, now=now, dry_run=True)
    assert r["findings"] and os.path.exists(os.path.join(d, op.DIARY)) == before and open(os.path.join(d, op.STATE)).read() == st0
    assert not os.path.exists(os.path.join(d, op.LOGF))


def test_overview_exposes_operator_section(root):
    d, now = root; ov = dash_data.build_overview(d, now); o = ov["operator"]
    assert o["available"] and o["worst"] == "warn" and len(o["findings"]) == 2 and o["actions"][0]["action"] == "rotate_logs" and o["alerts"][0]["code"] == "errors_1h"


def test_review_with_brain_file_but_no_status_does_not_crash(tmp_path):
    """fresh machine: data/brain_state.json ships with the repo while status_solana.json does not exist yet"""
    make_empty(str(tmp_path)); os.makedirs(tmp_path / "data", exist_ok=True)
    json.dump({"updated": "2026-11-01T10:00:00", "n_labelled": 10, "active": False, "oos": {}, "base": 0.4, "weights": {}, "avg_win": 0.1, "avg_loss": 0.05, "n": 10}, open(tmp_path / "data" / "brain_state.json", "w"))
    now = time.time(); ov = dash_data.build_overview(str(tmp_path), now)
    assert ov["solana"]["brain"]["available"] and not ov["solana"]["available"]
    F, S = op.review(ov, json.load(open(tmp_path / "config.json")), now)
    assert "sombra" in S["brain"] and any(f["code"] == "solana_down" or f["code"] == "director_missing" for f in F)


# ---------------------------------------------------------------- v3: market context, insider rank and brain/code findings
from tests.test_dash_data import write_context, write_rank, brain_v3


def test_review_context_findings_and_market_summary(tmp_path):
    d = str(tmp_path); now = time.time(); make_empty(d); cfg = json.load(open(tmp_path / "config.json")); codes = lambda F: {f["code"]: f["level"] for f in F}
    F, S = op.review(dash_data.build_overview(d, now), cfg, now); c = codes(F)
    assert c.get("context_stale") == "warn" and S["market"].startswith("sin contexto") and "news_riskoff_6h" not in c and "market_dead" not in c
    write_context(d, now); F, S = op.review(dash_data.build_overview(d, now), cfg, now); c = codes(F)
    assert "context_stale" not in c and "news_riskoff_6h" not in c and "market_dead" not in c
    assert S["market"] == "SOL 24 h +3.2 % (up) · BTC 24 h -1.0 % (on, range) · F&G 42 · riesgo-off no · calor normal (×1.10) · lanzamientos/h 35, graduaciones 4 · amplitud 12/80 (15 %)"
    write_context(d, now, riskoff_last=6, market={"new_pools_1h": 0, "heat": "cold"}); F, S = op.review(dash_data.build_overview(d, now), cfg, now); c = codes(F)
    assert c.get("news_riskoff_6h") == "info" and c.get("market_dead") == "info" and "calor cold" in S["market"] and "lanzamientos/h 0" in S["market"]
    write_context(d, now, riskoff_last=5, market={"new_pools_1h": 0, "heat": "normal"}); c = codes(op.review(dash_data.build_overview(d, now), cfg, now)[0])
    assert "news_riskoff_6h" not in c and "market_dead" not in c                  # 5 of 6 is not sustained; 'cold' is required for a dead market
    write_context(d, now, riskoff_last=6, rows=3); c = codes(op.review(dash_data.build_overview(d, now), cfg, now)[0]); assert "news_riskoff_6h" not in c   # < 6 rows: unknown, no finding
    write_context(d, now, riskoff_last=6, market={"new_pools_1h": 0, "heat": "cold"})
    F, S = op.review(dash_data.build_overview(d, now + 3 * 3600), cfg, now + 3 * 3600); c = codes(F)     # stale: warn, and no notes from old data
    assert c.get("context_stale") == "warn" and "news_riskoff_6h" not in c and "market_dead" not in c and S["market"].startswith("obsoleto (3.")


def test_review_insider_rank_and_brain_code_findings(root):
    d, now = root; cfg = json.load(open(os.path.join(d, "config.json"))); codes = lambda F: {f["code"]: (f["level"], f["msg"]) for f in F}
    c = codes(op.review(dash_data.build_overview(d, now), cfg, now)[0])
    assert c["insider_rank_stale"][0] == "info" and "sin insider_rank.json" in c["insider_rank_stale"][1]
    assert c["brain_state_older_than_code"][0] == "info" and "sin code_version" in c["brain_state_older_than_code"][1]     # the fixture brain is v2
    write_rank(d, now); c = codes(op.review(dash_data.build_overview(d, now), cfg, now)[0]); assert "insider_rank_stale" not in c
    c = codes(op.review(dash_data.build_overview(d, now + 3 * 3600), cfg, now + 3 * 3600)[0]); assert "obsoleto" in c["insider_rank_stale"][1]
    st = json.load(open(os.path.join(d, "status_solana.json"))); st["brain"]["model"] = brain_v3(now); json.dump(st, open(os.path.join(d, "status_solana.json"), "w"))
    c = codes(op.review(dash_data.build_overview(d, now), cfg, now)[0]); assert "brain_state_older_than_code" not in c      # v3 state, no brain.py in the root
    open(os.path.join(d, "brain.py"), "w").write("# fixture\n"); t_code = dash_data._iso_ts("2026-11-02T10:00:00") + 2 * 86400; os.utime(os.path.join(d, "brain.py"), (t_code, t_code))
    F, S = op.review(dash_data.build_overview(d, now), cfg, now); c = codes(F)
    assert c["brain_state_older_than_code"][0] == "info" and "2.0 d más nuevo" in c["brain_state_older_than_code"][1] and "modelo logit (brain/3)" in S["brain"]
    os.utime(os.path.join(d, "brain.py"), (t_code - 1.5 * 86400, t_code - 1.5 * 86400))                                      # 12 h newer: within a day, no finding
    assert "brain_state_older_than_code" not in codes(op.review(dash_data.build_overview(d, now), cfg, now)[0])


def test_entry_text_market_line_and_daily_market_paragraph(root):
    d, now = root; write_context(d, now, riskoff_last=2)
    ov = dash_data.build_overview(d, now); cfg = json.load(open(os.path.join(d, "config.json"))); F, S = op.review(ov, cfg, now)
    txt = op.entry_text(F, S, [], now)
    assert "- Mercado: SOL 24 h +3.2 % (up) · BTC 24 h -1.0 % (on, range) · F&G 42 · riesgo-off no · calor normal (×1.10) · lanzamientos/h 35, graduaciones 4 · amplitud 12/80 (15 %)." in txt
    assert txt.index("- Escaneo:") < txt.index("- Mercado:") < txt.index("- Director:")
    L = op.daily_lines(d, ov, now); m = [l for l in L if l.startswith("- Mercado (contexto")]
    assert len(m) == 1 and "riesgo-off en 2 de las últimas 6 filas horarias" in m[0] and "24 filas en el histórico" in m[0]
    assert "- Mercado:" not in op.entry_text(F, {k: v for k, v in S.items() if k != "market"}, [], now)     # a summary without the key still renders
    assert op.market_line({"available": False, "error": "fichero ausente"}) == "sin contexto (fichero ausente)"
    ln = op.market_line({"available": True, "fresh": True, "sol": {}, "btc": {}, "news": {"fng": "x"}, "market": {}, "breadth": {"n_entry": 3}, "regime": {}, "stale": ["sol.r24h", "btc"]})
    assert ln == "SOL 24 h ? (?) · BTC 24 h ? (?) · F&G ? · riesgo-off ? · calor ? · lanzamientos/h ? · amplitud 3/? · sin calcular: sol.r24h, btc"
    assert op.market_line({"available": True, "fresh": False, "age_s": 9000}).startswith("obsoleto (2.5 h): SOL 24 h ?")


def test_new_findings_never_alert_and_context_stale_once_per_6h(root):
    d, now = root        # the fixture ships no context files: context_stale (warn) + info findings every hour
    r = op.run_once(d, now=now); assert "context_stale" in r["alerted"]
    F = {f["code"]: f["level"] for f in r["findings"]}; assert F["insider_rank_stale"] == "info" and F["brain_state_older_than_code"] == "info" and F["context_stale"] == "warn"
    assert "context_stale" not in op.run_once(d, now=now + 3600)["alerted"]                    # deduped
    assert "context_stale" in op.run_once(d, now=now + 6 * 3600 + 1)["alerted"]                # once per 6 h
    al = [json.loads(l)["code"] for l in open(os.path.join(d, op.ALERTS))]
    assert al.count("context_stale") == 2 and not {"insider_rank_stale", "brain_state_older_than_code", "news_riskoff_6h", "market_dead"} & set(al)
    st = json.load(open(os.path.join(d, op.STATE))); assert st["summary"]["market"].startswith("sin contexto")
    assert "- Mercado: sin contexto" in open(os.path.join(d, op.DIARY), encoding="utf-8").read()
    assert dash_data.build_overview(d, now)["operator"]["summary"]["market"].startswith("sin contexto")      # the panel shows the same line
