"""insider_rank: Beta-posterior reliability with decay, bot filter, cluster collapse, live/PnL vetoes, hysteresis, discovery merge,
Solana Tracker wrappers + per-owner budget, build() I/O (atomic + tier-change log) and the 4000 x 1200 speed bound. All offline."""
import json, os, time, glob, collections
import numpy as np
import insider_rank as ir
import solanatracker as st

NOW = 1_800_000_000.0; D = 86400.0
A1, A2, A3 = "A"*32, "B"*32, "C"*32                                    # base58-looking addresses for the ST wrappers
W6L = [(0, 7, 15), (10, 7, 15), (1, 7, 15), (2, 7, 15), (3, 7, 15), (4, 7, 15), (69, 8, 15)]   # 6 wins on 5 distinct days + 1 miss (9.5 d old)


def launch(i, win, age_d, buyers, sells=(), creator=None):
    ev = [dict(w=w, rank=r, dt=r*2.0, dslot=s, sol=0.5, q=1.0) for (w, r, s) in buyers]+[dict(w=w, sell=True, dt=9.0, sol=0.1, q=-1.0) for w in sells]
    return dict(mint="M%03d" % i, t0=NOW-age_d*D, creator=creator or "DEV%03d" % i, ev=ev, win=win, peak=1e6 if win else 1e4, sym="S%d" % i, creator2=None)


def rows_for(targets, n=100, wins=60, creators=None):
    """100 launches (60 winners -> base rate 0.6), ages 0.5..9.5 d, 8 one-off noise buyers each; targets: {wallet: [(launch, rank|None=sell, dslot)]}"""
    by = collections.defaultdict(list); sell = collections.defaultdict(list)
    for w, L in targets.items():
        for (i, r, s) in L: (sell if r is None else by)[i].append((w, r, s) if r is not None else w)
    return [launch(i, i < wins, 0.5+(i % 10), [("N%03d_%d" % (i, k), 10+k, 20+k) for k in range(8)]+by.get(i, []), sell.get(i, []), (creators or {}).get(i)) for i in range(n)]


def pnl_doc(wins, losses, wp=None, ntok=7, realized=-3.2):
    s = {"realized": realized, "unrealized": 0.0, "total": realized, "totalInvested": 10, "totalWins": wins, "totalLosses": losses}
    if wp is not None: s["winPercentage"] = wp
    return {"tokens": {"T%d" % k: {} for k in range(ntok)}, "summary": s}


# ---------- math ----------
def test_beta_quantile_known_values_and_vectorised_agreement():
    assert abs(ir.beta_ppf(0.2, 2, 2)-0.2871) < 2e-3 and abs(ir.beta_ppf(0.2, 5, 5)-0.370) < 1e-2 and abs(ir.beta_ppf(0.5, 3, 3)-0.5) < 1e-9
    x = ir.beta_ppf(0.2, 2, 2); assert abs(3*x*x-2*x**3-0.2) < 1e-8                      # analytic CDF of Beta(2,2)
    rng = np.random.default_rng(3); a = rng.uniform(1, 50, 300); b = rng.uniform(1, 50, 300)
    v = ir.beta_ppf_vec(0.2, a, b); s = np.array([ir.beta_ppf(0.2, x, y) for x, y in zip(a, b)])
    assert np.abs(v-s).max() < 1e-3 and len(ir.beta_ppf_vec(0.2, [], [])) == 0
    assert ir.decay(0) == 1 and abs(ir.decay(7*D)-0.5) < 1e-12 and ir.decay(None) == 0 and ir.decay(-5) == 1


def test_params_only_tighten():
    assert ir.params({"rel_elite": 0.3, "bot_part": 0.5, "hit_days": 30, "pnl_win": 10, "junk": 1}) == ir.P
    p = ir.params({"rel_elite": 0.7, "bot_part": 0.05, "hit_days": 7}); assert p["rel_elite"] == 0.7 and p["bot_part"] == 0.05 and p["hit_days"] == 7


