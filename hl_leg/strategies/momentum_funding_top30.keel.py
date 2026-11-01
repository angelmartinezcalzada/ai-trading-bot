# Keel DSL — "HL momentum+funding top30" (library fork, str_01m69h9jq7qbq0gx8m5kfpq2yv v1). Continuous weights over 30 names:
# NOT runnable with a small account (Keel realism: ~$15k needed so that <5% of orders fall under the $10 minimum).
# Kept as the reference for when capital allows it: IS Sharpe 1.85 / DD 16.6%, OOS Sharpe 1.99 / DD 11.7%.
Globals(target_timeframe="1d", bar_offset="12h")

Universe(mode="top_volume", top_n=30, market="perp")

Execution(rebalance="buffered", buffer_threshold=0.2, buffer_mode="relative", rebalance_method="to_edge")

Pipeline([
    PriceDataLoader(),
    {
        "momentum": [ROC(period=14), CrossSectionalZScore()],
        "carry": [FundingDataLoader(use_cache=True), NegateTransform(), CrossSectionalZScore()],
    },
    ForecastCombiner(weights={"momentum": 0.7, "carry": 0.3}),
    ForecastScaler(avg_abs_target=10.0),
    ForecastCapper(limit=20.0),
    ForecastWeightNormalizer(target_leverage=1.0),
], name="momentum_funding_hyperliquid")
