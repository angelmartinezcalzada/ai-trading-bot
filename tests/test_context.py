"""context.py: pure build() on synthetic inputs, write/load round trip, stamp/signals/keys (snapshot and stamp), gather with raising
fetchers and local files, CLI. Everything offline."""
import calendar, json, math, os, statistics, time
import pytest
import context as C

T0 = 1_700_000_000.0            # 2023-11-14 22:13:20 UTC (Tuesday) -> hour_utc 22, dow 1
NONE = {k: (lambda: None) for k in C.DEFAULT_FETCH}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k): raise AssertionError("network call in a test")
    monkeypatch.setattr(C, "DEFAULT_FETCH", {k: boom for k in C.DEFAULT_FETCH}); monkeypatch.setattr(C, "FETCH", None)


def klines(start, step=1.0, n=25):
    """n hourly Binance-like rows whose close grows `step` % per bar (strings, like the API)"""
    return [[i * 3600_000, "0", "0", "0", f"{start * (1 + step / 100) ** i:.8f}", "1"] for i in range(n)]


def utc(ts): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
def utc_naive(ts): return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts))        # hl_risk.json 'updated'
def local_iso(ts): return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))     # candidates_solana.jsonl 'ts'


def pool(created, vol, dex="pumpswap"):
    return {"attributes": {"pool_created_at": utc(created), "volume_usd": {"h1": str(vol)}}, "relationships": {"dex": {"data": {"id": dex}}}}


def snap(ts, hour=None, sol=None, vol=None, npools=None):
    """minimal history row"""
    return {"ts": ts, "hour_utc": time.gmtime(ts).tm_hour if hour is None else hour, "sol": {"usd": sol}, "market": {"new_pools_vol_h1_usd": vol, "new_pools_1h": npools}}


def hl(updated, sol_flags="", sol_apex=-0.4, btc_apex=0.2, status="ok"):
    return {"updated": updated, "status": status, "ok": 2, "failed": 0,
            "coins": {"SOL": {"flags_long": sol_flags, "flags_short": "", "size_mult_long": 1.0, "apex": sol_apex, "crowd": 0.1, "time": updated},
                      "BTC": {"flags_long": "", "apex": btc_apex}}}


# ----------------------------------------------------------------------------------------------------------- build()
def test_returns_and_rv_from_klines():
    s = C.build({"ts": T0, "sol_klines": klines(100.0, 1.0), "btc_klines": klines(50_000.0, -0.2)}, [], T0)
    assert s["code"] == "context/1" and s["hour_utc"] == 22 and s["dow"] == 1
    assert s["sol"]["usd"] == pytest.approx(100 * 1.01 ** 24, rel=1e-6)                 # no sol_price -> last close
    assert s["sol"]["r1h"] == pytest.approx(1.0, abs=1e-3) and s["sol"]["r4h"] == pytest.approx(4.06, abs=1e-2)
    assert s["sol"]["r24h"] == pytest.approx((1.01 ** 24 - 1) * 100, abs=1e-2) and s["sol"]["rv24h"] == pytest.approx(0.0, abs=1e-6)
    assert s["btc"]["r24h"] == pytest.approx((0.998 ** 24 - 1) * 100, abs=1e-2) and s["btc"]["usd"] > 0
    assert s["regime"]["sol_trend"] == "up" and "sol.r24h" not in s["stale"]
    assert C.build({"ts": T0, "sol_price": 95.5, "sol_klines": klines(100.0, 1.0)}, [], T0)["sol"]["usd"] == 95.5   # ticker wins over the last close


def test_rv24h_is_the_std_of_hourly_log_returns_in_pct():
    closes = [100.0]
    for i in range(24): closes.append(closes[-1] * (1 + (0.03 if i % 2 else -0.02)))
    kl = [[0, "0", "0", "0", f"{c:.10f}", "0"] for c in closes]
    r = [math.log(closes[i] / closes[i - 1]) * 100 for i in range(1, 25)]
    s = C.build({"ts": T0, "sol_klines": kl}, [], T0)
    assert s["sol"]["rv24h"] == pytest.approx(statistics.pstdev(r), abs=1e-3)
    assert C.build({"ts": T0, "sol_klines": kl[:20]}, [], T0)["sol"]["rv24h"] is None      # fewer than 25 closes -> unknown


@pytest.mark.parametrize("step,trend", [(0.1, "up"), (0.0, "flat"), (-0.17, "down"), (-0.1, "flat")])
def test_sol_trend_thresholds(step, trend):
    s = C.build({"ts": T0, "sol_klines": klines(100.0, step)}, [], T0)
    r = s["sol"]["r24h"]
    assert (r >= 2) == (trend == "up") and (r <= -4) == (trend == "down") and s["regime"]["sol_trend"] == trend