def test_two_hits_not_elite_six_hits_recent_elite_and_participation_bot():
    rows = rows_for({"W2": [(0, 5, 12), (1, 5, 12)], "W6": W6L, "BOT": [(i, 0, 0) for i in range(100) if i % 20 < 7]})
    d = ir.rank({}, rows, {}, NOW)
    assert d["code"] == "insider_rank/1" and d["half_life_d"] == 7 and d["n_launches"] == 100 and abs(d["base_rate"]-0.6) < 1e-9
    w2, w6, bot = d["wallets"]["W2"], d["wallets"]["W6"], d["wallets"]["BOT"]
    assert w2["h"] == 2 and w2["m"] == 0 and w2["tier"] != "elite" and w2["rel"] < 0.6 and 1.7 < w2["h_eff"] < 2
    assert w6["tier"] == "elite" and w6["h"] == 6 and w6["m"] == 1 and w6["days"] == 6 and w6["rel"] >= 0.6 and w6["h_eff"] >= 2.5 and not w6["bot"] and w6["why"] == "elite"
    assert abs(w6["m_eff"]-0.5**(9.5/7)) < 1e-3 and w6["last_hit_t"] == NOW-0.5*D and w6["med_dslot"] == 15 and w6["med_dt"] == 14 and w6["avg_sol"] == 0.5
    assert bot["bot"] and bot["tier"] is None and bot["why"] == "bot" and bot["bot_why"].startswith("part") and abs(bot["part"]-0.35) < 1e-9 and 0 < bot["rel"] < 1
    assert d["top"][0] == "W6" and "BOT" not in d["top"] and d["tiers"]["elite"] == 1 and d["prev_tiers"]["W6"] == "elite"
    assert not any(a.startswith("N") for a in d["wallets"])                                # one-off noise buyers are not in the universe
    assert set(d["wallets"]["W6"]) == {"rel", "tier", "h", "m", "h_eff", "m_eff", "hr_post", "part", "bot", "bot_why", "early", "days", "med_dt", "med_dslot", "avg_sol",
                                       "last_hit_t", "last_seen_t", "cluster", "live_n", "live_hit", "live_mean", "pnl", "why"}
    assert set(d) == {"t", "code", "base_rate", "half_life_d", "n_launches", "wallets", "tiers", "top", "prev_tiers", "discovery"}
    assert set(d["discovery"]) == {"t", "n_candidates", "n_added", "note", "mints", "candidates"} and set(d["tiers"]) == {"elite", "good", "watch"}


def test_other_bot_rules_and_dev_exclusion():
    rows = rows_for({"SNIPE": [(i, 0, 0) for i in range(5)], "SELLER": [(0, 5, 10), (1, 5, 10)]+[(i, None, None) for i in range(2, 9)],
                     "SLOT": [(i, 1, 1) for i in range(4)], "DEVX": [(1, 3, 10), (2, 3, 10), (3, 3, 10)]}, creators={0: "DEVX"})
    W = ir.rank({}, rows, {}, NOW)["wallets"]
    assert W["SNIPE"]["bot_why"] == "slot_sniper" and W["SELLER"]["bot_why"] == "sells_early" and W["SLOT"]["bot_why"] == "slot_sniper"
    assert all(W[a]["tier"] is None for a in ("SNIPE", "SELLER", "SLOT")) and W["DEVX"]["tier"] is None and W["DEVX"]["why"] == "dev"


def test_stale_or_unknown_last_hit_blocks_elite():
    pr = ir.params(); o = dict(rel=0.7, h_eff=4.0, hr_post=0.7, days=3, last_hit_t=NOW-13*D, live_n=0, live_mean=None, pnl=None, bot=False, why=None, n=5)
    assert ir._raw_tier(o, pr, 0.6, NOW) == ("elite", "elite")
    assert ir._raw_tier(dict(o, last_hit_t=NOW-15*D), pr, 0.6, NOW) == ("good", "stale") and ir._raw_tier(dict(o, last_hit_t=None), pr, 0.6, NOW) == ("good", "stale")
    assert ir._raw_tier(dict(o, live_n=10, live_mean=None), pr, 0.6, NOW) == ("watch", "live_veto")                    # live cases without a mean: fail-closed
    assert ir._raw_tier(dict(o, rel=0.55, hr_post=0.55), pr, 0.6, NOW) == ("good", "good") and ir._raw_tier(dict(o, rel=0.3, hr_post=0.5), pr, 0.6, NOW) == (None, "low")


