"""Tests for the 2026-10-31 memebot fixes (see DECISIONS.md). Every test runs offline with fake modules / namespaces."""
import json, os, sys, time, types
import pytest
import memebot, scam


class NS(types.SimpleNamespace):
    pass


def fake_live_sol(monkeypatch, **over):
    m = types.ModuleType("live_sol")
    m.SOL = "So11111111111111111111111111111111111111112"
    m.calls = {"sellable": [], "swap": 0}
    m.quote = lambda inp, out, lam, slip: {"outAmount": "1000000", "otherAmountThreshold": "990000", "priceImpactPct": "0.001"}
    m.slippage_bps = lambda size, liq, imp=0.0, urgent=False: 100
    def sellable(mint, raw_out, slip, max_rt, lam):
        m.calls["sellable"].append(raw_out); return True, "rt=0.30%"
    m.sellable = sellable
    m.token_balances = lambda: {}
    m.sol_balance = lambda: 1.0
    def swap(q): m.calls["swap"] += 1; raise RuntimeError("stop here: swap is not under test")
    m.swap = swap
    m.tx_fee_sol = lambda sig: 0.0
    for k, v in over.items(): setattr(m, k, v)
    monkeypatch.setitem(sys.modules, "live_sol", m)
    return m


def test_live_ev_gate_measures_round_trip_on_expected_fill(monkeypatch):
    ls = fake_live_sol(monkeypatch)
    s = NS(sol=100.0, c={"max_roundtrip_loss_pct": 3}, pos={}, seen={}, live=True)
    p = {"baseToken": {"symbol": "X"}, "liquidity": {"usd": 100000}, "_ev": 1.0, "_dec": 6}
    assert memebot.Meme._buy_live(s, "MINT", p, 50, "why", 4.0) is None   # swap raised -> returns None
    assert ls.calls["sellable"] == [1000000]                               # outAmount, not the 990000 threshold
    assert ls.calls["swap"] == 1                                           # the EV gate let the buy through (1.0 >= 3 x 0.30)


def test_live_ev_gate_still_blocks_when_ev_too_small(monkeypatch):
    ls = fake_live_sol(monkeypatch)
    s = NS(sol=100.0, c={"max_roundtrip_loss_pct": 3}, pos={}, seen={}, live=True)
    p = {"baseToken": {"symbol": "X"}, "liquidity": {"usd": 100000}, "_ev": 0.5, "_dec": 6}
    assert memebot.Meme._buy_live(s, "MINT", p, 50, "why", 4.0) is None
    assert ls.calls["swap"] == 0                                           # 0.5 < 3 x 0.30 -> blocked, no swap
    p["_ev"] = None
    memebot.Meme._buy_live(s, "MINT", p, 50, "why", 4.0)
    assert ls.calls["swap"] == 0                                           # unknown EV stays fail-closed


def test_sell_live_late_landing_check_is_correct_for_partial_sells(monkeypatch):
    state = {"n": 0, "after": 1000}
    def token_balances():                      # first read = balance before the swap (bal0), later reads = after the failed attempt
        state["n"] += 1; return {"MINT": (1000 if state["n"] == 1 else state["after"], 6)}
    def quote(*a): raise RuntimeError("swap failed")
    fake_live_sol(monkeypatch, token_balances=token_balances, quote=quote)
    monkeypatch.setattr(memebot.time, "sleep", lambda t: None)
    s = NS(sol=100.0, c={}, pos={"MINT": {"sym": "X", "raw": 1000, "dec": 6, "entry": 1.0, "mark": 1.0}})
    # balance unchanged after the failed swap -> the 33% partial sell is NOT reported as filled
    assert memebot.Meme.sell_live(s, "MINT", "protect_spike", 330) is None
    # balance dropped by exactly the partial amount -> filled (late landing)
    state.update(n=0, after=670)
    got, sig = memebot.Meme.sell_live(s, "MINT", "protect_spike", 330)
    assert sig == "late_landing" and got > 0
    # the old rule (balance < 1% of raw) would have needed the WHOLE position to be gone: 670 is not < 3.3
    state.update(n=0, after=10)                                           # full sell of 1000 with 10 dust left -> still filled
    got, sig = memebot.Meme.sell_live(s, "MINT", "stop", 1000)
    assert sig == "late_landing"


