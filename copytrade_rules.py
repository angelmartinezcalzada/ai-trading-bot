"""Exit rules of the paper copy-trade (pure functions, tested in tests/test_rules.py).
rug = entry pool gone, or liquidity pulled >80 %, on 2 consecutive polls: DexScreener returns liquidity=0 / a missing pair on pumpswap data
gaps, and 15 of the first 36 'rug' closes had an exit price ABOVE entry (31-oct review). One bad print only arms the counter: the position
waits for confirmation instead of exiting on a stale price."""
def rug_step(q, p, liq):
    """updates q['rug_n'] from one poll (p = price, 0 when the pool is gone; liq = pool liquidity USD) and returns rug (bool)"""
    liq_known = bool(liq) and liq > 0
    q["rug_n"] = q.get("rug_n", 0)+1 if (p == 0 or (liq_known and q.get("liq") and liq < 0.2*q["liq"])) else 0
    return q["rug_n"] >= 2
def exit_reason(q, rug, r, insider_sold, now, tp, sl, hold):
    if rug: return "rug"
    if q.get("rug_n"): return None
    if insider_sold: return "insider_sell"
    if r >= tp: return "tp"
    if r <= -sl: return "sl"
    if now-q["t"] > hold: return "time"
    return None
