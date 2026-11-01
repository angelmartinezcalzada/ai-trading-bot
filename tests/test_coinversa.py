import json
from hl_leg import coinversa as cv

BIAS = {"coin": "BTC", "tiers": [
    {"tier": "money_printer", "label": "Apex", "netBiasByNotional": -0.40},
    {"tier": "smart_money", "label": "Sharps", "netBiasByNotional": 0.27},
    {"tier": "exit_liquidity", "label": "The Crowd", "netBiasByNotional": 0.34}]}
SNAP = {"totalOI": 3_188_000_000, "nearLiquidationNotional": 256_000_000, "avgLeverage": 16.2}
LIVE_SNAP = {"market": {"totalOi": 3_199_658_499.5, "avgLongLeverage": 15.43, "avgShortLeverage": 17.73},            # the real /live/risk/coin shape (2026-10-31)
             "nearLiquidationNotional": 259_605_055.5, "concentrationTop5": 0.19}

def test_tier_bias_maps_internal_names():
    assert cv.tier_bias(BIAS) == {"apex": -0.40, "sharps": 0.27, "crowd": 0.34}
    assert cv.tier_bias(None) == {}

def test_flags_long_apex_against_and_high_leverage():
    f = cv.risk_flags("long", BIAS, SNAP)
    assert "apex_against" in f and "high_leverage" in f
    assert "crowd_with_us" not in f           # 0.34 < 0.5
    assert "liq_cluster" not in f             # 256M/3188M = 8% < 10%

def test_flags_short_side_flips_sign():
    f = cv.risk_flags("short", BIAS, SNAP)
    assert "apex_against" not in f and "crowd_with_us" not in f

def test_flags_never_crash_on_garbage():
    assert cv.risk_flags("long", {"tiers": [{"tier": "x", "netBiasByNotional": "nan?"}]}, {"totalOI": "abc"}) == []
    assert cv.risk_flags("long", None, None) == []

def test_size_multiplier_only_reduces_and_floors():
    assert cv.size_multiplier([]) == 1.0
    assert cv.size_multiplier(["crowd_with_us"]) == 0.75
    assert cv.size_multiplier(["crowd_with_us", "apex_against", "liq_cluster"]) == 0.5

def test_client_disabled_without_key_is_fail_safe(monkeypatch):
    monkeypatch.delenv("COINVERSA_API_KEY", raising=False)
    c = cv.CoinversaClient(api_key="")
    assert not c.enabled and c.cohort_bias("BTC") is None and c.risk_overview() is None

def test_client_uses_session_and_cache():
    calls = []
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"tiers": []}
    class S:
        def get(self, url, params=None, timeout=None, headers=None, allow_redirects=True):
            calls.append((url, params)); assert allow_redirects is False; return R()
    c = cv.CoinversaClient(api_key="k", base_url="https://x", session=S())
    assert c.cohort_bias("BTC") == {"tiers": []}
    assert c.cohort_bias("BTC") == {"tiers": []}
    assert len(calls) == 1 and calls[0][0] == "https://x/live/cohort-bias" and calls[0][1] == {"coin": "BTC"}

def test_client_failure_returns_none():
    class S:
        def get(self, *a, **k): raise OSError("down")
    c = cv.CoinversaClient(api_key="k", session=S())
    assert c.risk_snapshot("SOL") is None

def test_context_row_shape():
    row = cv.context_row("BTC", BIAS, SNAP, ts=0)
    assert row["time"] == "1970-01-01T00:00:00" and row["coin"] == "BTC" and row["apex"] == -0.4
    assert "apex_against" in row["flags_long"]


def test_flags_read_the_live_snapshot_shape():
    assert cv.snapshot_numbers(LIVE_SNAP, "long") == {"oi": 3_199_658_499.5, "near_liq": 259_605_055.5, "avg_leverage": 15.43}
    assert cv.snapshot_numbers(LIVE_SNAP, "short")["avg_leverage"] == 17.73
    assert cv.risk_flags("long", None, LIVE_SNAP) == ["high_leverage"]          # 259M/3200M = 8.1% < 10%; leverage 15.4 > 12
    assert cv.risk_flags("long", None, dict(LIVE_SNAP, nearLiquidationNotional=400_000_000)) == ["liq_cluster", "high_leverage"]
    assert cv.snapshot_numbers({}, "long") == {"oi": None, "near_liq": None, "avg_leverage": None}   # missing is None, never 0
    row = cv.context_row("BTC", None, LIVE_SNAP, ts=0)
    assert row["oi"] == 3_199_658_499.5 and row["avg_leverage"] == 17.73


def test_short_side_flags_are_pinned():
    bias = {"tiers": [{"tier": "exit_liquidity", "netBiasByNotional": -0.6}, {"tier": "money_printer", "netBiasByNotional": 0.4}]}
    assert cv.risk_flags("short", bias, None) == ["crowd_with_us", "apex_against"]
    assert cv.risk_flags("long", bias, None) == []


def test_size_multiplier_values():
    assert cv.size_multiplier(["crowd_with_us", "apex_against"]) == 0.562
    assert cv.size_multiplier(["liq_cluster"]) == 0.85
    assert cv.tier_bias({"tiers": ["garbage", {"tier": "money_printer", "netBiasByNotional": 0.1}]}) == {"apex": 0.1}
