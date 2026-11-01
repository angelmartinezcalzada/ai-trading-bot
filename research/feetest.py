exec(open("research.py").read().split("res={}")[0])
C4,H4,L4=load("4h"); R4=C4.pct_change(); b4=C4["BTCUSDT"]
src=open("research.py").read()
exec(src[src.index("def breakout_fn"):src.index('report("vol_breakout_1d"')])
exec(src[src.index("def xs4"):src.index('report("xs_momentum_rotation_4h"')])
f=breakout_fn(C4,H4,L4,6)
for nm,r in [("bo4h",f(120,40,50)),("xs4",xs4(60,5,12,50))]:
    print(FEE,nm,"IS",stats(r[r.index<SPLIT]),"OOS",stats(r[r.index>=SPLIT]),"trades/yr" if nm=="bo4h" else "",len(r)/3 if nm=="bo4h" else "")