def test_writeoff_due_requires_every_condition():
    s = NS(c={}, _rd_last={"MINT": {"liquidity": {"usd": 0}}}, quote=lambda *a, **k: {"outAmount": "1"})
    p = {"sellfail": 5, "noroute": 10, "fail_t": time.time()-1000}
    assert memebot.Meme.writeoff_due(s, "MINT", p) is True
    s.quote = lambda *a, **k: None                                         # Jupiter down: never write off
    assert memebot.Meme.writeoff_due(s, "MINT", p) is False
    s.quote = lambda *a, **k: {"outAmount": "1"}
    s._rd_last = {"MINT": {"priceUsd": "0.1"}}                             # DexScreener row without a liquidity figure: not evidence
    assert memebot.Meme.writeoff_due(s, "MINT", p) is False
    s._rd_last = {"MINT": {"liquidity": {"usd": 0}}}
    assert memebot.Meme.writeoff_due(s, "MINT", dict(p, sellfail=4)) is False
    assert memebot.Meme.writeoff_due(s, "MINT", dict(p, noroute=3)) is False
    assert memebot.Meme.writeoff_due(s, "MINT", dict(p, fail_t=time.time())) is False
    assert memebot.Meme.writeoff_due(s, "MINT", p, frac=0.5) is False
    s._rd_last = {}                                                        # DexScreener outage: never write off
    assert memebot.Meme.writeoff_due(s, "MINT", p) is False
    s._rd_last = {"MINT": {"liquidity": {"usd": 50000}}}                   # pool alive: never write off
    assert memebot.Meme.writeoff_due(s, "MINT", p) is False


def test_sell0_writes_off_dead_live_position_and_blocks_readoption():
    rec = []
    s = NS(live=True, sol=100.0, cash=10.0, trades=[], seen={}, c={"slippage_bps": 300}, _rd_last={"MINT": {"liquidity": {"usd": 0}}},
           pos={"MINT": {"sym": "DEAD", "raw": 1000, "dec": 6, "cost": 4.0, "entry": 1.0, "noroute": 9, "sellfail": 4, "fail_t": time.time()-2000}},
           quote=lambda inp, out, amt, slip=300: ({"outAmount": "1"} if inp == memebot.USDC else None), sell_live=lambda m, r, raw: None, net_fee_usd=lambda: 0.01, reconcile=lambda *a, **k: None,
           save=lambda: None, record=lambda *a: rec.append(a))
    s.writeoff_due = lambda m, p, frac=1.0: memebot.Meme.writeoff_due(s, m, p, frac)
    memebot.Meme._sell0(s, "MINT", "kill_switch")
    assert "MINT" not in s.pos and "MINT" in s.dead
    assert rec and rec[0][1] == "SELL" and "WRITEOFF" in rec[0][6] and rec[0][5] == pytest.approx(-4.01)   # record(sym, side, px, qty, fee, pnl, reason)
    assert s.trades == [pytest.approx(-4.01)] and s.seen["MINT"]["cool"] > time.time()   # loss cooldown applied


def test_rug_parse_error_is_fail_closed(monkeypatch):
    monkeypatch.setattr(memebot, "get", lambda url, **k: {"markets": "not-a-list", "topHolders": [{"pct": None}]})
    s = NS(c={}, rug_fallback=lambda m: "FALLBACK")
    assert memebot.Meme.rug(s, "MINT") is None                            # malformed report -> None, no exception


def test_rug_falls_back_when_rugcheck_has_no_report(monkeypatch):
    monkeypatch.setattr(memebot, "get", lambda url, **k: None)
    s = NS(c={}, rug_fallback=lambda m: {"src": "goplus"})
    assert memebot.Meme.rug(s, "MINT") == {"src": "goplus"}


def test_reload_keeps_previous_config_when_file_is_broken(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # 02-nov: reload() applies ./director_state.json; on a live machine the real Director (out of shadow) tightens size_pct
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"exchanges": {"solana": {"exit_mode": "trail", "size_pct": 8}}}))
    s = NS(cfg_path=str(cfg), mt=0)
    memebot.Meme.reload(s)
    assert s.c["size_pct"] == 8
    cfg.write_text("{ broken json"); os.utime(cfg, (time.time()+5, time.time()+5))
    memebot.Meme.reload(s)                                                 # must not raise
    assert s.c["size_pct"] == 8


def test_honeypot_does_not_cache_missing_quotes():
    answers = [(None, "no_buy_route"), (1.2, {"q": 1})]
    s = NS(_ttl={}, _honeypot=lambda *a: answers.pop(0))
    assert memebot.Meme.honeypot(s, "MINT", 100) == (None, "no_buy_route")
    assert not s._ttl                                                      # outage-like answer not cached
    assert memebot.Meme.honeypot(s, "MINT", 100) == (1.2, {"q": 1})
    assert s._ttl[("honeypot", "MINT", 100)][1] == (1.2, {"q": 1})         # definitive answer cached


