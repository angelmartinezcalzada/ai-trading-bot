# Keel DSL — "HL meme-perps confluence 4h" (str_01m69hjqs60d0hk6nz972qyvkg v1): the memecoin thesis of the Solana bot moved
# to liquid Hyperliquid perps (4.5 bps fees instead of 1-3% round trips). RESULT (2024-08-15..2026-03-31): Sharpe 0.70,
# max drawdown -53%, PF 1.11 — versus Sharpe 1.84 / DD -30% for the same rule on the top-15 majors. Evidence that the
# memecoin universe, not the execution venue, is what loses money. REJECTED.
Globals(target_timeframe="4h")

Universe(mode="manual", symbols=["DOGE", "kPEPE", "WIF", "kBONK", "FARTCOIN", "POPCAT", "PUMP", "SPX", "PENGU", "TRUMP", "MOODENG", "PNUT", "GOAT", "BRETT", "TURBO", "kFLOKI", "kSHIB", "USELESS"], market="perp")

Execution(rebalance="on_change")
# pipeline identical to confluence_4h_small.keel.py with EqualWeightSizer(target_leverage=1.0, max_weight=0.34)