# ---------- cluster / live / pnl ----------
def test_cluster_collapse_keeps_only_best_wallet_tiered():
    rows = rows_for({"C1": W6L, "C2": [(20, 7, 15), (21, 7, 15), (22, 7, 15), (23, 7, 15), (24, 7, 15), (69, 8, 15)], "F1": W6L})
    wj = {"t": NOW, "wallets": {"C1": {"cluster": "fund1", "cluster_n": 2}, "C2": {"cluster": "fund1", "cluster_n": 2}, "F1": {"cluster": "farm", "cluster_n": 9}}}
    W = ir.rank(wj, rows, {}, NOW)["wallets"]
    assert W["C1"]["tier"] == "elite" and W["C2"]["tier"] == "watch" and W["C2"]["why"] == "cluster" and W["C2"]["cluster"] == "fund1"
    assert W["F1"]["tier"] is None and W["F1"]["why"] == "farm_cluster"
    assert ir.rank({}, rows, {}, NOW)["wallets"]["C2"]["tier"] in ("good", "elite")       # without the cluster it would be tiered


def test_live_track_veto():
    rows = rows_for({"LV": W6L})
    W = ir.rank({}, rows, {"LV": {"n": 12, "h": 3, "sum": -0.5}}, NOW)["wallets"]["LV"]
    assert W["live_n"] == 12 and W["live_hit"] == 3 and abs(W["live_mean"]+0.0417) < 1e-3 and W["tier"] == "watch" and W["why"] == "live_veto"
    assert ir.rank({}, rows, {"LV": {"n": 12, "h": 5, "sum": -0.1}}, NOW)["wallets"]["LV"]["tier"] == "good"      # mean -0.8%: good allowed, elite not
    assert ir.rank({}, rows, {"LV": {"n": 12, "h": 7, "sum": 0.1}}, NOW)["wallets"]["LV"]["tier"] == "elite"
    assert ir.rank({}, rows, {"LV": {"n": 5, "h": 0, "sum": -0.9}}, NOW)["wallets"]["LV"]["tier"] == "elite"      # < 10 live cases: no veto yet
    assert ir.rank({}, rows, {"LV": "junk"}, NOW)["wallets"]["LV"]["tier"] == "elite"


def test_pnl_requirement_for_elite():
    rows = rows_for({"PN": W6L})
    o = ir.rank({}, rows, {}, NOW, st_pnl={"PN": pnl_doc(2, 5, 28.57)})["wallets"]["PN"]
    assert o["tier"] == "good" and o["why"] == "pnl_veto" and o["pnl"] == {"realized": -3.2, "unrealized": 0.0, "win_pct": 28.57, "n_tokens": 7, "src": "st"}
    assert ir.rank({}, rows, {}, NOW, st_pnl={"PN": pnl_doc(6, 1, 85.7)})["wallets"]["PN"]["tier"] == "elite"
    assert ir.rank({}, rows, {}, NOW, st_pnl={"PN": pnl_doc(1, 2, 33.3, ntok=3)})["wallets"]["PN"]["tier"] == "elite"    # < 5 tokens: not enough to veto
    assert ir.rank({}, rows, {}, NOW, st_pnl={"PN": pnl_doc(4, 4)})["wallets"]["PN"]["tier"] == "elite"                 # win % derived 50 -> ok
    assert ir.rank({}, rows, {}, NOW, st_pnl={"PN": {"tokens": {"a": {}, "b": {}, "c": {}, "d": {}, "e": {}}, "summary": {"realized": 1}}})["wallets"]["PN"]["tier"] == "good"  # unknown win % with 5 tokens: fail-closed
    assert ir.rank({}, rows, {}, NOW, st_pnl={"PN": "garbage"})["wallets"]["PN"]["tier"] == "elite" and ir.parse_pnl({"summary": "x"}) is None and ir.parse_pnl(None) is None