def test_eval_slots_skip_recent_deterministic_vetoes_but_never_positions_or_insiders():
    now = time.time()
    s = NS(pos={}, _hardfail={"a": (now, 3600), "c": (now, 3600), "d": (now-7200, 3600)})
    keep, skipped = memebot.Meme.eval_slots(s, ["a", "b", "c", "d", "e"], {"a": "dex", "b": "dex", "c": "insider", "d": "dex", "e": "dex"}, {"max_eval_per_cycle": 3})
    assert skipped == ["a"] and keep == {"b", "c", "d"}                    # c is insider-sourced, d expired, e beyond the cap
    s.pos = {"a": {}}
    keep, skipped = memebot.Meme.eval_slots(s, ["a", "b"], {"a": "dex", "b": "dex"}, {})
    assert skipped == [] and keep == {"a", "b"}


def test_scam_check_is_fail_closed_without_any_data(monkeypatch):
    monkeypatch.setattr(scam, "_get", lambda url, ttl=600, **p: None)
    monkeypatch.setattr(scam, "blacklist", lambda: set())
    assert "scam_data_unavailable" in scam.check("MINT", "ABC", 0.5, {})


def test_pump_play_default_is_off():
    src = open(memebot.__file__).read()
    assert 'c.get("pump_play", True)' not in src and src.count('c.get("pump_play", False)') == 3


def test_stamp_hardfail_ttl_by_veto_and_never_from_goplus():
    s = NS(_hardfail={}, HARD_PERM=memebot.Meme.HARD_PERM, HARD_SLOW=memebot.Meme.HARD_SLOW)
    memebot.Meme.stamp_hardfail(s, "a", ["mint_authority"], {"src": "rugcheck"}, {})
    memebot.Meme.stamp_hardfail(s, "b", ["lp_unlocked"], {}, {})
    memebot.Meme.stamp_hardfail(s, "c", ["lp_unlocked"], {"src": "goplus+rpc"}, {})
    memebot.Meme.stamp_hardfail(s, "d", ["top10"], {}, {})
    assert s._hardfail["a"][1] == 3600 and s._hardfail["b"][1] == 900 and "c" not in s._hardfail and "d" not in s._hardfail


def test_sell0_backs_off_after_repeated_failed_swaps():
    calls = []
    s = NS(live=True, sol=100.0, cash=10.0, trades=[], seen={}, c={"slippage_bps": 300}, _rd_last={},
           pos={"MINT": {"sym": "FRZ", "raw": 1000, "dec": 6, "cost": 4.0, "entry": 1.0, "sellfail": 4, "fail_last": time.time()}},
           quote=lambda *a, **k: calls.append("quote") or {"outAmount": "3900000"}, sell_live=lambda m, r, raw: None, net_fee_usd=lambda: 0.01,
           reconcile=lambda *a, **k: None, save=lambda: None, record=lambda *a: None, writeoff_due=lambda m, p, frac=1.0: False)
    memebot.Meme._sell0(s, "MINT", "stop")
    assert calls == []                                                     # inside the back-off window: no quote, no swap
    s.pos["MINT"]["fail_last"] = time.time()-3600
    memebot.Meme._sell0(s, "MINT", "stop")
    assert calls == ["quote"] and s.pos["MINT"]["sellfail"] == 5           # window over: one more attempt, counted


def test_rent_is_booked_at_full_exit_not_in_stop_basis():
    rec = []
    s = NS(live=True, sol=100.0, cash=10.0, trades=[], seen={}, c={"slippage_bps": 300}, _rd_last={},
           pos={"MINT": {"sym": "X", "raw": 1000, "dec": 6, "cost": 4.0, "entry": 1.0, "rent_usd": 0.2}},
           quote=lambda *a, **k: {"outAmount": "4100000"}, sell_live=lambda m, r, raw: (4.1, "sig"), net_fee_usd=lambda: 0.01,
           reconcile=lambda *a, **k: None, save=lambda: None, record=lambda *a: rec.append(a))
    import sys, types
    ls = types.ModuleType("live_sol"); ls.tx_fee_sol = lambda sig: None; sys.modules["live_sol"] = ls
    try: memebot.Meme._sell0(s, "MINT", "trail12")
    finally: sys.modules.pop("live_sol", None)
    assert rec[0][5] == pytest.approx(4.1-0.01-4.0-0.2) and "rent=0.20" in rec[0][6]   # pnl includes the rent, the stop never saw it


