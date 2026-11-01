import json, os, csv
from hl_leg import hl_context, coinversa as cv

class FakeClient:
    enabled = True
    def __init__(self, bias, snap): self.bias, self.snap = bias, snap
    def cohort_bias(self, coin): return self.bias.get(coin)
    def risk_snapshot(self, coin): return self.snap.get(coin)

BIAS = {"tiers": [{"tier": "money_printer", "netBiasByNotional": -0.5}, {"tier": "exit_liquidity", "netBiasByNotional": 0.7}]}
SNAP = {"totalOI": 1000.0, "nearLiquidationNotional": 200.0, "avgLeverage": 5.0}

def test_one_pass_writes_csv_and_json(tmp_path):
    c = FakeClient({"BTC": BIAS}, {"BTC": SNAP, "ETH": SNAP})
    risk = hl_context.one_pass(c, ["BTC", "ETH", "SOL"], data_dir=str(tmp_path), now=0)
    assert set(risk) == {"BTC", "ETH"}                       # SOL had no data -> skipped
    assert risk["BTC"]["flags_long"] == ["crowd_with_us", "apex_against", "liq_cluster"]
    assert risk["BTC"]["size_mult_long"] == 0.5 and risk["ETH"]["size_mult_long"] == 0.85
    rows = list(csv.DictReader(open(tmp_path / "hl_context.csv")))
    assert [r["coin"] for r in rows] == ["BTC", "ETH"] and rows[0]["time"] == "1970-01-01T00:00:00"
    j = json.load(open(tmp_path / "hl_risk.json"))
    assert j["coins"]["BTC"]["apex"] == -0.5 and j["status"] == "partial" and j["ok"] == 2 and j["failed"] == 1
    # second pass appends without a second header
    hl_context.one_pass(c, ["BTC"], data_dir=str(tmp_path), now=3600)
    assert len(list(csv.DictReader(open(tmp_path / "hl_context.csv")))) == 3

def test_disabled_client_writes_nothing(tmp_path):
    c = cv.CoinversaClient(api_key="")
    assert hl_context.one_pass(c, ["BTC"], data_dir=str(tmp_path)) == {}
    assert not (tmp_path / "hl_context.csv").exists()

def test_load_universe_default_file():
    syms = hl_context.load_universe()
    assert "BTC" in syms and "SOL" in syms and len(syms) == 15


def test_all_failed_pass_keeps_last_good_snapshot_and_flags_degraded(tmp_path):
    good = FakeClient({"BTC": BIAS}, {"BTC": SNAP})
    hl_context.one_pass(good, ["BTC"], data_dir=str(tmp_path), now=0)
    dead = FakeClient({}, {})
    assert hl_context.one_pass(dead, ["BTC", "ETH"], data_dir=str(tmp_path), now=7200) == {}
    j = json.load(open(tmp_path / "hl_risk.json"))
    assert j["status"] == "degraded" and j["ok"] == 0 and j["failed"] == 2
    assert j["updated"] == "1970-01-01T00:00:00" and j["last_attempt"] == "1970-01-01T02:00:00"
    assert j["coins"]["BTC"]["apex"] == -0.5                                  # previous good data kept, not wiped
