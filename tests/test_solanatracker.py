import solanatracker as st
def tok(sn=1, bu=0, dev=2, rug=False, market="pumpfun-amm", holders=500, ct=1000):
    return {"token": {"mint": "M", "creation": {"creator": "C", "created_time": ct}},
            "pools": [{"market": market, "liquidity": {"usd": 9000}, "price": {"usd": 0.001}}],
            "risk": {"snipers": {"totalPercentage": sn}, "bundlers": {"totalPercentage": bu}, "insiders": {"totalPercentage": 0},
                     "dev": {"percentage": dev}, "top10": 15, "rugged": rug}, "holders": holders, "buys": 10, "sells": 5}
def test_pass_and_prio():
    v, w, p = st.decide(st.features(tok(), now=2000)); assert v == "pass" and p == 1
def test_conc_reject():
    assert st.decide(st.features(tok(sn=15, bu=8)))[0] == "reject"
def test_creator_rugs():
    dep = {"data": [{"mint": f"x{i}", "liquidityUsd": 0, "createdAt": 0} for i in range(4)]}
    v, w, _ = st.decide(st.features(tok(), dep, now=10**7)); assert v == "reject" and "creator_rugs4/4" in w[0]
def test_missing_neutral():
    assert st.decide(None)[0] == "neutral" and st.features({}) is None
def test_no_key_neutral(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path); monkeypatch.delenv("SOLANATRACKER_API_KEY", raising=False)
    assert st.get("/tokens/x", "tokens", cache={}) is None
def test_live_wiring_only_tightens():
    src = open(st.__file__.replace("solanatracker.py", "memebot.py")).read()
    assert "_st.live_check" in src and "f.extend(stv)" in src and "f.clear" not in src.split("_st.live_check")[1].split("thr =")[0]