def test_sol_trend_on_exact_thresholds():
    assert C.build({"ts": T0, "sol_klines": klines(100.0, 0.0826)}, [], T0)["sol"]["r24h"] >= 2.0
    assert C.build({"ts": T0, "sol_klines": klines(100.0, 0.0826)}, [], T0)["regime"]["sol_trend"] == "up"
    assert C.build({"ts": T0, "sol_klines": klines(100.0, -0.17)}, [], T0)["regime"]["sol_trend"] == "down"


def test_returns_from_history_when_klines_missing():
    hist = [snap(T0 - h * 3600, sol=100.0 * (1 + 0.001 * (24 - h))) for h in range(24, 0, -1)]   # 24 hourly samples, rising
    s = C.build({"ts": T0, "sol_price": 102.4}, hist, T0)
    assert s["sol"]["usd"] == 102.4 and s["sol"]["r1h"] == pytest.approx(102.4 / 102.3 * 100 - 100, abs=1e-3)
    assert s["sol"]["r4h"] == pytest.approx(102.4 / 102.0 * 100 - 100, abs=1e-3) and s["sol"]["r24h"] == pytest.approx(2.4, abs=1e-3)
    assert s["sol"]["rv24h"] is not None and s["regime"]["sol_trend"] == "up"
    s2 = C.build({"ts": T0, "sol_price": 102.4}, hist[-5:], T0)                                # only 5 h of history
    assert s2["sol"]["r1h"] is not None and s2["sol"]["r4h"] is not None and s2["sol"]["r24h"] is None and s2["sol"]["rv24h"] is None
    assert s2["regime"]["sol_trend"] is None and "sol.r24h" in s2["stale"]
    s3 = C.build({"ts": T0, "sol_price": 102.4}, [snap(T0 - 3600 - 2000, sol=100.0)], T0)       # sample too far from the hour mark
    assert s3["sol"]["r1h"] is None
    assert C.build({"ts": T0, "sol_price": 102.4}, list(reversed(hist)), T0)["sol"]["r24h"] == pytest.approx(2.4, abs=1e-3)   # order irrelevant


def test_new_pools_graduations_and_volume():
    pools = [pool(T0 - 600, 1000), pool(T0 - 1800, 500, "raydium"), pool(T0 - 3000, 250, "meteora-dlmm"), pool(T0 - 3500, 100, "orca"),
             pool(T0 - 4000, 9999, "pumpswap"), {"attributes": {}}, "junk"]                       # last three: too old / no date / garbage
    m = C.build({"ts": T0, "gecko_new_pools": pools}, [], T0)["market"]
    assert m["new_pools_1h"] == 4 and m["graduations_1h"] == 3 and m["new_pools_vol_h1_usd"] == 1850.0
    assert m["heat"] is None and m["heat_ratio"] is None                                      # no history yet
    assert C.build({"ts": T0, "gecko_new_pools": []}, [], T0)["market"]["new_pools_1h"] == 0
    assert C.build({"ts": T0, "gecko_new_pools": None}, [], T0)["market"]["new_pools_1h"] is None


def test_heat_needs_three_same_hour_samples_in_seven_days():
    pools = [pool(T0 - 100, 3000)]
    same = [snap(T0 - d * 86400, vol=1000.0) for d in (1, 2)]
    assert C.build({"ts": T0, "gecko_new_pools": pools}, same, T0)["market"]["heat"] is None            # 2 samples
    other_hour = same + [snap(T0 - 3 * 86400 + 7200, vol=1.0)]                                          # third sample at another hour
    assert C.build({"ts": T0, "gecko_new_pools": pools}, other_hour, T0)["market"]["heat"] is None
    old = same + [snap(T0 - 8 * 86400, vol=1.0)]                                                        # third sample older than 7 d
    assert C.build({"ts": T0, "gecko_new_pools": pools}, old, T0)["market"]["heat"] is None
    hist = same + [snap(T0 - 3 * 86400, vol=2000.0)]                                                    # median 1000
    m = C.build({"ts": T0, "gecko_new_pools": pools}, hist, T0)["market"]
    assert m["heat_ratio"] == 3.0 and m["heat"] == "hot"
    assert C.build({"ts": T0, "gecko_new_pools": [pool(T0 - 100, 1500)]}, hist, T0)["market"]["heat"] == "hot"      # 1.5 -> hot
    assert C.build({"ts": T0, "gecko_new_pools": [pool(T0 - 100, 1200)]}, hist, T0)["market"]["heat"] == "normal"
    assert C.build({"ts": T0, "gecko_new_pools": [pool(T0 - 100, 500)]}, hist, T0)["market"]["heat"] == "cold"      # 0.5 -> cold
    assert C.build({"ts": T0, "gecko_new_pools": []}, hist, T0)["market"]["heat"] == "cold"                          # 0 launches: ratio 0
    s = C.build({"ts": T0, "gecko_new_pools": pools}, hist, T0)
    assert s["regime"]["heat"] == "hot" and "market.heat" not in s["stale"]
    zero = [snap(T0 - d * 86400, vol=0.0) for d in (1, 2, 3)]                                           # median 0 -> ratio undefined
    assert C.build({"ts": T0, "gecko_new_pools": pools}, zero, T0)["market"]["heat"] is None
    assert C.build({"ts": T0, "gecko_new_pools": None}, hist, T0)["market"]["heat"] is None             # no launches data -> unknown


