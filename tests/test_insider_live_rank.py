"""insider live follower on the reliability ranking (insider_rank.json contract), convergence by cluster, state checkpoint, status keys
and the fallback without insider_rank. Offline: rpc / parse_swap / _px / requests / _gk / promote are faked; the rank module is a fake
injected in sys.modules (None = absent, also once the real module is merged)."""
import json, os, sys, time, types, collections, logging
import pytest
import insider, insider_ws


def A(i): return "Wallet%03d" % i + "k" * 36          # 44-char addresses


def rw(tier, rel=0.5, bot=False, cluster=None):
    return dict(rel=rel, tier=tier, h=3, m=1, h_eff=2.5, m_eff=0.8, hr_post=0.7, part=0.1, bot=bot, bot_why="sniper" if bot else None, early=0.5, days=3,
                med_dt=12.0, med_dslot=4.0, avg_sol=0.8, last_hit_t=None, last_seen_t=None, cluster=cluster, live_n=0, live_hit=0, live_mean=None, pnl=None, why="")


def rank_doc(wallets, top=None, t=None):
    return dict(t=time.time() if t is None else t, code="insider_rank/1", base_rate=0.3, half_life_d=7, n_launches=50, wallets=wallets,
                tiers=dict(collections.Counter(o["tier"] for o in wallets.values() if o["tier"])),
                top=top if top is not None else sorted(wallets, key=lambda w: -wallets[w]["rel"])[:200], prev_tiers={}, discovery=dict(t=None, n_candidates=0, n_added=0, note=""))


def fake_rank(monkeypatch, R, calls=None):
    m = types.SimpleNamespace(load=lambda root=".": R, build=lambda root=".", st=None, now=None: (calls.append(root) if calls is not None else None) or R)
    monkeypatch.setitem(sys.modules, "insider_rank", m); return m


def W_of(tiers, sc=None): return {w: dict(h=2, m=1, hr=0.6, early=0.5, days=2, sc=(sc or {}).get(w, 1.0), snipe=0, tier=t) for w, t in tiers.items()}


def _wallets_file(W): json.dump(dict(t=time.time(), launches=10, wallets=W, tiers={}), open(insider.F_W, "w"))


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path); os.makedirs("research")
    class NoNet:
        def get(self, *a, **k): raise RuntimeError("no network in tests")
        post = get
    monkeypatch.setattr(insider, "requests", NoNet())
    monkeypatch.setattr(insider, "_gk", lambda path, **p: {})
    monkeypatch.setattr(insider, "promote", lambda min_n=40: {})
    monkeypatch.setattr(insider, "_px", lambda m, **k: 1.0)
    monkeypatch.setattr(insider, "rpc", lambda m, p, gap=0.13: None)
    monkeypatch.setattr(insider, "parse_swap", lambda sig, mint=None, owner=None: [])
    return tmp_path


def test_rank_eligible_order_tier_override_bot_and_unknown_excluded():
    a, b, c, d, e, f, g = (A(i) for i in range(7))
    W = W_of({a: "good", b: "elite", c: "watch", d: "elite", e: "elite", g: "good"})       # f is NOT in insider_wallets.json
    RW = {a: rw("elite", 0.9), b: rw("elite", 0.8, bot=True), c: rw("good", 0.7), d: rw("watch", 0.6), e: rw(None, 0.5), f: rw("elite", 0.95), g: rw("good", 0.2)}
    R = rank_doc(RW, top=[f, a, b, c, d, e])                                                 # g beyond top: appended by rel
    assert insider_ws.rank_eligible(R, W) == [a, c, g]                                       # bot b, watch d, null e, unknown f: never, whatever the wallet file says
    assert insider_ws.pick_wallets({"wallets": W}, R=R) == [a, c, g] and insider_ws.pick_wallets({"wallets": W}, max_wallets=1, R=R) == [a]
    assert insider_ws.pick_wallets({"wallets": W}) == [b, d, e, a, g]                        # old ordering unchanged without a rank doc
    assert insider_ws.rank_eligible(None, W) == [] and insider_ws.rank_eligible({"wallets": "x"}, W) == [] and insider_ws.rank_eligible(R, {}) == []


