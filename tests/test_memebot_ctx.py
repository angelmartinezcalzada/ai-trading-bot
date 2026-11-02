"""memebot x context (02-nov): tighten-only merge of the hourly snapshot, richer candidate rows (rid / veto_class / ctx / score_brain / st_f /
smart_flags / rt_src / whale fields / insider age), learn-thread + director wiring that adapts to the installed signatures (brain v3 cfg_base,
director ctx=), status() extras, startup seed hook. Offline: fake modules, SimpleNamespace bots or a real Meme in a tmp cwd with every network
call patched out; the same cycle runs with the context module absent (everything null, nothing tightened or loosened)."""
import json, os, time, types, datetime as dt
import pytest
import memebot, director, brain, news, solanatracker, eval_solana

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_KEYS = ("thr", "score_adj", "size_mult", "equity", "n_pos")   # ctx keys the bot fills even without a snapshot


class NS(types.SimpleNamespace):
    pass


def snapshot(now=None, **over):
    """a data/context_now.json document as context.py writes it (schema from the 02-nov task)"""
    now = now or time.time()
    d = {"ts": now - 120, "code": "context/1", "hour_utc": 9, "dow": 0,
         "sol": {"usd": 150.0, "r1h": 0.1, "r4h": 0.5, "r24h": 3.0, "rv24h": 1.2},
         "btc": {"usd": 70000.0, "r1h": 0.0, "r4h": 0.2, "r24h": 1.0, "rv24h": 0.8, "regime": "bull", "regime_age_s": 3600},
         "news": {"risk_off": False, "fng": 42, "sentiment": 0.1, "sources_ok": 4, "age_s": 60},
         "market": {"new_pools_1h": 30, "graduations_1h": 5, "agg_vol_h1_usd": 1e6, "n_cands_1h": 12, "heat": "normal", "heat_ratio": 1.05},
         "breadth": {"n_entry": 2, "n_universe": 40, "share": 0.05, "med_atr_ratio": 1.0}, "hl": {"sol_bias": None, "btc_bias": None, "stress": None},
         "health": {"insider_age_s": 30, "st_budget_used": 10, "st_budget_cap": 300, "x_buzz_age_s": None, "brain_active": False, "director_shadow": True},
         "regime": {"sol_trend": "up", "btc_on": True, "risk_off": False, "heat": "normal"}, "stale": []}
    d.update(over); return d


def fake_context(monkeypatch, snap, calls=None):
    """a context module with the load / stamp contract; calls (list) records the stamp kwargs the bot passes"""
    m = types.ModuleType("context")
    m.load = lambda root=".", max_age=7200: snap
    def stamp(s, thr=None, score_adj=None, size_mult=None, equity=None, n_pos=None, now=None):
        if calls is not None: calls.append(dict(thr=thr, score_adj=score_adj, size_mult=size_mult, equity=equity, n_pos=n_pos))
        return {"ts": s["ts"], "age_s": int((now or time.time()) - s["ts"]), "sol_24h": s["sol"]["r24h"], "sol_4h": s["sol"]["r4h"], "sol_trend": s["regime"]["sol_trend"],
                "btc_on": s["regime"]["btc_on"], "risk_off": s["regime"]["risk_off"], "fng": s["news"]["fng"], "heat": s["market"]["heat"], "heat_ratio": s["market"]["heat_ratio"],
                "new_pools_1h": s["market"]["new_pools_1h"], "breadth": s["breadth"]["share"], "hour_utc": s["hour_utc"], "dow": s["dow"],
                "thr": thr, "score_adj": score_adj, "size_mult": size_mult, "equity": equity, "n_pos": n_pos}
    m.stamp = stamp
    monkeypatch.setattr(memebot, "context", m)
    return m


