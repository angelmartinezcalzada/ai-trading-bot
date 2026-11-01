"""copytrade_rules (rug confirmation) and insider.pending_swaps (fail-closed cursor)."""
import insider
from copytrade_rules import rug_step, exit_reason

TP, SL, HOLD = 0.15, 0.08, 1800

def test_one_bad_print_arms_but_does_not_exit():
    q = {"e": 1.0, "t": 0, "liq": 60000}
    assert rug_step(q, 0.0, 0) is False and q["rug_n"] == 1
    assert exit_reason(q, False, 0.5, True, 10, TP, SL, HOLD) is None      # not even tp / insider_sell while pending confirmation
    assert rug_step(q, 0.0, 0) is True and q["rug_n"] == 2
    assert exit_reason(q, True, -1.0, False, 10, TP, SL, HOLD) == "rug"

def test_good_print_resets_counter_and_normal_exits_apply():
    q = {"e": 1.0, "t": 0, "liq": 60000}
    rug_step(q, 0.0, 0); assert rug_step(q, 1.2, 55000) is False and q["rug_n"] == 0
    assert exit_reason(q, False, 0.2, False, 10, TP, SL, HOLD) == "tp"
    assert exit_reason(q, False, -0.1, False, 10, TP, SL, HOLD) == "sl"
    assert exit_reason(q, False, 0.0, True, 10, TP, SL, HOLD) == "insider_sell"
    assert exit_reason(q, False, 0.0, False, 5000, TP, SL, HOLD) == "time"
    assert exit_reason(q, False, 0.0, False, 10, TP, SL, HOLD) is None

def test_liquidity_pull_needs_known_liquidity():
    q = {"e": 1.0, "t": 0, "liq": 60000}
    assert rug_step(q, 1.0, 0) is False and q["rug_n"] == 0                 # liquidity unknown (0) with a price: data gap, not a pull
    rug_step(q, 1.0, 5000); assert q["rug_n"] == 1                          # <20 % of entry liquidity: armed

def test_pending_swaps_retries_unfetched_tx_instead_of_skipping():
    sigs = [{"signature": "c"}, {"signature": "b"}, {"signature": "a"}]  # newest first
    done = ["a"]; calls = []
    def parse(sig): calls.append(sig); return None if sig == "b" else [{"sig": sig}]
    out = insider.pending_swaps(sigs, done, parse)
    assert calls == ["b", "c"] and out == [{"sig": "c"}] and done == ["a", "c"]   # b not marked: retried next cycle
    def parse2(sig): return [{"sig": sig}]
    assert insider.pending_swaps(sigs, done, parse2) == [{"sig": "b"}] and done == ["a", "c", "b"]

def test_pending_swaps_marks_errored_tx_and_bounds_memory():
    sigs = [{"signature": str(i), "err": (i == 3) or None} for i in range(100)]
    done = []; parsed = []
    out = insider.pending_swaps(sigs, done, lambda sig: parsed.append(sig) or [], keep=10)
    assert out == [] and "3" not in parsed and len(parsed) == 99 and len(done) == 10 and done == [str(i) for i in range(9, -1, -1)]