def test_select_tracked_rank_order_tier_from_rank_and_rotation_advances():
    ws = [A(i) for i in range(130)]
    RW = {w: rw("elite" if i < 50 else "good", rel=1-i/1000) for i, w in enumerate(ws)}
    W = W_of({w: "watch" for w in ws})                                                        # the wallet file says watch for all: the rank tier wins
    R = rank_doc(RW)                                                                           # top = by rel desc = ws order
    tr, tiers, rot = insider.select_tracked(W, {}, R, rot_i=0, max_wallets=120, rot_n=20)
    assert tr[:100] == ws[:100] and tr[100:] == ws[100:120] and rot == dict(i=0, n=20, pool=30, wallets=ws[100:120]) and len(tr) == 120
    assert tiers[ws[0]] == "elite" and tiers[ws[60]] == "good" and set(tiers.values()) == {"elite", "good"}
    tr1, _, rot1 = insider.select_tracked(W, {}, R, rot_i=1)
    assert tr1[:100] == ws[:100] and rot1["wallets"] == ws[120:130]+ws[100:110]              # advances by 20 and wraps around the pool
    assert insider.select_tracked(W, {}, R, rot_i=3)[2]["wallets"] == ws[100:120]
    R2 = rank_doc({w: RW[w] for w in ws[:105]}); tr3, _, rot3 = insider.select_tracked(W, {}, R2, rot_i=7)
    assert sorted(tr3[100:]) == sorted(ws[100:105]) and rot3["n"] == 5 and rot3["pool"] == 5   # small pool: everyone beyond the fixed slots is tracked
    assert insider.select_tracked(W, {}, rank_doc({}), 0) == ([], {}, dict(i=0, n=0, pool=0, wallets=[]))   # empty verdict is final
    # fallback without a rank doc: today's ordering (mined score + live 1h re-rank), tiers from insider_wallets.json, no rotation
    Wf = W_of({ws[0]: "elite", ws[1]: "good", ws[2]: "watch", ws[3]: "elite"}, sc={ws[0]: 1, ws[1]: 5, ws[3]: 2})
    trf, tiersf, rotf = insider.select_tracked(Wf, {ws[3]: dict(n=10, h=10, sum=1.0)}, None)
    assert trf == [ws[1], ws[3], ws[0]] and tiersf == {ws[1]: "good", ws[3]: "elite", ws[0]: "elite"} and rotf is None


def test_convergence_counts_clusters_and_dedups_sellers():
    now = time.time(); a, b, c, d, e = (A(i) for i in range(5)); cl = {a: "k1", b: "k1", c: "k1", d: "k2"}; cid = lambda w: cl.get(w) or w
    buys = [dict(t=now-10, w=a, tier="elite", mint="M1"), dict(t=now-20, w=b, tier="elite", mint="M1"), dict(t=now-30, w=c, tier="good", mint="M1"),
            dict(t=now-5, w=a, tier="elite", mint="M2"), dict(t=now-6, w=d, tier="elite", mint="M2"), dict(t=now-7, w=e, tier="good", mint="M2"),
            dict(t=now-4000, w=d, tier="elite", mint="M1")]                                   # outside the window
    sells = [dict(t=now-10, w=a, tier="elite", mint="M3"), dict(t=now-20, w=a, tier="elite", mint="M3"), dict(t=now-30, w=e, tier="good", mint="M3"), dict(t=now-5000, w=d, tier="elite", mint="M4")]
    conv, sbm, sbn = insider.convergence(buys, sells, now, 1800, cid)
    assert conv["M1"] == dict(score=3, n=3, elite=1, n_clusters=1)                            # 3 wallets of one funding cluster = one actor (best tier counts once)
    assert conv["M2"] == dict(score=8, n=3, elite=2, n_clusters=3)                            # k1 elite + k2 elite + e (own address) good
    assert sbm == {"M3": 8, "M4": 0} and sbn == {"M3": dict(n=2, elite=1), "M4": dict(n=0, elite=0)}   # weighted sum over events kept; distinct sellers added
    assert insider.convergence([], [], now, 1800, cid) == ({}, {}, {})