def test_new_pools_p75_from_history():
    hist = [snap(T0 - h * 3600, npools=n) for h, n in enumerate((1, 2, 3, 4, 5, 6, 7, 8), 1)]
    m = C.build({"ts": T0, "gecko_new_pools": []}, hist, T0)["market"]
    assert m["new_pools_p75_7d"] == 6
    assert C.build({"ts": T0}, hist[:2], T0)["market"]["new_pools_p75_7d"] is None


def test_prio_fee_field():
    assert C.build({"ts": T0, "prio_fees": 1234}, [], T0)["market"]["prio_fee_ulam"] == 1234
    assert C.build({"ts": T0, "prio_fees": 0}, [], T0)["market"]["prio_fee_ulam"] == 0
    for bad in (None, -5, "x", True, float("nan")):
        assert C.build({"ts": T0, "prio_fees": bad}, [], T0)["market"]["prio_fee_ulam"] is None


def test_stale_is_complete_when_every_input_is_missing():
    s = C.build({"ts": T0, **{k: None for k in C.DEFAULT_FETCH}}, [], T0)
    for blk in ("sol", "btc", "news", "market", "breadth", "hl", "regime"):
        assert all(v is None for v in s[blk].values()) and blk in s["stale"]
        assert all(f"{blk}.{k}" in s["stale"] for k in s[blk])
    assert all(f"health.{k}" in s["stale"] for k, v in s["health"].items() if v is None)
    assert s["health"]["st_budget_cap"] is None or isinstance(s["health"]["st_budget_cap"], int)   # cap comes from solanatracker when importable
    assert s["ts"] == T0 and s["code"] == "context/1"
    json.dumps(s)                                                                                      # serialisable


def test_build_survives_garbage_raw():
    for raw in (None, {}, {"ts": "x"}, {"ts": T0, "sol_klines": "no", "btc_klines": [[1]], "gecko_new_pools": 5, "news": 3, "binance_status": [],
                                         "cands": "x", "hl_risk": [1], "trend_status": {"signals": 2}, "x_buzz": [], "st_budget": {"n": "3"}}):
        s = C.build(raw, None, T0)
        assert s["code"] == "context/1" and isinstance(s["stale"], list)
    assert C.build({"ts": T0, "sol_klines": [[0, 0, 0, 0, "-1", 0]] * 25}, [], T0)["sol"]["usd"] is None     # non-positive close -> unknown
    assert C.build({"ts": T0, "sol_price": True}, [], T0)["sol"]["usd"] is None                                # bool is not a price


def test_btc_on_and_regime_age():
    st = {"regime": {"regime": "range", "btc_vol_pct": 1.2}}
    s = C.build({"ts": T0, "binance_status": st, "binance_mtime": T0 - 100}, [], T0)
    assert s["btc"]["regime"] == "range" and s["btc"]["regime_age_s"] == 100 and s["regime"]["btc_on"] is True
    s = C.build({"ts": T0, "binance_status": {"regime": {"regime": "bear"}}, "binance_mtime": T0 - 899}, [], T0)
    assert s["regime"]["btc_on"] is False
    s = C.build({"ts": T0, "binance_status": st, "binance_mtime": T0 - 901}, [], T0)                     # older than 900 s
    assert s["btc"]["regime"] == "range" and s["btc"]["regime_age_s"] == 901 and s["regime"]["btc_on"] is None and "regime.btc_on" in s["stale"]
    s = C.build({"ts": T0, "binance_status": {"regime": {"regime": "weird"}}, "binance_mtime": T0}, [], T0)
    assert s["btc"]["regime"] is None and s["regime"]["btc_on"] is None
    assert C.build({"ts": T0}, [], T0)["regime"]["btc_on"] is None


def test_news_block():
    s = C.build({"ts": T0, "news": None, "news_mtime": None}, [], T0)
    assert s["news"] == {"risk_off": None, "fng": None, "sentiment": None, "sources_ok": None, "age_s": None} and "news" in s["stale"]
    assert s["regime"]["risk_off"] is None
    n = {"risk_off": True, "fng": {"value": 18, "label": "Extreme Fear"}, "sentiment": -0.25,
         "sources_ok": {"CoinDesk": T0 - 100, "Binance": T0 - 7 * 3600, "Fear&Greed": T0 - 10}}                 # news.py: {source: epoch of last success}
    s = C.build({"ts": T0, "news": n, "news_mtime": T0 - 300}, [], T0)
    assert s["news"] == {"risk_off": True, "fng": 18, "sentiment": -0.25, "sources_ok": 2, "age_s": 300} and s["regime"]["risk_off"] is True
    assert "news" not in s["stale"] and "news.fng" not in s["stale"]
    s = C.build({"ts": T0, "news": {"risk_off": False, "fng": 55, "sentiment": 0.1, "sources_ok": 4, "ts": T0 - 60}, "news_mtime": T0 - 3000}, [], T0)
    assert s["news"]["age_s"] == 60 and s["news"]["fng"] == 55 and s["news"]["sources_ok"] == 4
    s = C.build({"ts": T0, "news": {"risk_off": "yes", "fng": None, "sources_ok": {"a": "x", "b": 1}}, "news_mtime": T0}, [], T0)   # wrong types -> unknown, never a pass
    assert s["news"]["risk_off"] is None and s["news"]["fng"] is None and s["news"]["sources_ok"] == 2