# ---------------------------------------------------------------- pure helpers
def test_merge_regime_is_tighten_only():
    M = memebot.merge_regime
    assert M(True, False, snapshot(regime={"btc_on": False}))[0] is False                     # old True / ctx False -> False
    assert M(False, False, snapshot(regime={"btc_on": True}))[0] is False                     # old False / ctx True -> stays False (never loosened)
    assert M(True, False, snapshot(regime={"btc_on": None}))[0] is True                       # ctx None -> old
    assert M(None, None, snapshot(regime={"btc_on": False}))[0] is False                      # unknown + ctx False -> False (tighter)
    assert M(True, False, None) == (True, False) and M(True, False, "junk") == (True, False) and M(None, None, {}) == (None, None)   # no snapshot: old values
    assert M(True, False, snapshot(regime={"risk_off": True}))[1] is True                     # old False / ctx True -> True
    assert M(True, True, snapshot(regime={"risk_off": False}))[1] is True                     # old True / ctx False -> stays True
    assert M(True, False, snapshot(regime={"risk_off": None}, news={"risk_off": True}))[1] is True   # regime null -> news.risk_off
    assert M(True, False, snapshot(regime={}))[1] is False and M(True, None, snapshot(regime={}))[1] is None
    assert M(True, False, snapshot(regime="bad", news=None)) == (True, False)                 # malformed blocks: ignored


def test_veto_class_maps_hard_policy_soft_and_unknown_is_hard():
    hard = ["liq", "mint_authority", "freeze_authority", "lp_unlocked", "dev_rug_history", "transfer_tax", "few_holders", "rugcheck_unavailable", "rc_score35",
            "rc_score_missing", "rugcheck_danger:x|y", "stable_impersonator", "brand_impersonator", "stablecoin", "scam_data_unavailable", "scam_error", "too_new0.5h",
            "blacklisted_creator", "wash_traders3/300", "lp_unlocked40", "dev_holds12%", "insiders7", "no_buy_route", "no_sell_route", "hardfail_recent", "something_new"]
    policy = ["no_momentum_m5", "no_momentum", "news_negative", "insider_negative", "st_conc30.0%", "st_st_rugged", "director_gate", "score<55", "brain_ev<=0",
              "honeypot/high_tax", "honeypot_rt4.2", "no_sellability_check", "already_pumped_h1", "pump_paper_only"]
    vc = memebot.veto_class(hard + policy + ["top10"])
    assert all(vc[k] == "hard" for k in hard) and all(vc[k] == "policy" for k in policy) and vc["top10"] == "soft"
    assert memebot.veto_class([]) == {} and memebot.veto_class(None) == {}


def test_ctx_stamp_is_null_without_snapshot_and_delegates_with_one(monkeypatch):
    monkeypatch.setattr(memebot, "context", None)
    st = memebot.ctx_stamp(None, thr=55, score_adj=0, size_mult=0.8, equity=100.0, n_pos=1)
    assert set(st) == set(memebot.CTX_KEYS) and st["age_s"] is None
    assert all(st[k] is None for k in memebot.CTX_KEYS if k not in BOT_KEYS) and [st[k] for k in BOT_KEYS] == [55, 0, 0.8, 100.0, 1]
    assert memebot.ctx_stamp(snapshot(), thr=1)["sol_trend"] is None                       # snapshot but no module: still null
    m = fake_context(monkeypatch, None)
    assert memebot.ctx_stamp(None, thr=1)["age_s"] is None                                  # module but no snapshot
    calls = []; m = fake_context(monkeypatch, snapshot(), calls)
    st = memebot.ctx_stamp(snapshot(), thr=60, score_adj=-5, size_mult=1.0, equity=48.0, n_pos=0)
    assert st["sol_trend"] == "up" and st["fng"] == 42 and st["heat_ratio"] == 1.05 and st["thr"] == 60 and st["age_s"] >= 100 and set(st) >= set(memebot.CTX_KEYS)
    assert calls == [dict(thr=60, score_adj=-5, size_mult=1.0, equity=48.0, n_pos=0)]
    m.stamp = lambda *a, **k: 1 / 0                                                         # broken stamp: null dict, no exception
    st = memebot.ctx_stamp(snapshot(), thr=3); assert st["age_s"] is None and st["thr"] == 3