# ---------- hysteresis ----------
def test_hysteresis_pending_then_confirm_and_immediate_demotion():
    rows = rows_for({"W6": W6L})
    d0 = ir.rank({}, rows, {}, NOW); assert d0["wallets"]["W6"]["tier"] == "elite"                                   # bootstrap (no prev): raw tiers
    p0 = {"code": ir.CODE, "wallets": {}, "prev_tiers": {}}; d1 = ir.rank({}, rows, {}, NOW, prev=p0)
    assert d1["wallets"]["W6"]["tier"] is None and d1["wallets"]["W6"]["why"] == "pending:elite" and d1["prev_tiers"]["W6"] == "elite?" and ir.tier_changes(p0, d1) == []
    d2 = ir.rank({}, rows, {}, NOW+1200, prev=d1)
    assert d2["wallets"]["W6"]["tier"] == "elite" and ir.tier_changes(d1, d2) == [{"t": NOW+1200, "addr": "W6", "from": None, "to": "elite", "rel": d2["wallets"]["W6"]["rel"], "why": "elite"}]
    assert ir.rank({}, rows, {}, NOW, prev={"wallets": {"W6": {"tier": "good"}}, "prev_tiers": {"W6": "good"}})["wallets"]["W6"]["tier"] == "elite"   # one step up: immediate
    d3 = ir.rank({}, rows, {}, NOW, prev={"wallets": {"W6": {"tier": "watch"}}, "prev_tiers": {"W6": "watch"}})
    assert d3["wallets"]["W6"]["tier"] == "watch" and d3["prev_tiers"]["W6"] == "elite?"                                   # two steps: pending
    d4 = ir.rank({}, rows, {}, NOW+16*D, prev=d2); ch = ir.tier_changes(d2, d4)                                           # hits now > 14 d old
    assert d4["wallets"]["W6"]["tier"] != "elite" and ch[0]["from"] == "elite" and ch[0]["to"] == d4["wallets"]["W6"]["tier"]
    assert ir.tier_changes(d2, dict(d4, wallets={}))[0]["to"] is None and ir.tier_changes(None, d0)[0]["from"] is None


# ---------- discovery / ST ----------
class FakeST:
    OWNER = ["bot"]; CACHE_F = "x"; TTL = {"pnl": 43200}
    def __init__(s, cache=None): s.calls = []; s.cache = cache or {}
    def first_buyers(s, m): s.calls.append(("fb", m, s.OWNER[0])); return [{"wallet": A1, "total": 12.5}, {"wallet": "bad"}, "junk"]
    def top_traders(s, page=1): s.calls.append(("tt", page, s.OWNER[0])); return {"wallets": [{"wallet": A2, "summary": {"total": 100, "totalWins": 9, "totalLosses": 3, "winPercentage": 75}}]}
    def wallet_pnl(s, a): s.calls.append(("pnl", a, s.OWNER[0])); return pnl_doc(6, 1, 85.7)
    def _load(s, f, d): return s.cache


