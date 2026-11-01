# Keel DSL — "HL supertrend+bollinger causal top-15 (no hindsight universe)"  (Keel strategy str_01m69nnhfd4z38bbcy07gs7kk6, v1)
# THE STRATEGY IN PAPER since 2026-10-31 21:41 UTC: dep_01m69ygrjews0qmgq2sraj8rdr, $1,000 simulated, daily at 11:59 UTC (../hl_paper.json).
# Same rule as supertrend_bollinger_small.keel.py, but the 15 tradable names are re-chosen every 7 days from the trailing 30-day dollar
# volume inside a broad top-60 pool, so no name is picked with hindsight. This is the HONEST evidence for the rule:
#   out-of-sample 2026-04-01..2026-10-30: Sharpe 1.15, +43.5%, max DD -30%, PF 1.31, win rate 47.5%   (btr_01m69npabhj1hsrvx1534x709n)
#   full window  2024-08-15..2026-10-30: Sharpe 0.76, +91%, max DD -58%, PF 1.18, 6 of 10 quarters positive, worst 2025-Q1 -28% and
#                                        2026-Q1 -28%; the in-sample slice (to 2026-03-31) is only +29% with the same -58% DD  (btr_01m69np54xf2f34gbpx0nb77yd)
# The hindsight top-15 (universe resolved 2026-07-06, inside the OOS window) reads OOS Sharpe 1.94 / full 1.79: that gap is survivorship, not edge.
# Capital realism (Keel): <25% of orders under the $10 minimum from ~$64, <5% from ~$100 (min_trade_size=0.05 skips resize orders < 5%).
# Everything below is the Keel source verbatim (the resolved=[...] pin is the top-60 POOL saved by Keel; the traded set is the weekly mask).
Globals(target_timeframe="1d", bar_offset="12h")

Universe(mode="top_volume", top_n=60, market="perp", lookback="90d", resolved=["AAVE", "ADA", "AERO", "APT", "ARB", "ASTER", "AVAX", "BCH", "BNB", "BTC", "CASHCAT", "CHIP", "CRV", "DOGE", "DOT", "ENA", "ETH", "ETHFI", "FARTCOIN", "FET", "GRAM", "GRASS", "HBAR", "HYPE", "INJ", "JUP", "KAITO", "LINK", "LIT", "LTC", "MON", "NEAR", "NIL", "ONDO", "PAXG", "PENDLE", "PENGU", "PONS", "PUMP", "SAND", "SOL", "SPX", "STRK", "SUI", "TAO", "TIA", "TRUMP", "TRX", "UNI", "USELESS", "VIRTUAL", "VVV", "WLD", "XLM", "XMR", "XPL", "XRP", "ZEC", "ZRO", "kPEPE"], resolved_at="2026-10-31T19:06:00.692903+00:00", max_leverages={"AAVE": 10.0, "ADA": 10.0, "AERO": 3.0, "APT": 10.0, "ARB": 10.0, "ASTER": 5.0, "AVAX": 10.0, "BCH": 10.0, "BNB": 10.0, "BTC": 40.0, "CASHCAT": 3.0, "CHIP": 3.0, "CRV": 10.0, "DOGE": 10.0, "DOT": 10.0, "ENA": 10.0, "ETH": 25.0, "ETHFI": 5.0, "FARTCOIN": 10.0, "FET": 5.0, "GRAM": 5.0, "GRASS": 3.0, "HBAR": 5.0, "HYPE": 10.0, "INJ": 5.0, "JUP": 10.0, "KAITO": 5.0, "LINK": 10.0, "LIT": 5.0, "LTC": 10.0, "MON": 5.0, "NEAR": 10.0, "NIL": 3.0, "ONDO": 10.0, "PAXG": 10.0, "PENDLE": 5.0, "PENGU": 5.0, "PONS": 3.0, "PUMP": 10.0, "SAND": 5.0, "SOL": 20.0, "SPX": 5.0, "STRK": 5.0, "SUI": 10.0, "TAO": 5.0, "TIA": 5.0, "TRUMP": 10.0, "TRX": 10.0, "UNI": 10.0, "USELESS": 3.0, "VIRTUAL": 5.0, "VVV": 3.0, "WLD": 10.0, "XLM": 5.0, "XMR": 5.0, "XPL": 10.0, "XRP": 20.0, "ZEC": 10.0, "ZRO": 5.0, "kPEPE": 10.0}, resolution="u1:841a03d36e05.9f060a4f.f0bd2361ded8")

Execution(rebalance="on_change", min_trade_size=0.05)

Pipeline([
    DollarVolumeLoader(),
    Store("dollar_volume"),
    PriceDataLoader(),
    Store("ohlcv"),
    RollingVolumeUniverseMask(dollar_volume_slot="dollar_volume", top_n=15, rebalance_freq="7d", lookback_bars=30),
    Store("top15_causal"),
    Load("ohlcv"),
    {
        "st_green": [SuperTrend(period=10, multiplier=3.0), AboveThresholdFilter(threshold=0.0)],
        "bb_confirms": [BollingerBands(period=20, num_std=2.0), AboveThresholdFilter(threshold=0.5)],
        "bands_not_flat": [VolatilitySqueeze(short_period=7, long_period=21), AboveThresholdFilter(threshold=0.85)],
    },
    MaskAnd(),
    ApplyUniverseMask(mask_slot="top15_causal"),
    FixedWeightSizer(weight_per_position=0.33),
    LeverageCap(max_leverage=1.0),
    FillNaN(fill_value=0.0),
], name="supertrend_bollinger_causal_top15")