def test_st_subset_maps_the_real_solanatracker_feature_keys():
    now = time.time()
    tok = {"risk": {"snipers": {"totalPercentage": 4.5}, "bundlers": {"totalPercentage": 1.0}, "insiders": {"totalPercentage": 0.5}, "dev": {"percentage": 2.0}, "top10": 20, "rugged": False, "score": 10},
           "holders": 9000, "buys": 10, "sells": 5, "pools": [{"market": "raydium", "liquidity": {"usd": 60000}, "price": {"usd": 0.1}}],
           "token": {"mint": "M", "creation": {"created_time": now - 7200, "creator": "C"}}}
    dep = {"data": [{"mint": "X", "liquidityUsd": 0, "createdAt": (now - 86400) * 1000}, {"mint": "Y", "liquidityUsd": 5000, "createdAt": (now - 86400) * 1000}]}
    f = solanatracker.features(tok, dep, now=now)
    assert memebot.st_subset(f) == {"snipers_pct": 4.5, "bundlers_pct": 1.0, "insiders_pct": 0.5, "dev_pct": 2.0, "holders": 9000, "migrated": True, "age_h": 2.0, "creator_rugs": 1}
    assert memebot.st_subset(None) is None and memebot.st_subset("x") is None


def test_accepts_checks_keyword_or_var_kwargs():
    assert memebot._accepts(lambda a, ctx=None: 0, "ctx") and memebot._accepts(lambda a, **kw: 0, "ctx")
    assert not memebot._accepts(lambda a: 0, "ctx") and not memebot._accepts(object(), "ctx") and not memebot._accepts(len, "ctx")
    assert memebot._accepts(director.compute, "paths") and memebot._accepts(director.compute, "ctx")       # director v2 accepts paths/sim and ctx (merged 02-nov)


def test_hour_utc_is_utc():
    assert memebot.hour_utc(0) == 0 and memebot.hour_utc(5 * 3600 + 1) == 5 and memebot.hour_utc() == dt.datetime.now(dt.timezone.utc).hour


# ---------------------------------------------------------------- rows
def test_logc_enriches_only_full_rows_with_and_without_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); monkeypatch.setattr(memebot, "context", None)
    s = NS(equity=lambda: 500.0, pos={"H": {}}, smart={"M": {"ts": time.time() - 60, "flags": ["smart_buy"]}, "OLD": {"ts": time.time() - 4000, "flags": ["x"]}}, _ctx_doc=None)
    s.row_enrich = lambda rec: memebot.Meme.row_enrich(s, rec)
    short = {"ts": "2026-11-02T10:00:00", "mint": "S", "sym": "S", "src": "x", "liq": 1, "pass": False, "fail": ["liq"]}
    memebot.Meme.logc(s, dict(short))
    base = {"ts": "2026-11-02T10:00:00", "rid": "M:2026-11-02T10:00:00", "mint": "M", "sym": "M", "pass": False, "fail": ["score<55", "top10"], "roundtrip_loss_pct": None,
            "parts": {"whale_buys": 0, "whale_sells": 0, "bot_wallets": 0, "whales_fetched": False}}
    full = lambda **over: {**json.loads(json.dumps(base)), **over}                           # logc enriches in place: every row starts fresh
    memebot.Meme.logc(s, full())
    rows = [json.loads(l) for l in open("candidates_solana.jsonl")]
    assert rows[0] == short                                                                 # short rows (liq / hardfail_recent) stay short
    r = rows[1]
    assert r["veto_class"] == {"score<55": "policy", "top10": "soft"}
    assert set(r["ctx"]) == set(memebot.CTX_KEYS) and r["ctx"]["age_s"] is None and r["ctx"]["equity"] == 500.0 and r["ctx"]["n_pos"] == 1 and r["ctx"]["thr"] is None
    assert r["score_brain"] is None and r["st_f"] is None and r["rt_src"] is None and (r["whale_buys"], r["whale_sells"], r["bots"]) == (None, None, None)
    assert r["smart_flags"] == ["smart_buy"] and 0 <= r["hour_utc"] <= 23
    # with a snapshot, fetched whales, a measured round trip, a stale smart-money entry and an explicit (thr) stamp from the cycle
    snap = snapshot(); fake_context(monkeypatch, snap); s._ctx_doc = snap
    memebot.Meme.logc(s, full(mint="OLD", fail=[], roundtrip_loss_pct=1.3, score_brain=61.0, st_f={"holders": 1},
                             parts={"whale_buys": 2, "whale_sells": 1, "bot_wallets": 3, "whales_fetched": True}))
    r2 = json.loads(open("candidates_solana.jsonl").readlines()[-1])
    assert r2["ctx"]["sol_trend"] == "up" and r2["ctx"]["age_s"] >= 100 and r2["rt_src"] == "measured" and (r2["whale_buys"], r2["whale_sells"], r2["bots"]) == (2, 1, 3)
    assert r2["smart_flags"] is None and r2["score_brain"] == 61.0 and r2["st_f"] == {"holders": 1} and r2["veto_class"] == {}
    memebot.Meme.logc(s, full(ctx={"thr": 60, "age_s": 7}))
    assert json.loads(open("candidates_solana.jsonl").readlines()[-1])["ctx"] == {"thr": 60, "age_s": 7}
    s.smart = ["broken"]                                                                    # an enrich failure never loses the row
    memebot.Meme.logc(s, full(mint="Z"))
    r4 = json.loads(open("candidates_solana.jsonl").readlines()[-1]); assert r4["mint"] == "Z" and "veto_class" in r4


