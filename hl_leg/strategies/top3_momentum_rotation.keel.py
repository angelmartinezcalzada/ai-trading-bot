# Keel DSL — "HL top3 momentum rotation weekly (regime-gated)" (str_01m69hjq5ram4eg82br9myjz69 v2).
# RESULT (2024-08-15..2026-03-31): Sharpe 0.43, max drawdown -45%, PF 1.16. REJECTED (3-name concentration + weekly cadence
# is too slow to exit a crypto drawdown; the EMA10/50 market regime gate did not protect it).
Globals(target_timeframe="1d")

Universe(mode="top_volume", top_n=20, market="perp")

Execution(rebalance="on_change")

Pipeline([
    PriceDataLoader(),
    {
        "roc": [ROC(period=20)],
        "regime": [MarketTrendRegimeFilter(fast_period=10, slow_period=50)],
    },
    RegimeGate(signal_key="roc", index_key="regime", condition="index > 0"),
    TopNAssetSelector(n=3, method="largest", min_value=0.0),
    EqualWeightSizer(target_leverage=1.0, max_weight=0.34),
    WeightCadence(duration="7d", anchor="MONDAY", timezone="UTC"),
    FillNaN(fill_value=0.0),
], name="top3_momentum_rotation")
