exec(open("research.py").read().split("res={}")[0])
import itertools
C4,H4,L4=load("4h"); R4=C4.pct_change(); b4=C4["BTCUSDT"]
src=open("research.py").read()
exec(src[src.index("def breakout_fn"):src.index('report("vol_breakout_1d"')])
exec(src[src.index("def xs4"):src.index('report("xs_momentum_rotation_4h"')])
P=[pd.Timestamp(x) for x in ["2023-10-01","2024-06-01","2025-02-01","2025-10-01","2026-11-01"]]
def per(r): return [round(pf(r[(r.index>=P[i])&(r.index<P[i+1])]),2) for i in range(4)]
f=breakout_fn(C4,H4,L4,6)
for p in itertools.product([90,120,180],[30,40,60],[0,50]): print("bo4h",p,per(f(*p)))
for p in itertools.product([30,42,60],[5,7],[6,12],[50]): print("xs4",p,per(xs4(*p)))