def test_score_logs_whales_as_not_fetched_unless_near_qualifier():
    calls = []
    s = NS(c={"min_score": 50}, seen={}, gpool={}, whales=lambda pair: calls.append(pair) or (2, 1, 3))
    rc = {"holders": 100, "top10": 10, "insiders": 0, "creator_bal": 0, "supply": 0, "verified": False}
    p = {"liquidity": {"usd": 100000}, "volume": {"h24": 1000}, "txns": {}, "priceChange": {}, "pairCreatedAt": time.time() * 1000, "pairAddress": "PAIR"}
    sc, comp = memebot.Meme.score(s, p, rc, "M")
    assert calls == [] and comp["whales_fetched"] is False and (comp["whale_buys"], comp["whale_sells"], comp["bot_wallets"]) == (0, 0, 0)   # parts keep 0 (brain.signals)
    assert comp["parts"]["whales"] == 0 and comp["parts"]["bots"] == 0 and brain.signals({"parts": comp, "liq": 1, "score": sc})["whale_buys"] is False
    p.update(volume={"h24": 1e6}, txns={"h1": {"buys": 100, "sells": 10}, "m5": {"buys": 50, "sells": 10}}, priceChange={"h1": 10, "m5": 1}, pairCreatedAt=(time.time() - 7200) * 1000)
    sc, comp = memebot.Meme.score(s, p, rc, "M")
    assert calls == ["PAIR"] and comp["whales_fetched"] is True and (comp["whale_buys"], comp["whale_sells"], comp["bot_wallets"]) == (2, 1, 3)
    assert comp["parts"]["whales"] == 3 and comp["parts"]["bots"] == -3
    row = {"rid": "x", "mint": "M", "fail": [], "parts": comp}; memebot.Meme.row_enrich(NS(equity=lambda: 1.0, pos={}), row)
    assert (row["whale_buys"], row["whale_sells"], row["bots"]) == (2, 1, 3)


