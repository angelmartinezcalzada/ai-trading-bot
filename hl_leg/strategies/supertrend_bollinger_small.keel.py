# Keel DSL — "HL supertrend+bollinger top15 (base)"  (Keel strategy str_01m69h9m4jb20rdq7nzbzw1468, v8 = v3 rule + min_trade_size 0.05)
# REFERENCE ONLY, NOT THE PAPER STRATEGY. Its universe is the top-15 by volume that Keel RESOLVED ON 2026-07-06 (the resolved=[...] pin
# below), i.e. a list chosen inside the out-of-sample window: names like PUMP, XPL, LIT, ZEC, VVV, GRAM are there because they became big
# in 2026. The backtest therefore knows the future (survivorship): OOS Sharpe 1.94 / +104% / DD -30% and full-window Sharpe 1.79 / +855% /
# DD -35% / 8 of 10 quarters positive (btr_01m69npdg72gr22ygwya3wtvbw, btr_01m69npfh8yh9s625szn6tr5wz) are NOT achievable forward.
# Check: the same rule on a basket of names that already existed before 2025 reads full-window Sharpe 0.33 / +7.5% / DD -71% and OOS 0.15
# (str_01m69nekhr5kw2p5xk64etgh8b). The honest version is supertrend_bollinger_causal_top15.keel.py (weekly causal top-15).
# Rule: hold a name while SuperTrend(10,3) is green, price sits in the upper half of its 20d Bollinger channel and ATR7/ATR21 > 0.85.
# Sizing: 33% of equity per open name, gross capped at 1x, one order in and one out per position (on_change).
# Lines below are the Keel source verbatim.
Globals(target_timeframe="1d", bar_offset="12h")

Universe(mode="top_volume", top_n=15, market="perp", resolved=["BTC", "DOGE", "ETH", "GRAM", "HYPE", "LINK", "LIT", "PUMP", "SOL", "SUI", "VVV", "XPL", "XRP", "ZEC", "kPEPE"], resolved_at="2026-07-06T19:04:20.109737+00:00")

Execution(rebalance="on_change", min_trade_size=0.05)

Pipeline([
    PriceDataLoader(),
    {
        "st_green": [SuperTrend(period=10, multiplier=3.0), AboveThresholdFilter(threshold=0.0)],
        "bb_confirms": [BollingerBands(period=20, num_std=2.0), AboveThresholdFilter(threshold=0.5)],
        "bands_not_flat": [VolatilitySqueeze(short_period=7, long_period=21), AboveThresholdFilter(threshold=0.85)],
    },
    MaskAnd(),
    FixedWeightSizer(weight_per_position=0.33),
    LeverageCap(max_leverage=1.0),
], name="supertrend_bollinger_small")