def test_breadth_from_trend_status():
    sig = {"m1": {"entry": True, "atr_ratio": 1.2, "in_universe": True}, "m2": {"entry": False, "atr_ratio": 0.8, "in_universe": True},
           "m3": {"entry": True, "atr_ratio": 1.0, "in_universe": True}, "m4": {"entry": True, "atr_ratio": 5.0, "in_universe": False},
           "m5": {"entry": False, "atr_ratio": None, "in_universe": True}}
    b = C.build({"ts": T0, "trend_status": {"ts": T0 - 600, "signals": sig}}, [], T0)["breadth"]
    assert b == {"n_entry": 2, "n_universe": 4, "share": 0.5, "med_atr_ratio": 1.0}
    b = C.build({"ts": T0, "trend_status": {"ts": T0 - 3 * 86400, "signals": sig}}, [], T0)["breadth"]   # stale status -> unknown
    assert b["n_entry"] is None and b["share"] is None
    assert C.build({"ts": T0, "trend_status": {"ts": T0, "signals": {}}}, [], T0)["breadth"]["n_universe"] is None


def test_hl_block():
    s = C.build({"ts": T0, "hl_risk": hl(utc_naive(T0 - 600), "crowd_with_us|liq_cluster")}, [], T0)["hl"]
    assert s == {"sol_bias": -0.4, "btc_bias": 0.2, "stress": "crowd_with_us|liq_cluster", "status": "ok", "age_s": 600}
    assert C.build({"ts": T0, "hl_risk": hl(utc_naive(T0 - 60))}, [], T0)["hl"]["stress"] == "none"               # SOL row with no flags
    s = C.build({"ts": T0, "hl_risk": hl(utc_naive(T0 - 7201), "apex_against")}, [], T0)["hl"]                   # older than 2 h -> unknown
    assert s == {"sol_bias": None, "btc_bias": None, "stress": None, "status": "ok", "age_s": 7201}
    deg = {**hl(utc_naive(T0 - 3000), "high_leverage"), "status": "degraded", "last_attempt": utc_naive(T0)}      # failed pass keeps the last good data
    assert C.build({"ts": T0, "hl_risk": deg}, [], T0)["hl"] == {"sol_bias": -0.4, "btc_bias": 0.2, "stress": "high_leverage", "status": "degraded", "age_s": 3000}
    s = C.build({"ts": T0, "hl_risk": {"status": "degraded", "updated": None, "coins": {}}, "hl_mtime": T0 - 5}, [], T0)["hl"]
    assert s == {"sol_bias": None, "btc_bias": None, "stress": None, "status": "degraded", "age_s": 5}
    s = C.build({"ts": T0, "hl_risk": {"updated": utc_naive(T0), "status": "partial", "coins": {"BTC": {"apex": 0.9, "flags_long": "crowd_with_us"}}}}, [], T0)["hl"]
    assert s["btc_bias"] == 0.9 and s["sol_bias"] is None and s["stress"] is None                                   # no SOL row -> SOL unknown
    assert C.build({"ts": T0}, [], T0)["hl"] == {"sol_bias": None, "btc_bias": None, "stress": None, "status": None, "age_s": None}


def test_health_block():
    today = time.strftime("%Y-%m-%d", time.localtime(T0))
    raw = {"ts": T0, "insider_mtime": T0 - 42, "st_budget": {"day": today, "n": 123, "nd": 4}, "st_cap": 300,
           "x_buzz": {"m1": {"ts": T0 - 500}, "m2": {"ts": T0 - 200}}, "brain_state": {"active": False}, "director_state": {"shadow": True}}
    h = C.build(raw, [], T0)["health"]
    assert h == {"insider_age_s": 42, "st_budget_used": 123, "st_budget_cap": 300, "x_buzz_age_s": 200, "brain_active": False, "director_shadow": True}
    h = C.build({"ts": T0, "st_budget": {"day": "2001-01-01", "n": 123}, "x_buzz": {}, "x_buzz_mtime": T0 - 7, "brain_state": {"active": "si"}}, [], T0)["health"]
    assert h["st_budget_used"] == 0 and h["x_buzz_age_s"] == 7 and h["brain_active"] is None and h["st_budget_cap"] is None