def test_insider_feat_reports_file_age_even_when_stale(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = NS(); s.ins_st = lambda: memebot.Meme.ins_st(s)
    I = memebot.Meme.insider_feat(s, "M"); assert I["stale"] is True and I["age_s"] is None and I["conv"] == 0            # no file
    json.dump({"conv": {"M": {"score": 4, "n": 2, "elite": 1}}, "tokens": {}, "tok_valid": {}}, open("insider_status.json", "w"))
    s._ins_t = 0; I = memebot.Meme.insider_feat(s, "M"); assert I["stale"] is False and 0 <= I["age_s"] <= 5 and I["conv"] == 4
    old = time.time() - 1200; os.utime("insider_status.json", (old, old)); s._ins_t = 0
    I = memebot.Meme.insider_feat(s, "M"); assert I["stale"] is True and 1195 <= I["age_s"] <= 1210 and I["conv"] == 0   # stale: signal dropped as before, age kept
    open("insider_status.json", "w").write("{ broken"); s._ins_t = 0
    I = memebot.Meme.insider_feat(s, "M"); assert I["stale"] is True and I["age_s"] is not None and I["conv"] == 0


# ---------------------------------------------------------------- learn thread / director wiring
def test_learn_cycle_and_director_cycle_adapt_to_the_installed_signatures(monkeypatch):
    calls, comp = [], []
    class B2:   # brain v2: learn(cfg), no paths
        def learn(self, cfg): calls.append(("v2", cfg, None))
        def build_dataset(self, cfg, max_fetch=40): return []
    class B3:   # brain v3: learn(cfg, cfg_base=) + paths after learn
        paths = [([(1, 1, 1, 1, 1)], 1.0)]
        def learn(self, cfg, cfg_base=None): calls.append(("v3", cfg, cfg_base))
        def build_dataset(self, cfg, max_fetch=40): return [1]
    monkeypatch.setattr(director, "compute", lambda root, cfg, equity, sol_usd, now=None, data=None, paths=None, sim=None, prev=None, write=True: comp.append(dict(cfg=cfg, data=data, paths=paths, sim=sim)))
    s = NS(c={"min_score": 55}, c_base={"min_score": 50}, equity=lambda: 48.0, sol=100.0, brain=B2())
    s.director_cycle = lambda: memebot.Meme.director_cycle(s); s.ctx_load = lambda: memebot.Meme.ctx_load(s)
    memebot.Meme.learn_cycle(s, dict(s.c), dict(s.c_base))
    assert calls == [("v2", {"min_score": 55}, None)] and comp[-1] == dict(cfg={"min_score": 50}, data=[], paths=None, sim=None)   # old call, base config to the director
    s.brain = B3(); memebot.Meme.learn_cycle(s, dict(s.c), dict(s.c_base))
    assert calls[-1] == ("v3", {"min_score": 55}, {"min_score": 50}) and comp[-1]["paths"] == B3.paths and comp[-1]["sim"] is eval_solana.sim and comp[-1]["data"] == [1]
    seen = []   # a director that accepts ctx= gets the snapshot (None without one); today's director never sees the kwarg (above)
    monkeypatch.setattr(director, "compute", lambda root, cfg, equity, sol_usd, data=None, paths=None, sim=None, ctx=None, **k: seen.append(ctx))
    fake_context(monkeypatch, snapshot()); memebot.Meme.director_cycle(s); assert seen[-1]["regime"]["btc_on"] is True
    monkeypatch.setattr(memebot, "context", None); memebot.Meme.director_cycle(s); assert seen[-1] is None
    class BX:   # a failing brain never stops the director; a failing dataset means data=None
        def learn(self, cfg, cfg_base=None): raise RuntimeError("boom")
        def build_dataset(self, cfg, max_fetch=40): raise RuntimeError("no data")
    s.brain = BX(); memebot.Meme.learn_cycle(s, {}, {}); assert len(seen) == 3


def test_director_gate_uses_utc_hour_and_passes_ctx_only_when_accepted(monkeypatch):
    real, seen = director.entry_allowed, []
    monkeypatch.setattr(memebot, "hour_utc", lambda now=None: 7)
    monkeypatch.setattr(director, "entry_allowed", lambda c, h, n, play="scanner": seen.append((h, n, play, "noctx")) or (True, "ok"))
    s = NS(buys_today=lambda: 2); rec = {}
    assert memebot.Meme.director_gate(s, {"x": 1}, "scanner", rec, snapshot()) == (True, "ok") and seen[-1] == (7, 2, "scanner", "noctx") and rec["hour_utc"] == 7
    monkeypatch.setattr(director, "entry_allowed", lambda c, h, n, play="scanner", ctx=None: seen.append((h, n, play, ctx)) or (False, "director: hora 7 fuera de ventana"))
    ok, why = memebot.Meme.director_gate(s, {}, "pump", rec, snapshot())
    assert ok is False and "fuera de ventana" in why and seen[-1][2] == "pump" and seen[-1][3]["regime"]["heat"] == "normal"
    ok, _ = memebot.Meme.director_gate(s, {}, "scanner", rec, None); assert seen[-1][3] is None
    monkeypatch.setattr(director, "entry_allowed", real)                                     # today's director: windows are hours, now UTC
    assert memebot.Meme.director_gate(s, {"director_windows": [7]}, "scanner", rec)[0] and not memebot.Meme.director_gate(s, {"director_windows": [8]}, "scanner", rec)[0]


def test_seed_brain_context_uses_a_hook_only_when_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); os.makedirs("data")
    open("data/context.jsonl", "w").write(json.dumps({"ts": 1, "market": {"agg_vol_h1_usd": 5}}) + "\n{bad json\n" + json.dumps({"ts": 2}) + "\n")
    assert memebot.Meme.seed_brain_context(NS(brain=NS())) is False                          # a brain without the hook: nothing happens
    s = NS(brain=brain.Brain(str(tmp_path / "bs.json")))                                    # brain v3 has NO seed hook (02-nov review: the context measure differs from the bot's own)
    assert memebot.Meme.seed_brain_context(s) is False
    got = []; s.brain.seed_heat = lambda rows: got.append(rows)
    assert memebot.Meme.seed_brain_context(s) is True and [r["ts"] for r in got[0]] == [1, 2]
    s.brain.seed_heat = lambda rows: 1 / 0                                                  # a broken hook never breaks startup
    assert memebot.Meme.seed_brain_context(s) is False
    assert memebot.Meme.seed_brain_context(NS(brain=NS(seed_heat=lambda rows: got.append(rows))), path="data/none.jsonl") is False and len(got) == 1


