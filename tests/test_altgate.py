import os, json, importlib, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def test_daemon_cap(tmp_path, monkeypatch):
    import solanatracker as st; importlib.reload(st)
    monkeypatch.setattr(st, "BUDGET_F", str(tmp_path/"b.json")); monkeypatch.setattr(st, "DAEMON_CAP", 2)
    st.OWNER[0] = "daemon"; r = [st._budget_ok() for _ in range(3)]
    st.OWNER[0] = "bot"; assert r == [True, True, False] and st._budget_ok()
def test_altgate_code_present():
    s = open(os.path.join(os.path.dirname(__file__), "..", "memebot.py")).read()
    assert "alt_gate_max_rt_cost_pct" in s and "gate=alt" in s and 'elif ev_ is None or ev_ < 3*max(rt_, 0)' in s