def test_candidates_tail_counts_distinct_mints_in_the_last_hour():
    rows = [{"ts": local_iso(T0 - 100), "mint": "A"}, {"ts": local_iso(T0 - 200), "mint": "A"}, {"ts": local_iso(T0 - 3000), "mint": "B"},
            {"ts": local_iso(T0 - 4000), "mint": "C"}, {"ts": "garbage", "mint": "D"}, {"mint": "E"}, "junk"]
    m = C.build({"ts": T0, "cands": rows}, [], T0)["market"]
    assert m["n_cands_1h"] == 2 and m["agg_vol_h1_usd"] is None                                        # rows carry no vol_h1 -> unknown
    rows2 = [{"ts": local_iso(T0 - 100), "mint": "A", "vol_h1": 1000}, {"ts": local_iso(T0 - 200), "mint": "A", "vol_h1": 900},
             {"ts": local_iso(T0 - 300), "mint": "B", "vol": {"h1": 50.5}}, {"ts": local_iso(T0 - 400), "mint": "C"}]
    for order in (rows2, list(reversed(rows2))):                                                        # latest row per mint, whatever the order
        m = C.build({"ts": T0, "cands": order}, [], T0)["market"]
        assert m["n_cands_1h"] == 3 and m["agg_vol_h1_usd"] == 1050.5
    assert C.build({"ts": T0, "cands": None}, [], T0)["market"]["n_cands_1h"] is None


def test_epoch_parses_local_utc_and_offsets():
    assert C._epoch(utc(T0)) == T0 and C._epoch("2023-11-14T22:13:20+00:00") == T0 and C._epoch(T0) == T0 and C._epoch(int(T0)) == T0
    assert C._epoch(utc_naive(T0), utc=True) == T0 and C._epoch(local_iso(T0)) == T0
    assert C._epoch("2023-11-14T23:13:20+01:00") == T0
    for bad in (None, "", "x", True, {}, "2023-13-45T00:00:00"): assert C._epoch(bad) is None


# ------------------------------------------------------------------------------------------------- write / load
def test_write_load_round_trip_and_history(tmp_path):
    root = str(tmp_path)
    assert C.load(root, now=T0) is None and C.history(root) == []
    s = C.build({"ts": T0, "sol_klines": klines(100.0, 0.2)}, [], T0)
    p = C.write(s, root)
    assert p == os.path.join(root, "data", "context_now.json") and not [f for f in os.listdir(tmp_path / "data") if f.endswith(".tmp")]
    assert C.load(root, now=T0 + 100) == s and C.load(root, max_age=7200, now=T0 + 7201) is None
    assert C.history(root) == [s]
    s2 = C.build({"ts": T0 + 3600, "sol_price": 101.0}, C.history(root), T0 + 3600); C.write(s2, root)
    assert [h["ts"] for h in C.history(root)] == [T0, T0 + 3600] and s2["sol"]["r1h"] == pytest.approx(101 / (100 * 1.002 ** 24) * 100 - 100, abs=1e-3)
    assert C.history(root, cap=10) == [] and len(C.history(root, cap=4_000_000)) == 2                   # byte-tail cap: only complete lines
    (tmp_path / "data" / "context_now.json").write_text("{not json")
    assert C.load(root, now=T0) is None
    (tmp_path / "data" / "context_now.json").write_text(json.dumps({"ts": T0, "code": "other/9"}))
    assert C.load(root, now=T0) is None


def test_history_file_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "HIST_MAX", 50); monkeypatch.setattr(C, "HIST_KEEP", 20)
    root = str(tmp_path)
    for i in range(51): C.write({"ts": T0 + i, "code": "context/1"}, root)
    lines = (tmp_path / "data" / "context.jsonl").read_text().splitlines()
    assert len(lines) == 20 and json.loads(lines[-1])["ts"] == T0 + 50 and json.loads(lines[0])["ts"] == T0 + 31
    assert not [f for f in os.listdir(tmp_path / "data") if f.endswith(".tmp")]
    C.write({"ts": T0 + 51, "code": "context/1"}, root)
    assert len((tmp_path / "data" / "context.jsonl").read_text().splitlines()) == 21


# ------------------------------------------------------------------------------------------- stamp / signals / keys
def full_snapshot():
    pools = [pool(T0 - 100, 3000)]
    hist = [snap(T0 - d * 86400, vol=1000.0, npools=3) for d in (1, 2, 3)] + [snap(T0 - h * 3600, npools=n) for h, n in ((1, 1), (2, 2), (3, 10))]
    raw = {"ts": T0, "sol_klines": klines(100.0, 0.2), "btc_klines": klines(50_000.0, 0.1), "gecko_new_pools": pools,
           "binance_status": {"regime": {"regime": "bull"}}, "binance_mtime": T0 - 10,
           "news": {"risk_off": True, "fng": {"value": 15}, "sentiment": -0.5, "sources_ok": {"a": T0 - 1}}, "news_mtime": T0 - 30,
           "trend_status": {"ts": T0, "signals": {"m1": {"entry": True, "atr_ratio": 1.0, "in_universe": True}, "m2": {"entry": True, "atr_ratio": 1.1, "in_universe": True}}}}
    return C.build(raw, hist, T0)