# ---------------------------------------------------------------- a real Meme in a tmp folder (paper, every network call patched out)
def _meme(tmp_path, monkeypatch, **over):
    monkeypatch.chdir(tmp_path)
    cfg = json.load(open(os.path.join(ROOT, "config.json"))); cfg["exchanges"]["solana"].update(over); cfg["_path"] = str(tmp_path / "config.json")
    json.dump(cfg, open(cfg["_path"], "w"))
    monkeypatch.setattr(memebot, "get", lambda url, **k: None)                              # no network anywhere
    s = memebot.Meme(cfg, live=False); s.ai_scores, s.ai_watch, s.smart = {}, {}, {}
    return s


def test_status_has_context_fng_headlines_and_brain_extras(tmp_path, monkeypatch):
    s = _meme(tmp_path, monkeypatch)
    monkeypatch.setattr(news, "state", lambda: {"risk_off": False, "fng": {"value": 33, "label": "Fear"}, "top": [{"title": "Hack at X", "src": "CoinDesk"}, {"title": "Listing Y"}, {"src": "no title"}], "coin_block": {}, "coin_boost": {}})
    s.brain.st.update(model_choice="logit", calibration=[{"bin": "0-20%", "n": 3}], active_votes=2, code_version="brain/3")
    s.status(); st = json.load(open("status_solana.json"))                                  # no snapshot yet
    assert st["fng"] == 33 and st["headlines"] == ["Hack at X", "Listing Y"]
    assert st["context"] == {"fresh": False, "ts": None, "age_s": None, "regime": None, "heat_ratio": None, "stale_n": None}
    M = st["brain"]["model"]
    assert M["model_choice"] == "logit" and M["active_votes"] == 2 and M["code_version"] == "brain/3" and M["calibration"][0]["n"] == 3 and "updated" in M and "weights" in M
    s._ctx_doc = snapshot(stale=["hl.stress"]); s.status(); st = json.load(open("status_solana.json"))
    assert st["fng"] == 42 and st["context"]["fresh"] is True and 100 <= st["context"]["age_s"] <= 200 and st["context"]["regime"]["sol_trend"] == "up"
    assert st["context"]["stale_n"] == 1 and st["context"]["heat_ratio"] == 1.05
    for k in ("model_choice", "calibration", "active_votes", "code_version"): s.brain.st.pop(k)
    monkeypatch.setattr(news, "state", lambda: 1 / 0)                                        # brain v2 + broken news: keys absent, nothing invented, no exception
    s.status(); st = json.load(open("status_solana.json"))
    assert "model_choice" not in st["brain"]["model"] and st["headlines"] == [] and st["fng"] == 42


