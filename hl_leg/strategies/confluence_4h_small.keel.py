# Keel DSL — "HL confluence 4h top15" (library fork str_01m69h9kgf6hzebaetby47kk8t, v4 = 0.33/name, no stop; the backtests quoted are v4).
# REJECTED for the MVP: in-sample Sharpe 1.85 but out-of-sample (2026-04..10) Sharpe 0.53, PF 1.07 — the 4h clock pays
# ~10%/yr in fees and the edge did not survive. Kept for the record.
Globals(target_timeframe="4h")

Universe(mode="top_volume", top_n=15, market="perp")

Execution(rebalance="on_change")

ema_gate = Pipeline([
    {"fast": [EWMA(window=50)], "slow": [EWMA(window=200)]},
    Crossover(fast_key="fast", slow_key="slow"),
], name="ema_gate")

px_vs_50 = Pipeline([
    {"px": [EWMA(window=2)], "e50": [EWMA(window=50)]},
    Crossover(fast_key="px", slow_key="e50"),
], name="px_vs_50")

Pipeline([
    PriceDataLoader(),
    Store("ohlcv"),
    {
        "entries": [Pipeline([
            {"const": [ConstantForecast(value=1.0)],
             "setup": [Pipeline([
                 {"regime_up": [ema_gate, AboveThresholdFilter(threshold=0.0)],
                  "momentum_on": [MACD(fast_period=12, slow_period=26, signal_period=9), AboveThresholdFilter(threshold=0.0)],
                  "not_exhausted": [RSI(period=14), RangeSelector(low_threshold=45, high_threshold=70)]},
                 MaskAnd()], name="setup")]},
            ApplyMask(score_signal="const", filter_signal="setup"),
            Store("conf_entry")], name="entries")],
        "exits": [Pipeline([
            {"const": [ConstantForecast(value=1.0)],
             "bail": [Pipeline([
                 {"macd_flip": [MACD(fast_period=12, slow_period=26, signal_period=9), BelowThresholdFilter(threshold=0.0)],
                  "below_50": [px_vs_50, BelowThresholdFilter(threshold=0.0)]},
                 MaskOr()], name="bail")]},
            ApplyMask(score_signal="const", filter_signal="bail"),
            Store("conf_exit")], name="exits")],
    },
    TradeManager(entries="conf_entry", prices="ohlcv"),
    {"bail": [Load("conf_exit"), Exit()], "stop": [StopLoss(pct=0.08)]},
    Exposure(),
    FixedWeightSizer(weight_per_position=0.33),
    LeverageCap(max_leverage=1.0),
], name="confluence_small")