def test_discover_merges_candidates_as_discovered_only():
    rows = rows_for({"W6": W6L}); fs = FakeST()
    f = ir.discover(fs, rows, {}, NOW, budget=3)
    assert f["n_calls"] == 4 and len(f["mints"]) == 3 and all(c[2] == "insider" for c in fs.calls) and fs.OWNER[0] == "bot"
    assert f["candidates"][A1] == {"src": "first_buyers", "n_wins": 3, "pnl_total": 37.5, "win_pct": None} and f["candidates"][A2] == {"src": "top_traders", "n_wins": 9, "pnl_total": 100.0, "win_pct": 75.0}
    disc = ir.merge_discovery(None, f, NOW); d = ir.rank({}, rows, {}, NOW, discovery=disc)
    for a in (A1, A2): assert d["wallets"][a]["tier"] is None and d["wallets"][a]["why"] == "discovered" and d["wallets"][a]["h"] == 0 and a not in d["top"]
    assert d["discovery"]["n_added"] == 2 and d["discovery"]["n_candidates"] == 2 and d["discovery"]["mints"] == f["mints"] and d["discovery"]["t"] == NOW
    f2 = ir.discover(fs, rows, d, NOW, budget=3); assert not set(f2["mints"]) & set(f["mints"])                            # already discovered mints are skipped
    d2 = ir.rank({}, rows, {}, NOW+15*D, prev=d); assert A1 not in d2["wallets"]                                           # candidates expire after 14 d
    class Broken:
        def first_buyers(s, m): raise RuntimeError("boom")
        def top_traders(s, p): return "nonsense"
    assert ir.discover(Broken(), rows, {}, NOW, budget=2) == {"candidates": {}, "n_calls": 3, "mints": []}


def test_pull_pnl_cache_first_and_budget():
    fs = FakeST(cache={f"/pnl/{A3}": {"t": time.time(), "d": pnl_doc(1, 1)}})
    out = ir.pull_pnl(fs, [A1, A2, A3, "D"*32, "E"*32], budget=2)
    assert set(out) == {A3, A1, A2} and [c[1] for c in fs.calls] == [A3, A1, A2] and all(c[2] == "insider" for c in fs.calls) and out[A1]["win_pct"] == 85.7
    assert ir.pull_pnl(object(), [A1], budget=5) == {}


def test_st_wrappers_return_none_on_malformed_and_never_raise(monkeypatch):
    for bad in (None, "str", 7, {}, {"wallets": "x"}, {"summary": 1}, []):
        monkeypatch.setattr(st, "get", lambda *a, **k: bad)
        assert st.wallet_pnl(A1) is None and st.wallet_info(A1) is (bad if isinstance(bad, dict) else None) and st.top_traders(1) is (bad if isinstance(bad, list) else None)
        assert st.first_buyers(A1) is (bad if isinstance(bad, list) else None)
    def boom(*a, **k): raise RuntimeError("x")
    monkeypatch.setattr(st, "get", boom)
    assert st.top_traders() is None and st.first_buyers(A1) is None and st.wallet_pnl(A1) is None and st.wallet_info(A1) is None
    monkeypatch.setattr(st, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")))
    assert st.first_buyers("../x") is None and st.wallet_pnl("") is None and st.wallet_info(None) is None and st.top_traders("x") is None
    seen = []; monkeypatch.setattr(st, "get", lambda p, k, **kw: seen.append((p, k)) or {"summary": {"realized": 1}})
    assert st.wallet_pnl(A1) == {"summary": {"realized": 1}} and st.top_traders(2) is None and seen[0] == (f"/pnl/{A1}", "pnl") and seen[1] == ("/top-traders/all/2", "top_traders")
    assert all(st.TTL[k] == v for k, v in {"top_traders": 21600, "first_buyers": 86400, "pnl": 43200, "wallet": 21600}.items()) and st.TTL["tokens"] == 3600


def test_budget_accounting_per_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "BUDGET_F", str(tmp_path/"b.json")); monkeypatch.setattr(st, "INSIDER_CAP", 3); monkeypatch.setattr(st, "OWNER", ["insider"])
    assert [st._budget_ok() for _ in range(4)] == [True, True, True, False]
    st.OWNER[0] = "bot"; assert st._budget_ok() and st._budget_ok()                       # the bot is only limited by DAILY_CAP
    st.OWNER[0] = "daemon"; assert st._budget_ok()
    b = json.load(open(tmp_path/"b.json")); assert b["ni"] == 3 and b["nd"] == 1 and b["n"] == 6
    st.OWNER[0] = "insider"; assert not st._budget_ok() and json.load(open(tmp_path/"b.json"))["n"] == 6


