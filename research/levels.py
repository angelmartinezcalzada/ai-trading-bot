"""Per-coin dynamic levels (shared by research + live memebot).
bars: list [t,o,h,l,c,v] 1m, oldest first, ending at/just before entry."""
def atr(b, n=30):
    b = b[-(n+1):]
    if len(b) < 5: return None
    tr = [max(x[2], p[4]) - min(x[3], p[4]) for p, x in zip(b, b[1:])]
    return sum(tr)/len(tr)
def poc(b, n=120, bins=24):
    b = b[-n:]; lo = min(x[3] for x in b); hi = max(x[2] for x in b)
    if hi <= lo: return None
    v = [0.0]*bins
    for x in b: v[min(bins-1, int((x[4]-lo)/(hi-lo)*bins))] += x[5] or 0
    i = max(range(bins), key=lambda k: v[k]); return lo + (i+.5)*(hi-lo)/bins
def levels(b, entry, P, rt):
    """returns dict(stop, tp1, trail_k, atr, sup, res) using structure + ATR. P: ks,ktp,ktr"""
    a = atr(b) or entry*0.01; a = max(a, entry*0.002)
    swing_lo = min(x[3] for x in b[-30:]); swing_hi = max(x[2] for x in b[-60:]); pc = poc(b)
    sup = max([s for s in (swing_lo, pc) if s and s < entry - 0.3*a] or [entry - P["ks"]*a])
    stop = min(entry - P["ks"]*a, sup - 0.5*a)                     # below structure AND >= k*ATR away
    dist = min(0.25, max(0.02 + rt, (entry-stop)/entry)); stop = entry*(1-dist)
    res = swing_hi if swing_hi > entry*(1+max(0.03, 1.5*a/entry)) else None
    tp1 = max(res or 0, entry + P["ktp"]*a)
    return dict(stop=stop, tp1=tp1, atr=a, sup=sup, res=res, dist=dist, poc=pc, swing_lo=swing_lo, swing_hi=swing_hi)