def _scan_setup(s, monkeypatch, scores):
    """two candidates through the real _scan_cycle: prefilter, cached RugCheck, scoring (patched), brain.decide (real), ST (patched), honeypot
    (patched), director gate, scam (patched) and the buy (patched). Returns the recorded buys."""
    def pair(mint, sym):
        return {"baseToken": {"address": mint, "symbol": sym, "name": sym.title() + " Coin"}, "dexId": "raydium", "priceUsd": "0.01", "pairAddress": "PAIR" + sym, "url": "u",
                "liquidity": {"usd": 120000}, "volume": {"h1": 50000, "h24": 900000}, "txns": {"h1": {"buys": 300, "sells": 100}, "m5": {"buys": 40, "sells": 10}},
                "priceChange": {"h1": 8, "m5": 2}, "pairCreatedAt": (time.time() - 7200) * 1000, "marketCap": 1e6, "info": {}}
    rc = {"mint_auth": None, "freeze_auth": None, "top10": 12.0, "lp_locked": 100.0, "rugged": False, "score_norm": 5, "holders": 9000, "dec": 6, "creator": "CR", "creator_bal": 0,
          "supply": 1e9, "verified": False, "fee_pct": 0, "insiders": 0, "danger": [], "creator_rugs": 0}
    prs = {m: pair(m, m[:5].upper()) for m in scores}
    def scan():
        s.gctx, s.gpool = [], {}; return {m: "gecko_new_pools" for m in scores}
    s.scan, s.pairs = scan, lambda mints: dict(prs)
    s._rc, s._rc_fail = {m: (time.time(), dict(rc)) for m in scores}, {}
    comp = {"liq": 120000, "vol_liq": 7.5, "b_s": "300/100", "h1": 8, "m5": 2, "age_h": 2.0, "vel": 1.5, "ub5": 0, "ub1": 0, "holder_g": 0, "liq_g": 0, "top10_chg": 0,
            "whale_buys": 0, "whale_sells": 0, "bot_wallets": 0, "whales_fetched": False, "creator_pct": 0, "parts": {"vol_liq": 12, "buy_press": 12, "momentum": 12, "velocity": 8}}
    s.score = lambda p, rc_, m: (scores[m], json.loads(json.dumps(comp)))
    s.honeypot = lambda m, usd: (1.1, {"q": 1}); s.quote = lambda *a, **k: None
    s.brain.depth_curve = lambda q, m, u: ({50: 0.1, 200: 0.3, 1000: 0.9}, 1500)
    bought = []; s.buy = lambda m, p, sc, why: bought.append((m, sc, why, dict(p)))
    monkeypatch.setattr(memebot.scam, "check", lambda *a, **k: [])
    monkeypatch.setattr(solanatracker, "live_check", lambda m, sym=None: ([], 3.0, {"verdict": "pass", "why": [], "prio": 1, "f": {"snipers": 4.0, "bundlers": 1.0, "insiders": 0.5, "dev": 2.0, "holders": 9000, "migrated": True, "age_h": 2.0, "creator_rugs": 0}}))
    monkeypatch.setattr(news, "state", lambda: {"risk_off": False, "fng": {"value": 50}, "top": [], "coin_block": {}, "coin_boost": {}})
    return bought


def _rows():
    return {r["mint"]: r for r in (json.loads(l) for l in open("candidates_solana.jsonl"))}


def test_scan_cycle_rows_without_context_are_null_and_nothing_is_tightened(tmp_path, monkeypatch):
    monkeypatch.setattr(memebot, "context", None)
    s = _meme(tmp_path, monkeypatch, min_score=50)
    json.dump({"regime": {"regime": "bull"}}, open("status_binance.json", "w"))              # today's input: BTC on
    bought = _scan_setup(s, monkeypatch, {"MintAlpha11": 80.0, "MintBeta222": 40.0})
    s._scan_cycle()
    R = _rows(); a, b = R["MintAlpha11"], R["MintBeta222"]
    assert s._ctx_doc is None and len(R) == 2
    assert a["rid"] == f"MintAlpha11:{a['ts']}" and a["pass"] is True and a["score"] == 83.0 and a["score_brain"] == 80.0   # ST bonus after the brain saw 80
    assert a["st_f"] == {"snipers_pct": 4.0, "bundlers_pct": 1.0, "insiders_pct": 0.5, "dev_pct": 2.0, "holders": 9000, "migrated": True, "age_h": 2.0, "creator_rugs": 0}
    assert a["rt_src"] == "measured" and a["roundtrip_loss_pct"] == 1.1 and a["veto_class"] == {} and a["fail"] == []
    assert (a["whale_buys"], a["whale_sells"], a["bots"]) == (None, None, None) and a["parts"]["whale_buys"] == 0 and a["smart_flags"] is None
    assert a["insider"]["stale"] is True and a["insider"]["age_s"] is None and a["hour_utc"] == memebot.hour_utc()
    assert set(a["ctx"]) == set(memebot.CTX_KEYS) and a["ctx"]["age_s"] is None and a["ctx"]["sol_trend"] is None and a["ctx"]["thr"] == 50 and a["ctx"]["equity"] == 1000.0 and a["ctx"]["n_pos"] == 0
    assert b["pass"] is False and b["veto_class"] == {"no_sellability_check": "policy"} and b["rt_src"] is None and b["score_brain"] == 40.0 and b["ctx"]["thr"] == 50
    assert len(bought) == 1 and bought[0][0] == "MintAlpha11" and bought[0][1] == 83.0
    p = bought[0][3]; assert p["_btc_on"] is True and p["_riskoff"] is False and p["_smult"] == 0.8      # unchanged inputs: nothing tightened or loosened