# ---------- files ----------
def test_build_writes_atomically_logs_tier_changes_and_load_staleness(tmp_path):
    root = str(tmp_path); os.makedirs(tmp_path/"research"); rows = rows_for({"W6": W6L, "C2": [(20, 7, 15), (21, 7, 15), (22, 7, 15), (23, 7, 15), (24, 7, 15)]})
    assert ir.build(root, now=NOW) is None and not os.path.exists(tmp_path/ir.F_RANK)                                    # nothing mined: nothing written
    with open(tmp_path/ir.F_MINED, "w") as f: f.writelines(json.dumps(r)+"\n" for r in rows); f.write("not json\n")
    json.dump({"t": NOW, "wallets": {"C2": {"cluster": "k1", "tier": "good", "sc": 1}}}, open(tmp_path/ir.F_W, "w"))
    d1 = ir.build(root, now=NOW); L = ir.read_jsonl(str(tmp_path/ir.F_LOG))
    assert d1["wallets"]["W6"]["tier"] == "elite" and json.load(open(tmp_path/ir.F_RANK))["t"] == NOW and not glob.glob(root+"/*.tmp")
    assert len(L) == sum(1 for o in d1["wallets"].values() if o["tier"]) and all(set(r) == {"t", "addr", "from", "to", "rel", "why"} for r in L) and d1["wallets"]["C2"]["cluster"] == "k1"
    d2 = ir.build(root, now=NOW+1200); assert d2["wallets"]["W6"]["tier"] == "elite" and len(ir.read_jsonl(str(tmp_path/ir.F_LOG))) == len(L)   # unchanged: no new rows
    d3 = ir.build(root, now=NOW+16*D); r = ir.read_jsonl(str(tmp_path/ir.F_LOG))[-1]
    assert d3["wallets"]["W6"]["tier"] != "elite" and r["addr"] == "W6" and r["from"] == "elite" and r["to"] == d3["wallets"]["W6"]["tier"]
    fs = FakeST(); d4 = ir.build(root, st=fs, now=NOW+16*D+1200, disc_budget=2, pnl_budget=3)
    assert d4["discovery"]["n_candidates"] == 2 and d4["wallets"][A1]["why"] == "discovered" and any(c[0] == "pnl" for c in fs.calls) and fs.OWNER[0] == "bot"
    assert all(d4["wallets"][a]["pnl"] for a in d4["top"][:3])
    doc = json.load(open(tmp_path/ir.F_RANK)); doc["t"] = time.time(); ir.write_json(str(tmp_path/ir.F_RANK), doc); assert ir.load(root)["code"] == ir.CODE
    doc["t"] = time.time()-7201; ir.write_json(str(tmp_path/ir.F_RANK), doc); assert ir.load(root) is None
    doc["t"] = time.time()+7201; ir.write_json(str(tmp_path/ir.F_RANK), doc); assert ir.load(root) is None                 # clock skew: fail-closed
    doc["t"] = time.time(); doc["code"] = "other"; ir.write_json(str(tmp_path/ir.F_RANK), doc); assert ir.load(root) is None
    assert ir.load(str(tmp_path/"nope")) is None and "nivel" in ir.table(d4) and A1[:6]+"..." in ir.table(d4) and A1 not in ir.table(d4) and ir.table(None).startswith("sin ranking")


def test_speed_4000_wallets_1200_launches():
    rng = np.random.default_rng(0); NW, NL = 4000, 1200; wal = ["W%05d" % i for i in range(NW)]; big = []
    for i in range(NL):
        idx = rng.choice(NW, 100, replace=False); ds = rng.integers(0, 60, 100)
        big.append(dict(mint="X%04d" % i, t0=NOW-float(rng.uniform(0, 30))*D, creator="C%04d" % i, win=bool(rng.random() < 0.55), peak=1, sym="x", creator2=None,
                        ev=[dict(w=wal[j], rank=k, dt=float(k), dslot=int(ds[k]), sol=0.3, q=1.0) for k, j in enumerate(idx)]))
    t = time.time(); d = ir.rank({}, big, {}, NOW); dt = time.time()-t
    assert dt < 2.0 and len(d["wallets"]) == NW and len(d["top"]) <= 200 and d["n_launches"] == NL
