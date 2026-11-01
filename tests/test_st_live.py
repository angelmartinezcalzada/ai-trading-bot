import solanatracker as st
def _rec(v, why=(), prio=0): return {"verdict": v, "why": list(why), "prio": prio}
def test_neutral_when_api_down(monkeypatch):
    monkeypatch.setattr(st, "get", lambda *a, **k: None)
    monkeypatch.setattr(st, "SHADOW_F", "/tmp/st_test_shadow.jsonl")
    assert st.live_check("M")[:2] == ([], 0.0)
def test_exception_neutral(monkeypatch):
    def boom(*a, **k): raise RuntimeError()
    monkeypatch.setattr(st, "shadow", boom)
    assert st.live_check("M") == ([], 0.0, None)
def test_veto(monkeypatch):
    monkeypatch.setattr(st, "shadow", lambda *a, **k: _rec("reject", ["conc30.0%", "st_rugged"], 1))
    v, b, _ = st.live_check("M"); assert v == ["st_conc30.0%", "st_st_rugged"] and b == 0
def test_bonus(monkeypatch):
    monkeypatch.setattr(st, "shadow", lambda *a, **k: _rec("pass", [], 1))
    assert st.live_check("M")[:2] == ([], 3.0)
def test_decide_rules():
    f = dict(snipers=10, bundlers=10, dev=3, insiders=0, creator_rugs=3, creator_tokens=6, st_rugged=False, migrated=False, age_h=1, holders=0, buys=0, sells=0)
    v, why, _ = st.decide(f); assert v == "reject" and len(why) == 2
    f.update(snipers=1, creator_rugs=2); assert st.decide(f)[0] == "pass"