def test_scan_cycle_with_context_stamps_rows_and_merges_tighten_only(tmp_path, monkeypatch):
    calls = []; snap = snapshot(regime={"sol_trend": "up", "btc_on": False, "risk_off": True, "heat": "normal"}); fake_context(monkeypatch, snap, calls)
    s = _meme(tmp_path, monkeypatch, min_score=50)
    json.dump({"regime": {"regime": "bull"}}, open("status_binance.json", "w"))              # today's input says BTC on; the snapshot says off -> off
    bought = _scan_setup(s, monkeypatch, {"MintAlpha11": 80.0, "MintBeta222": 40.0})
    s._scan_cycle()
    R = _rows(); a, b = R["MintAlpha11"], R["MintBeta222"]
    assert s._ctx_doc is snap and len(bought) == 1
    p = bought[0][3]; assert p["_btc_on"] is False and p["_riskoff"] is True and p["_smult"] == 0.64       # tighten-only merge reached the executor inputs
    assert a["ctx"]["thr"] == 60 and a["ctx"]["sol_trend"] == "up" and a["ctx"]["btc_on"] is False and a["ctx"]["risk_off"] is True and a["ctx"]["fng"] == 42 and a["ctx"]["age_s"] >= 100
    assert calls and calls[0] == dict(thr=60, score_adj=0, size_mult=0.64, equity=1000.0, n_pos=0)   # context.stamp contract
    assert b["pass"] is False and b["ctx"]["thr"] == 60 and b["ctx"]["heat_ratio"] == 1.05 and b["veto_class"] == {"no_sellability_check": "policy"}
    assert a["st"]["ok"] is True and a["st_f"]["migrated"] is True and a["hour_utc"] == memebot.hour_utc()
    st = json.load(open("status_solana.json")) if os.path.exists("status_solana.json") else None
    s.status(); st = json.load(open("status_solana.json"))
    assert st["context"]["fresh"] is True and st["context"]["regime"]["btc_on"] is False and st["fng"] == 42


def test_scan_cycle_survives_a_broken_context_module(tmp_path, monkeypatch):
    m = types.ModuleType("context"); m.load = lambda root=".", max_age=7200: 1 / 0; m.stamp = lambda *a, **k: 1 / 0
    monkeypatch.setattr(memebot, "context", m)
    s = _meme(tmp_path, monkeypatch, min_score=50)
    bought = _scan_setup(s, monkeypatch, {"MintAlpha11": 80.0})
    s._scan_cycle()
    a = _rows()["MintAlpha11"]
    assert s._ctx_doc is None and a["ctx"]["age_s"] is None and a["ctx"]["thr"] == 50 and len(bought) == 1 and bought[0][3]["_btc_on"] is None


def test_brain_active_gate_uses_score_brain_not_the_bonus_adjusted_score():
    """02-nov review: a +9 X/ST bonus must not lift a sub-floor score_brain past brain_min_score on the brain-active path"""
    src = open(os.path.join(os.path.dirname(memebot.__file__), "memebot.py"), encoding="utf-8").read()
    line = next(l for l in src.splitlines() if 'elif dec and dec["active"]: rec["pass"]' in l)
    assert 'rec.get("score_brain")' in line and 'and sc >= c.get("brain_min_score"' not in line
