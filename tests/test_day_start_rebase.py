"""Fresh LIVE install (--live, no state file): the daily-stop baseline must come from the wallet, not from config starting_equity."""
import types
import memebot


class NS(types.SimpleNamespace):
    def equity(s): return s.cash + sum(p.get("mark", p["entry"]) * p["raw"] / 10 ** p["dec"] for p in s.pos.values())
    def save(s): s.saved = getattr(s, "saved", 0) + 1


def mk(**o):
    d = dict(live=True, wallet={"sol": 0.57}, cash=96.0, pos={}, c={"starting_equity": 1000}, day_start=1000.0, halted=False, _fresh_live=True, saved=0, _reconciled_t=1.0)
    d.update(o); return NS(**d)


def test_fresh_live_rebases_to_wallet_equity():
    s = mk(); assert memebot.Meme.rebase_day_start(s) is True
    assert s.day_start == 96.0 and s._fresh_live is False and s.saved == 1
    assert memebot.Meme.rebase_day_start(s) is False                      # once


def test_saved_bogus_baseline_is_repaired_and_halt_cleared():
    s = mk(_fresh_live=False, halted=True)                                 # state saved after the day-1 false KILL SWITCH
    assert memebot.Meme.rebase_day_start(s) is True and s.day_start == 96.0 and s.halted is False


def test_real_baseline_and_real_halt_are_untouched():
    s = mk(_fresh_live=False, day_start=96.0, cash=90.0, halted=True)      # a genuine -6 % day
    assert memebot.Meme.rebase_day_start(s) is False and s.day_start == 96.0 and s.halted is True
    s = mk(_fresh_live=False, day_start=1000.0, cash=980.0)                # baseline equals config but the wallet really is ~1000 $
    assert memebot.Meme.rebase_day_start(s) is False and s.day_start == 1000.0


def test_no_wallet_or_paper_never_rebases():
    assert memebot.Meme.rebase_day_start(mk(wallet=None)) is False
    assert memebot.Meme.rebase_day_start(mk(live=False)) is False


def test_halt_with_open_positions_stays_until_flat():
    s = mk(_fresh_live=False, halted=True, pos={"M": {"entry": 1.0, "raw": 10 ** 6, "dec": 6}})
    assert memebot.Meme.rebase_day_start(s) is True and s.halted is True   # kill-switch flatten keeps running; baseline fixed


def test_never_rebases_before_a_successful_wallet_read():
    s = mk(_reconciled_t=0.0, cash=0.0)
    assert memebot.Meme.rebase_day_start(s) is False and s.day_start == 1000.0 and s._fresh_live is True   # waits for the real read