def test_stamp_full_and_null():
    s = full_snapshot()
    st = C.stamp(s, thr=55, score_adj=5, size_mult=0.5, equity=48.2, n_pos=1, now=T0 + 120)
    assert tuple(st) == C.STAMP_KEYS
    assert st["ts"] == T0 and st["age_s"] == 120 and st["sol_24h"] == s["sol"]["r24h"] and st["sol_4h"] == s["sol"]["r4h"] and st["sol_trend"] == "up"
    assert st["btc_on"] is True and st["risk_off"] is True and st["fng"] == 15 and st["heat"] == "hot" and st["heat_ratio"] == 3.0 and st["new_pools_1h"] == 1
    assert st["breadth"] == 1.0 and st["hour_utc"] == 22 and st["dow"] == 1 and (st["thr"], st["score_adj"], st["size_mult"], st["equity"], st["n_pos"]) == (55, 5, 0.5, 48.2, 1)
    st = C.stamp(s, now=T0 + 5 * 86400 + 3 * 3600)                                                   # hour / dow are the candidate's (now: Monday 01:13 UTC), not the snapshot's
    assert st["hour_utc"] == 1 and st["dow"] == 0 and st["age_s"] == 5 * 86400 + 3 * 3600
    empty = C.build({"ts": T0}, [], T0)
    st = C.stamp(empty, now=T0 + 5)
    assert st["age_s"] == 5 and all(st[k] is None for k in ("sol_24h", "sol_4h", "sol_trend", "btc_on", "risk_off", "fng", "heat", "heat_ratio", "new_pools_1h", "breadth", "thr"))
    st = C.stamp(None, thr=50, now=T0)
    assert st["ts"] is None and st["age_s"] is None and st["thr"] == 50 and st["hour_utc"] == 22 and st["dow"] == 1 and st["sol_trend"] is None
    json.dumps(st)


def test_signals_full_null_and_history():
    s = full_snapshot()
    sg = C.signals(s)
    assert tuple(sg) == C.SIGNAL_KEYS and all(isinstance(v, bool) for v in sg.values())
    assert sg == {"sol_up": True, "sol_down": False, "btc_on": True, "risk_off": True, "fear_extreme": True, "heat_hot": True, "heat_cold": False,
                  "launches_hi": False, "breadth_hi": True, "night_utc": False, "weekend": False}      # p75 of (1,2,3,3,3,10) = 3 > 1 launch
    s["market"]["new_pools_1h"] = 3; assert C.signals(s)["launches_hi"] is True
    hist = [snap(T0 - h * 3600, npools=0) for h in (1, 2, 3)]
    assert C.signals(s, history=hist)["launches_hi"] is True and C.signals(s, history=hist[:2])["launches_hi"] is False
    s["hour_utc"], s["dow"] = 6, 6; assert C.signals(s)["night_utc"] and C.signals(s)["weekend"]
    s["hour_utc"], s["dow"] = 7, 4; assert not C.signals(s)["night_utc"] and not C.signals(s)["weekend"]
    s["news"]["fng"] = 21; assert not C.signals(s)["fear_extreme"]
    s["regime"]["sol_trend"] = "down"; assert C.signals(s)["sol_down"] and not C.signals(s)["sol_up"]
    empty = C.signals(C.build({"ts": T0}, [], T0))
    assert set(empty) == set(sg) and not any(empty.values())                                           # unknown is never a signal
    assert not any(C.signals(None).values()) and not any(C.signals({}).values()) and not any(C.signals("x").values())


def test_signals_and_keys_on_the_compact_stamp():
    s = full_snapshot(); st = C.stamp(s, thr=50, now=T0 + 60)
    sg = C.signals(st)
    assert sg["sol_up"] and sg["btc_on"] and sg["risk_off"] and sg["fear_extreme"] and sg["heat_hot"] and sg["breadth_hi"] and not sg["night_utc"]
    assert sg["launches_hi"] is False                                                                 # a stamp carries no p75: needs history
    assert C.signals(st, history=[snap(T0 - h * 3600, npools=0) for h in (1, 2, 3)])["launches_hi"] is True
    assert C.signals(st, history=[snap(T0 - h * 3600, npools=5) for h in (1, 2, 3)])["launches_hi"] is False
    assert C.keys(st) == ("up", True, True, "hot") == C.keys(s)
    st2 = C.stamp(None, now=T0 + 6 * 3600 + 3600 * 24 * 4)                                           # Sunday 04:xx UTC, nothing known
    sg2 = C.signals(st2)
    assert sg2["night_utc"] and sg2["weekend"] and not any(v for k, v in sg2.items() if k not in ("night_utc", "weekend"))
    assert C.keys(st2) == ("na", "na", "na", "na")
    row = {"mint": "X", "score": 60, "ctx": st}                                                     # the brain reads rec['ctx'] from candidates_solana.jsonl
    assert C.keys(row["ctx"]) == ("up", True, True, "hot")


