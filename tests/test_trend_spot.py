"""trend_spot: indicators on synthetic daily bars, the entry rule, and the paper engine (no network: universe and bars are injected)."""
import csv, json, os, time
import pytest
import trend_spot as ts

DAY = 86400


def mk(n, start=1.0, drift=0.02, amp=0.01, t0=1_700_000_000, seed_amp=None):
    bars, px = [], start
    for i in range(n):
        o = px; c = o * (1 + drift); h, l = max(o, c) * (1 + amp), min(o, c) * (1 - amp)
        bars.append((t0 + i * DAY, o, h, l, c, 1.0)); px = c
    return bars


def test_atr_is_the_true_range_on_constant_bars():
    bars = [(i * DAY, 10.0, 11.0, 9.0, 10.0, 1.0) for i in range(30)]
    a = ts.atr_series(bars, 7); assert a[5] is None and a[6] == pytest.approx(2.0) and a[-1] == pytest.approx(2.0)


def test_supertrend_direction_follows_the_trend():
    assert ts.supertrend(mk(40, drift=0.03))[-1] == 1 and ts.supertrend(mk(40, drift=-0.03))[-1] == -1
    assert ts.supertrend(mk(5))[-1] is None                                               # warming up


def test_bollinger_position():
    closes = [1.0] * 19 + [1.0]; assert ts.bollinger_pos(closes, 20, 2.0) == 0.5          # flat: by convention the middle
    closes = [1.0 + 0.01 * (i % 2) for i in range(20)]; assert 0 <= ts.bollinger_pos(closes, 20, 2.0) <= 1
    assert ts.bollinger_pos([1.0] * 5, 20, 2.0) is None


def test_signal_rule_on_up_down_and_flat_series():
    up = ts.signal(mk(45, drift=0.02, amp=0.02)); assert up["entry"] and up["st_green"] and up["bb_pos"] > 0.5 and up["atr_ratio"] > 0.85
    down = ts.signal(mk(45, drift=-0.02, amp=0.02)); assert not down["entry"] and not down["st_green"]
    flat = [(i * DAY, 1.0, 1.0, 1.0, 1.0, 1.0) for i in range(45)]; assert ts.signal(flat)["entry"] is False
    assert ts.signal(mk(10))["entry"] is False and "pocas" in ts.signal(mk(10))["why"]


def test_paper_engine_round_trip(tmp_path):
    now = 1_700_000_000 + 60 * DAY + 3600; up, down = mk(60, drift=0.02, amp=0.02), mk(60, drift=-0.02, amp=0.02)
    uni = [{"sym": "AAA", "mint": "MintA", "pool": "pA", "liq": 5e6, "vol": 1e7}, {"sym": "BBB", "mint": "MintB", "pool": "pB", "liq": 5e6, "vol": 1e7},
           {"sym": "CCC", "mint": "MintC", "pool": "pC", "liq": 5e6, "vol": 1e7}, {"sym": "DDD", "mint": "MintD", "pool": "pD", "liq": 5e6, "vol": 1e7}]
    bars = {"pA": up, "pB": up, "pC": down, "pD": up}
    t = ts.TrendPaper(root=str(tmp_path), p={"max_positions": 2, "budget_usd": 1000.0})
    assert t.evaluate(now, uni=uni, bars_fn=lambda pool: bars[pool]) is True
    assert sorted(q["sym"] for q in t.st["pos"].values()) == ["AAA", "BBB"] and t.st["cash"] == pytest.approx(1000 - 2 * 330, abs=0.01)   # max 2, 33 % each, CCC never (down)
    assert t.evaluate(now + 60, uni=uni, bars_fn=lambda pool: bars[pool]) is False       # same UTC day: nothing
    rows = list(csv.DictReader(open(tmp_path / ts.LEDGER))); assert [r["side"] for r in rows] == ["BUY", "BUY"] and rows[0]["mint"] == "MintA"
    st = t.mark(px={"MintA": up[-1][4] * 1.10, "MintB": up[-1][4]})
    assert st["positions"][0]["pnl"] > 0 and st["equity"] > 1000 and os.path.exists(tmp_path / ts.STATUS)
    # next day: AAA's rule turns off (falling bars), BBB leaves the universe -> both closed with their reasons and PnL booked
    bars2 = {"pA": up + mk(25, start=up[-1][4], drift=-0.04, amp=0.02, t0=up[-1][0] + DAY)[:25], "pB": up, "pC": down, "pD": up}
    uni2 = [u for u in uni if u["mint"] != "MintB"]
    assert t.evaluate(now + 26 * DAY, uni=uni2, bars_fn=lambda pool: bars2[pool]) is True
    rows = list(csv.DictReader(open(tmp_path / ts.LEDGER))); sells = [r for r in rows if r["side"] == "SELL"]
    assert {r["reason"] for r in sells} == {"rule_off", "left_universe"} and t.st["closed"] == 2 and t.st["pnl"] == pytest.approx(sum(float(r["pnl"]) for r in sells), abs=1e-6)
    assert "MintD" in t.st["pos"]                                                          # a slot freed: the next qualifying name enters


def test_forming_bar_is_ignored(tmp_path):
    up = mk(60, drift=0.02, amp=0.02); now = up[-1][0] + 3600                                # the last bar opened an hour ago: still forming
    seen = {}
    def bars_fn(pool): return up
    t = ts.TrendPaper(root=str(tmp_path), p={"max_positions": 1})
    uni = [{"sym": "AAA", "mint": "MintA", "pool": "pA", "liq": 5e6, "vol": 1e7}]
    t.evaluate(now, uni=uni, bars_fn=bars_fn)
    assert t.st["signals"]["MintA"]["close"] == pytest.approx(up[-2][4])                    # evaluated on the previous closed bar


def test_universe_parsing_filters_and_dedupes(monkeypatch):
    pools = {"data": [
        {"attributes": {"name": "JUP / SOL", "address": "p1", "reserve_in_usd": "3000000", "volume_usd": {"h24": "9000000"}}, "relationships": {"base_token": {"data": {"id": "solana_MintJUP"}}}},
        {"attributes": {"name": "JUP / USDC", "address": "p2", "reserve_in_usd": "2000000", "volume_usd": {"h24": "5000000"}}, "relationships": {"base_token": {"data": {"id": "solana_MintJUP"}}}},
        {"attributes": {"name": "SOL / USDC", "address": "p3", "reserve_in_usd": "90000000", "volume_usd": {"h24": "9e8"}}, "relationships": {"base_token": {"data": {"id": "solana_So11111111111111111111111111111111111111112"}}}},
        {"attributes": {"name": "TINY / SOL", "address": "p4", "reserve_in_usd": "100000", "volume_usd": {"h24": "9000000"}}, "relationships": {"base_token": {"data": {"id": "solana_MintTINY"}}}},
        {"attributes": {"name": "WIF / SOL", "address": "p5", "reserve_in_usd": "4000000", "volume_usd": {"h24": "4000000"}}, "relationships": {"base_token": {"data": {"id": "solana_MintWIF"}}}}]}
    monkeypatch.setattr(ts, "get", lambda url, **p: pools if p.get("page") == 1 else {"data": []})
    u = ts.universe(8); assert [x["sym"] for x in u] == ["JUP", "WIF"] and u[0]["pool"] == "p1" and u[0]["mint"] == "MintJUP"