def test_state_checkpoint_round_trip_drops_old_entries_and_stale_files(offline):
    now = time.time(); a = A(1); fresh = lambda **k: dict(t=now-100, **k); old = lambda **k: dict(t=now-7*3600, **k)
    st = dict(done={a: ["s1", "s2"]}, buys=[fresh(w=a, tier="elite", mint="M1"), old(w=a, tier="elite", mint="M0")], sells=[old(w=a, tier="elite", mint="M0")],
              alerts=[fresh(mint="M1", px=1.0, score=6, n=2, elite=2, n_clusters=2)], feed=[fresh(kind="smart_buy")],
              tok={"M1": dict(flow_t=now-50, score=4.0), "M0": dict(flow_t=now-8*3600, score=1.0), "Mx": dict(score=2.0)},
              snaps=[fresh(mint="M1", score=4.0, px=1.0), old(mint="M0", score=1.0, px=1.0)], wbuys=[fresh(w=a, tier="elite", mint="M1", px=1.0)],
              pools={"p1": fresh(m="M1", liq=1), "p0": old(m="M0", liq=1)}, promo_t=now-100)
    insider.save_state(st, now)
    assert os.path.exists(insider.F_LS) and not os.path.exists(insider.F_LS+".tmp")
    s2 = insider.load_state(now=now)
    assert s2["done"] == {a: ["s1", "s2"]} and [b["mint"] for b in s2["buys"]] == ["M1"] and s2["sells"] == [] and len(s2["alerts"]) == 1 and len(s2["feed"]) == 1
    assert set(s2["tok"]) == {"M1"} and [x["mint"] for x in s2["snaps"]] == ["M1"] and len(s2["wbuys"]) == 1 and set(s2["pools"]) == {"p1"} and s2["promo_t"] == now-100
    s3 = insider.load_state(now=now+7*3600); assert s3["done"] == {} and s3["buys"] == [] and s3["alerts"] == []        # file itself stale: nothing restored
    empty = dict(done={}, buys=[], sells=[], alerts=[], feed=[], tok={}, snaps=[], wbuys=[], pools={})
    open(insider.F_LS, "w").write("{broken"); assert insider.load_state(now=now) == empty
    os.remove(insider.F_LS); assert insider.load_state(now=now) == empty
    json.dump({"t": now, "buys": "junk", "done": [1], "tok": 3}, open(insider.F_LS, "w")); s4 = insider.load_state(now=now)
    assert s4["buys"] == [] and s4["done"] == {} and s4["tok"] == {}                                                       # wrong shapes -> defaults, never a crash


