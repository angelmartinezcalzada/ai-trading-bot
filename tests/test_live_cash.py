"""02-nov: REAL-mode cash comes only from a successful wallet read. Before, go_live kept the PAPER cash (starting_equity 1000 $) when the
first read failed, so a 4 % ALT buy would have been ~40 $ on a ~50 $ wallet. Offline (NS objects, no network)."""
import os, time, types
import memebot


class NS(types.SimpleNamespace):
    pass


def meme_ns(read_ok, sol_price=94.0, bal=0.5667):
    s = NS(live=False, cash=1000.0, c={"starting_equity": 1000, "sol_fee_reserve": 0.02, "max_position_pct": 0.1, "exit_mode": "trail", "size_pct": 8,
                                       "max_gap_loss_pct": 0.1, "live_min_trade_usd": 1, "position_pct": 0.05, "slippage_bps": 300},
           pos={}, trades=[], halted=False, day="2000-01-01", day_start=1000.0, seen={}, dead={}, sol=sol_price, _fresh_live=False,
           wallet={"addr": "WALLET", "sol": bal, "usd": bal * sol_price, "t": time.time()}, saved=0, state_file="state_solana_paper.json", csv="trades_solana_paper.csv")
    s.save = lambda: setattr(s, "saved", s.saved + 1)
    s.equity = lambda: s.cash + 0.0
    def reconcile(adopt=False):
        if not read_ok: return                                                    # RPC error: memebot.reconcile logs and returns
        s.cash = max(0.0, bal - 0.02) * s.sol; s._reconciled_t = time.time()
    s.reconcile = reconcile
    return s


def test_go_live_with_a_failed_wallet_read_has_zero_cash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); s = meme_ns(read_ok=False)
    memebot.Meme.go_live(s)
    assert s.live is True and s.cash == 0.0 and s._reconciled_t == 0.0 and s._fresh_live is True
    assert s.day_start == 1000.0                                                  # not set from cash 0; rebase_day_start fixes it after a real read


def test_go_live_with_a_good_read_uses_the_wallet(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); s = meme_ns(read_ok=True)
    memebot.Meme.go_live(s)
    assert abs(s.cash - (0.5667 - 0.02) * 94.0) < 1e-9 and s._reconciled_t > 0 and abs(s.day_start - s.cash) < 1e-9


def buy_ns(reconciled_ago, wallet_usd=50.0, equity=1000.0):
    s = NS(live=True, c={"exit_mode": "trail", "size_pct": 8, "max_gap_loss_pct": 0.1, "live_min_trade_usd": 1, "position_pct": 0.05,
                         "slippage_bps": 300, "max_position_pct": 0.1}, cash=equity, wallet={"usd": wallet_usd},
           _reconciled_t=(time.time() - reconciled_ago) if reconciled_ago is not None else 0.0, bought=[])
    s.equity = lambda: equity
    s.quote = lambda *a, **k: {"outAmount": "1000000"}
    s.buy_live = lambda m, p, sc, why, size: s.bought.append(size)
    return s


def test_real_buy_needs_a_fresh_wallet_read():
    for ago in (None, 400):
        s = buy_ns(ago); memebot.Meme.buy(s, "MINT", {"baseToken": {"symbol": "X"}, "_size": 2.0}, 50, "why")
        assert s.bought == []                                                     # never read / read > 5 min ago: no buy


def test_real_buy_never_exceeds_ten_percent_of_the_real_wallet():
    s = buy_ns(10, wallet_usd=50.0, equity=1000.0)                                # bogus equity 1000 vs a real 50 $ wallet
    memebot.Meme.buy(s, "MINT", {"baseToken": {"symbol": "X"}, "_size": 40.0}, 50, "why")
    assert s.bought and abs(s.bought[0] - 5.0) < 1e-9                             # capped at 10 % of 50 $, not 40 $
    s = buy_ns(10, wallet_usd=50.0, equity=50.0)
    memebot.Meme.buy(s, "MINT", {"baseToken": {"symbol": "X"}, "_size": 2.0}, 50, "why")
    assert abs(s.bought[0] - 2.0) < 1e-9                                          # a normal 4 % buy is untouched