# ---------------------------------------------------------------- Director integration (director.py)
def test_meme_apply_director_tightens_and_ignores_stale_state(tmp_path, monkeypatch):
    import director
    monkeypatch.chdir(tmp_path)
    base = {"min_score": 45, "size_pct": 8, "live_target_max_usd": 5, "live_target_min_usd": 3, "hard_stop_pct": 6, "trail_pct_tt": 12, "pump_paper": True, "pump_play": False}
    s = NS(c=dict(base))
    assert memebot.Meme.apply_director(s, base) == base                                   # no state file: base config
    st = {"ts": time.time(), "shadow": False, "plays": {"scanner": "on", "insider_elite": "off", "pump": "off"}, "min_score_eff": 55, "ev_min_eff": 0.02,
          "size_policy": {"target_usd": 3.84, "max_frac": 0.08}, "exit_profile": {"hard_stop_pct": 5.0, "trail_pct": 10.0}, "windows": [10, 11, 12], "max_trades_day": 4}
    json.dump(st, open("director_state.json", "w"))
    c = memebot.Meme.apply_director(NS(), base)
    assert c["min_score"] == 55 and c["brain_ev_min"] == 0.02 and c["live_target_max_usd"] == 3.84 and c["hard_stop_pct"] == 5.0 and c["trail_pct_tt"] == 10.0
    assert c["pump_paper"] is False and c["pump_play"] is False and c["director_windows"] == [10, 11, 12] and c["director_max_trades_day"] == 4
    assert director.entry_allowed(c, 11, 0, "insider_elite") == (False, "director: jugada insider_elite apagada") and director.entry_allowed(c, 11, 0)[0]
    assert memebot.Meme.apply_director(NS(), dict(base, director_enabled=False)) == dict(base, director_enabled=False)   # owner's off switch
    json.dump(dict(st, ts=time.time() - 4 * 3600), open("director_state.json", "w"))
    assert memebot.Meme.apply_director(NS(), base) == base                                  # stale (> 3 h): base config again


def test_ata_sweep_queues_only_fully_sold_live_mints_and_retries_failures(monkeypatch):
    calls = []
    def close_empty_atas(dry_run, only, skip): calls.append((set(only), set(skip))); return {"closed": len(only) - 1, "sol_recovered": 0.002, "failed": [(sorted(only)[0], "boom")], "found": len(only), "mints": sorted(only), "dry_run": dry_run}
    fake_live_sol(monkeypatch, close_empty_atas=close_empty_atas)
    class T:   # run the thread body inline
        def __init__(self, target, daemon): self.t = target
        def start(self): self.t()
        def is_alive(self): return False
    monkeypatch.setattr(memebot.threading, "Thread", T)
    s = NS(live=True, c={}, pos={"HELD": {}}, _ata_q={"A": {"t": time.time() - 60, "n": 0}, "B": {"t": time.time() - 60, "n": 0}, "HELD": {"t": time.time() - 60, "n": 0}, "NEW": {"t": time.time(), "n": 0}})
    import os, tempfile; d = tempfile.mkdtemp(); os.chdir(d)
    memebot.Meme.ata_sweep(s)
    assert calls == [({"A", "B"}, {"HELD"})]                                              # held and too-recent mints are never touched
    assert "B" not in s._ata_q and s._ata_q["A"]["n"] == 1 and "HELD" in s._ata_q and "NEW" in s._ata_q
    assert os.path.exists("research/ata_close.jsonl")
    s.pos = {}; s._ata_q["A"]["t"] = time.time() - 60; s._ata_q["A"]["n"] = 2
    memebot.Meme.ata_sweep(s); assert "A" not in s._ata_q                                   # third failure: dropped with a warning
    s2 = NS(live=False, c={}, pos={}, _ata_q={"X": {"t": 0, "n": 0}}); calls.clear(); memebot.Meme.ata_sweep(s2); assert calls == []   # paper: never


def test_live_buy_impact_cap_is_configurable(monkeypatch):
    """owner 01-nov: max_buy_impact_pct (code default 5.0 after the merge with Grok's version; config 5.5)"""
    ls = fake_live_sol(monkeypatch, quote=lambda inp, out, lam, slip: {"outAmount": "1000000", "otherAmountThreshold": "990000", "priceImpactPct": "0.06"})
    p = {"baseToken": {"symbol": "X"}, "liquidity": {"usd": 100000}, "_ev": 5.0, "_dec": 6}
    s = NS(sol=100.0, c={"max_roundtrip_loss_pct": 3}, pos={}, seen={}, live=True)
    memebot.Meme._buy_live(s, "MINT", p, 50, "why", 4.0); assert ls.calls["swap"] == 0          # 6 % impact > default 5 %
    s = NS(sol=100.0, c={"max_roundtrip_loss_pct": 3, "max_buy_impact_pct": 7.0}, pos={}, seen={}, live=True)
    memebot.Meme._buy_live(s, "MINT", p, 50, "why", 4.0); assert ls.calls["swap"] == 1          # allowed up to the configured cap