def test_live_cycle_tracks_rank_wallets_clusters_status_keys_and_reloads_state(offline, monkeypatch, caplog):
    now = time.time(); a, b, c, d, e = (A(i) for i in range(5))
    W = W_of({a: "good", b: "watch", c: "elite", d: "elite", e: "elite"}); _wallets_file(W)
    RW = {a: rw("elite", 0.9, cluster="k1"), b: rw("elite", 0.8, cluster="k1"), c: rw("elite", 0.7, cluster="k2"), d: rw("elite", 0.95, bot=True), e: rw("watch", 0.5)}
    R = rank_doc(RW); fake_rank(monkeypatch, R)
    sigs = {w: [{"signature": "sig1_"+w[:9]}] for w in (b, c, d, e)}
    monkeypatch.setattr(insider, "rpc", lambda m, p, gap=0.13: sigs.get(p[0], []) if m == "getSignaturesForAddress" else None)
    monkeypatch.setattr(insider, "parse_swap", lambda sig, mint=None, owner=None: [dict(w=owner, signer=owner, mint="M1", dq=10.0, dsol=-0.5, slot=1, ts=now-10)])
    insider_ws.enqueue(insider_ws.QUEUE, a, "sigws_a"); insider_ws.enqueue(insider_ws.QUEUE, d, "sigws_d")             # socket events: a is followed, d (bot) is not
    # a previous daemon run left cursors (so new signatures are swaps to process), a 7 h old buy and two sells by one elite wallet
    json.dump(dict(t=now-60, v=1, done={a: [], b: [], c: [], d: [], e: []}, buys=[dict(t=now-7*3600, w=a, tier="elite", mint="M0")],
                   sells=[dict(t=now-100, w=c, tier="elite", mint="M2"), dict(t=now-200, w=c, tier="elite", mint="M2")], alerts=[], tok={}, wbuys=[], snaps=[], pools={}, feed=[]),
              open(insider.F_LS, "w"))
    json.dump({"ts": now-500, "state": "connected", "subs": 3, "events": 1, "ws": "wss://host/?api-key=SECRETKEY"}, open(insider_ws.STATUS, "w"))   # stale socket: RPC polls every cycle
    caplog.set_level(logging.WARNING, logger="insider")
    insider.live(conv_win=1800, poll=0, cycles=1)
    assert not [r for r in caplog.records if r.getMessage().startswith("live ")], caplog.text
    S = json.load(open(insider.F_ST))
    for k in ("ts", "v", "tracked", "cycle_s", "conv", "alerts", "buys", "sells", "sells_by_mint", "tokens", "tok_valid", "feed", "counts", "live_ranked",
              "sells_n_by_mint", "rank_t", "rank_tiers", "rank_src", "tracked_by_tier", "rotation_slice", "rpc_err_n", "ws_health"): assert k in S, k
    assert S["tracked"] == 3 and S["tracked_by_tier"] == {"elite": 3} and S["rank_t"] == R["t"] and S["rank_tiers"] == R["tiers"] and S["rank_src"] == "insider_rank"
    assert S["rotation_slice"] == dict(i=0, n=0, pool=0, wallets=[]) and isinstance(S["rpc_err_n"], int)
    assert S["ws_health"]["ok"] is False and S["ws_health"]["subs"] == 3 and S["ws_health"]["state"] == "connected" and "SECRETKEY" not in json.dumps(S)
    assert sorted(x["w"] for x in S["buys"]) == sorted([a, b, c]) and all(x["tier"] == "elite" for x in S["buys"])   # d (bot) and e (watch) never followed; tier from the rank, not the file
    assert S["conv"]["M1"] == dict(score=6, n=3, elite=2, n_clusters=2)                                              # a+b share funding cluster k1
    assert S["sells_by_mint"] == {"M2": 6} and S["sells_n_by_mint"] == {"M2": dict(n=1, elite=1)}
    assert len(S["alerts"]) == 1 and S["alerts"][0]["mint"] == "M1" and S["alerts"][0]["n_clusters"] == 2 and S["tokens"]["M1"]["n_clusters"] == 2
    assert not [x for x in S["buys"] if x["mint"] == "M0"] and S["counts"].get("cluster_buy") == 1                   # 7 h old buy dropped on reload
    L = json.load(open(insider.F_LS)); assert len(L["buys"]) == 3 and set(L["done"]) >= {a, b, c} and "sigws_a" in L["done"][a] and L["t"] >= now
    assert not os.path.exists(insider.F_ST+".tmp") and not os.path.exists(insider.F_LS+".tmp") and os.path.getsize(insider_ws.QUEUE) == 0
    # a restarted daemon reloads the checkpoint: the same signatures are not replayed, the convergence survives
    insider.live(conv_win=1800, poll=0, cycles=1); S2 = json.load(open(insider.F_ST))
    assert len(S2["buys"]) == 3 and S2["conv"]["M1"]["n"] == 3 and len(S2["alerts"]) == 1 and not [r for r in caplog.records if r.getMessage().startswith("live ")]


def test_live_fallback_without_insider_rank_uses_wallet_file_tiers_and_clusters(offline, monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "insider_rank", None)                                   # module absent (also once the real one is merged)
    assert insider._rank_mod() is None and insider.rank_doc() is None
    now = time.time(); a, b, c = (A(i) for i in range(3)); W = W_of({a: "elite", b: "good", c: "watch"}, sc={a: 1, b: 2}); W[a]["cluster"] = W[b]["cluster"] = "f1"; _wallets_file(W)
    sigs = {w: [{"signature": "sig_"+w[:9]}] for w in (a, b, c)}
    monkeypatch.setattr(insider, "rpc", lambda m, p, gap=0.13: sigs.get(p[0], []) if m == "getSignaturesForAddress" else None)
    monkeypatch.setattr(insider, "parse_swap", lambda sig, mint=None, owner=None: [dict(w=owner, signer=owner, mint="M1", dq=10.0, dsol=-0.5, slot=1, ts=now-10)])
    json.dump(dict(t=now-60, v=1, done={a: [], b: [], c: []}, buys=[], sells=[], alerts=[], tok={}, wbuys=[], snaps=[], pools={}, feed=[]), open(insider.F_LS, "w"))
    caplog.set_level(logging.WARNING, logger="insider")
    insider.live(conv_win=1800, poll=0, cycles=2)                                             # cycle 2 polls the good wallets too
    assert not [r for r in caplog.records if r.getMessage().startswith("live ")], caplog.text
    S = json.load(open(insider.F_ST))
    assert S["rank_t"] is None and S["rank_tiers"] is None and S["rank_src"] == "insider_wallets" and S["rotation_slice"] is None and S["ws_health"] is None
    assert S["tracked"] == 2 and S["tracked_by_tier"] == {"elite": 1, "good": 1} and sorted(x["w"] for x in S["buys"]) == sorted([a, b])
    assert S["conv"]["M1"] == dict(score=3, n=2, elite=1, n_clusters=1) and S["alerts"] == []   # wallet-file funding cluster used; one cluster never alerts
    # a stale or broken rank doc also falls back
    fake_rank(monkeypatch, rank_doc({a: rw("elite")}, t=now-3*3600)); assert insider.rank_doc(now) is None
    monkeypatch.setitem(sys.modules, "insider_rank", types.SimpleNamespace(load=lambda root=".": 1/0)); assert insider.rank_doc() is None
    monkeypatch.setitem(sys.modules, "insider_rank", types.SimpleNamespace(load=lambda root=".": {"t": now, "wallets": [1]})); assert insider.rank_doc() is None