def test_keys_na_for_unknown():
    s = full_snapshot()
    assert C.keys(s) == ("up", True, True, "hot")
    assert C.keys(C.build({"ts": T0}, [], T0)) == ("na", "na", "na", "na") and C.keys(None) == ("na", "na", "na", "na")
    s["regime"]["btc_on"] = False; s["regime"]["heat"] = None
    assert C.keys(s) == ("up", False, True, "na")


# ------------------------------------------------------------------------------------------------------ gather()
def test_gather_with_raising_fetchers_and_local_files(tmp_path):
    root = str(tmp_path)
    def boom(): raise RuntimeError("down")
    fx = {"sol_price": boom, "btc_klines": boom, "sol_klines": lambda: klines(100.0, 0.3), "gecko_new_pools": boom, "prio_fees": None}
    raw = C.gather(root, now=T0, fetch=fx)
    assert raw["ts"] == T0 and raw["sol_price"] is None and raw["btc_klines"] is None and raw["gecko_new_pools"] is None and raw["prio_fees"] is None
    assert len(raw["sol_klines"]) == 25 and raw["news"] is None and raw["cands"] is None and raw["trend_status"] is None and raw["hl_risk"] is None
    s = C.build(raw, [], T0)
    assert s["sol"]["r24h"] is not None and "news" in s["stale"] and "market" in s["stale"] and "hl" in s["stale"]
    # local files, as their writers produce them
    (tmp_path / "data").mkdir(); (tmp_path / "state").mkdir()
    now = time.time()
    (tmp_path / "news_state.json").write_text(json.dumps({"risk_off": False, "fng": {"value": 40}, "sentiment": 0.2, "sources_ok": {"x": round(now), "y": round(now) - 100}}))
    (tmp_path / "status_binance.json").write_text(json.dumps({"regime": {"regime": "bear", "btc_vol_pct": 1.0}, "ts": now}))
    (tmp_path / "state" / "trend_status.json").write_text(json.dumps({"ts": now, "signals": {"m": {"entry": True, "atr_ratio": 0.9, "in_universe": True}}}))
    (tmp_path / "data" / "hl_risk.json").write_text(json.dumps(hl(utc_naive(now - 120), "apex_against", sol_apex=0.3)))
    (tmp_path / "insider_status.json").write_text("{}")
    (tmp_path / "data" / "st_budget.json").write_text(json.dumps({"day": time.strftime("%Y-%m-%d"), "n": 7, "nd": 2}))
    (tmp_path / "data" / "x_buzz.json").write_text(json.dumps({"m": {"sym": "M", "posts_1h": 1, "ts": int(now - 50)}}))
    (tmp_path / "brain_state.json").write_text(json.dumps({"active": True}))
    (tmp_path / "director_state.json").write_text(json.dumps({"shadow": False, "ts": now}))
    with open(tmp_path / "candidates_solana.jsonl", "w") as f:
        f.write("not json\n")
        for i in range(3): f.write(json.dumps({"ts": local_iso(now - 60 * i), "mint": f"M{i}", "sym": "X", "pass": False, "fail": ["liq"]}) + "\n")
    raw = C.gather(root, now=now, fetch=fx)
    s = C.build(raw, [], now)
    assert s["news"]["fng"] == 40 and s["news"]["sources_ok"] == 2 and s["news"]["risk_off"] is False and s["news"]["age_s"] <= 5
    assert s["btc"]["regime"] == "bear" and s["regime"]["btc_on"] is False and s["btc"]["regime_age_s"] <= 5
    assert s["breadth"] == {"n_entry": 1, "n_universe": 1, "share": 1.0, "med_atr_ratio": 0.9}
    assert s["hl"]["sol_bias"] == 0.3 and s["hl"]["btc_bias"] == 0.2 and s["hl"]["stress"] == "apex_against" and s["hl"]["status"] == "ok" and 119 <= s["hl"]["age_s"] <= 125
    h = s["health"]
    assert h["insider_age_s"] <= 5 and h["st_budget_used"] == 7 and 49 <= h["x_buzz_age_s"] <= 52 and h["brain_active"] is True and h["director_shadow"] is False
    assert isinstance(h["st_budget_cap"], int) and h["st_budget_cap"] > 0
    assert s["market"]["n_cands_1h"] == 3 and s["market"]["agg_vol_h1_usd"] is None
    assert "news" not in s["stale"] and "breadth" not in s["stale"] and "hl" not in s["stale"]


