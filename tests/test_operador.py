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
    txt = open(os.path.join(d, "DECISIONS.md"), encoding="utf-8").read(); assert "(operador automático)" in txt
    st = json.load(open(os.path.join(d, op.STATE))); assert st["ts"] == now and st["findings"] and "solana_down" in st["alerted_now"]
    al = [json.loads(l) for l in open(os.path.join(d, op.ALERTS))]; assert any(a["code"] == "solana_down" for a in al)
    r2 = op.run_once(d, now=now + 60); assert "solana_down" not in r2["alerted"]              # deduped for 6 h
    r3 = op.run_once(d, now=now + 120, force_daily=True)
    assert r3["daily"] and "informe diario" in r3["text"] and "Decisiones que siguen siendo de Àngel" in r3["text"]
    assert json.load(open(os.path.join(d, op.STATE)))["last_daily"] == op._tz_now(now + 120)[0].strftime("%Y-%m-%d")


def test_dry_run_writes_nothing(root):
    d, now = root; before = os.path.exists(os.path.join(d, "DECISIONS.md")); st0 = open(os.path.join(d, op.STATE)).read()   # the fixture ships a state file
    r = op.run_once(d, now=now, dry_run=True)
    assert r["findings"] and os.path.exists(os.path.join(d, "DECISIONS.md")) == before and open(os.path.join(d, op.STATE)).read() == st0
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