def test_build_refreshes_rank_when_module_present_and_works_without_it(offline, monkeypatch):
    import smart_money; monkeypatch.setattr(smart_money, "load", lambda: {})
    x, y, dev = A(10), A(11), A(12); ev = lambda w, r: dict(w=w, rank=r, dt=30, dslot=5, sol=0.5, q=1000)
    for i in range(3):
        open(insider.F_MINED, "a").write(json.dumps(dict(mint="MINT%d" % i, t0=time.time()-86400*(i+1), creator=dev, ev=[ev(dev, 0), ev(x, 1), ev(y, 2)], win=1, peak=5e5, sym="S%d" % i, creator2=None))+"\n")
    calls = []; fake_rank(monkeypatch, rank_doc({}), calls)
    W = insider.build(do_cluster=False)
    assert x in W and dev not in W and W[x]["tier"] in ("elite", "good") and calls == ["."] and json.load(open(insider.F_W))["wallets"][x]["tier"] == W[x]["tier"]
    monkeypatch.setitem(sys.modules, "insider_rank", None); assert insider.build(do_cluster=False).keys() == W.keys()
    monkeypatch.setitem(sys.modules, "insider_rank", types.SimpleNamespace(load=lambda root=".": None, build=lambda root=".", st=None, now=None: 1/0))
    assert insider.build(do_cluster=False).keys() == W.keys() and not os.path.exists(insider.F_W+".tmp")   # a failing rank build never breaks the wallet build


def test_px_cache_and_spacer(monkeypatch):
    calls = []
    class Resp:
        def json(self): return [{"priceUsd": "0.5", "liquidity": {"usd": 10}}, {"priceUsd": "0.7", "liquidity": {"usd": 100}}]
    monkeypatch.setattr(insider, "requests", types.SimpleNamespace(get=lambda url, timeout=10: calls.append(url) or Resp()))
    monkeypatch.setattr(insider, "_px_c", {}); insider._px_t[0] = 0.0
    t0 = time.time(); assert insider._px("MA") == 0.7 and insider._px("MA") == 0.7 and len(calls) == 1          # 60 s per-mint cache
    assert insider._px("MB") == 0.7 and len(calls) == 2 and time.time()-t0 >= 0.25                               # 0.25 s spacer between fetches
    monkeypatch.setattr(insider, "requests", types.SimpleNamespace(get=lambda url, timeout=10: 1/0))
    assert insider._px("MA") == 0.7 and insider._px("MC") is None and insider._px("MC") is None                  # failures: None, never cached


def test_rpc_error_counter(monkeypatch):
    monkeypatch.setattr(insider.time, "sleep", lambda s: None)
    class R:
        def __init__(self, code, body): self.status_code, self.b = code, body
        def json(self): return self.b
    seq = [R(429, {}), R(200, {"error": {"code": -32000, "message": "x"}}), R(200, {"result": 7})]
    monkeypatch.setattr(insider, "requests", types.SimpleNamespace(post=lambda *a, **k: seq.pop(0)))
    insider._rpc_err.clear()
    assert insider.rpc("m", []) is None and insider.rpc_err_n() == 2                                            # 429 attempt + error reply
    assert insider.rpc("m", []) == 7 and insider.rpc_err_n() == 2 and insider.rpc_err_n(now=time.time()+601) == 0