def test_gather_candidates_tail_drops_the_cut_line(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "TAIL_CAP", 200); monkeypatch.setattr(C, "TAIL_MAX", 200)
    now = time.time()
    with open(tmp_path / "candidates_solana.jsonl", "w") as f:
        for i in range(20): f.write(json.dumps({"ts": local_iso(now - i), "mint": f"MINT{i:02d}", "pad": "x" * 20}) + "\n")
    rows = C.gather(str(tmp_path), now=now, fetch=NONE)["cands"]
    assert 0 < len(rows) < 20 and all(r["mint"].startswith("MINT") for r in rows)


def test_candidates_tail_grows_only_until_it_covers_the_hour(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "TAIL_CAP", 200); monkeypatch.setattr(C, "TAIL_MAX", 3200)
    now = time.time(); p = tmp_path / "candidates_solana.jsonl"
    with open(p, "w") as f:                                                                             # 40 rows ~ 2.4 KB, all within the hour
        for i in range(40): f.write(json.dumps({"ts": local_iso(now - 3000 + i * 10), "mint": f"MINT{i:02d}", "pad": "x" * 20}) + "\n")
    rows = C.gather(str(tmp_path), now=now, fetch=NONE)["cands"]
    assert len(rows) == 40                                                                              # grew 200 -> 800 -> 3200: whole file
    with open(p, "w") as f:
        for i in range(40): f.write(json.dumps({"ts": local_iso(now - 7200 + i * 10), "mint": f"MINT{i:02d}", "pad": "x" * 20}) + "\n")
    rows = C.gather(str(tmp_path), now=now, fetch=NONE)["cands"]                                        # first rows older than an hour: stops at 800 B
    assert 0 < len(rows) < 40 and C._epoch(rows[0]["ts"]) <= now - 3600
    monkeypatch.setattr(C, "TAIL_MAX", 200)                                                             # cap reached: the partial tail is what we have
    assert 0 < len(C.gather(str(tmp_path), now=now, fetch=NONE)["cands"]) < 40


def test_default_fetchers_are_wrapped_and_never_raise(monkeypatch):
    monkeypatch.setattr(C, "DEFAULT_FETCH", {k: (lambda: (_ for _ in ()).throw(RuntimeError("net"))) for k in C.DEFAULT_FETCH})
    raw = C.gather(".", now=T0)
    assert all(raw[k] is None for k in C.DEFAULT_FETCH)


# ----------------------------------------------------------------------------------------------------------- CLI
def test_cli_once_with_fetch_override(tmp_path, capsys, monkeypatch):
    root = str(tmp_path)
    pools = [pool(time.time() - 100, 500), pool(time.time() - 200, 100, "orca")]
    monkeypatch.setattr(C, "FETCH", {"sol_price": lambda: 150.0, "sol_klines": lambda: klines(150.0, 0.1), "btc_klines": lambda: None,
                                     "gecko_new_pools": lambda: pools, "prio_fees": lambda: 1234})
    assert C.main(["--once"], root=root) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("contexto: SOL +2.4% 24h, BTC ?, F&G ?, riesgo-off ?, lanzamientos/h 2, calor ?, amplitud ?/?")
    s = json.load(open(tmp_path / "data" / "context_now.json"))
    assert s["sol"]["usd"] == 150.0 and s["market"]["new_pools_1h"] == 2 and s["market"]["graduations_1h"] == 1 and s["btc"]["usd"] is None
    assert s["market"]["prio_fee_ulam"] == 1234 and s["stale"] and "btc" in s["stale"]
    assert len((tmp_path / "data" / "context.jsonl").read_text().splitlines()) == 1
    assert C.main(["--show"], root=root) == 0 and json.loads(capsys.readouterr().out)["code"] == "context/1"
    assert C.main(["--once"], fetch=NONE, root=root) == 0 and capsys.readouterr().out.startswith("contexto: SOL ?% 24h")   # fetch arg overrides FETCH
    assert C.load(root)["sol"]["usd"] is None and len(C.history(root)) == 2


def test_cli_show_without_file(tmp_path, capsys):
    assert C.main(["--show"], root=str(tmp_path)) == 0 and "sin contexto" in capsys.readouterr().out


def test_cli_loop_stops_on_stop_file(tmp_path, capsys, monkeypatch):
    (tmp_path / "STOP").write_text("")
    monkeypatch.setenv("CONTEXT_SECONDS", "1")
    assert C.main(["--loop"], fetch=NONE, root=str(tmp_path)) == 0 and capsys.readouterr().out == ""


def test_summary_line_formats_every_value():
    s = full_snapshot()
    line = C.summary_line(s)
    assert line.startswith("contexto: SOL +") and "BTC on" in line and "F&G 15" in line and "riesgo-off si" in line and "lanzamientos/h 1" in line
    assert "calor hot" in line and line.endswith("amplitud 2/2")
    s["regime"]["btc_on"] = False; s["regime"]["risk_off"] = False
    assert "BTC off" in C.summary_line(s) and "riesgo-off no" in C.summary_line(s)
