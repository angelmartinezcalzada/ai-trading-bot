import json,sys,math
sys.path.insert(0,'.')
import brain as B
cfg=json.load(open("config.json"))["exchanges"]["solana"]
b=B.Brain.__new__(B.Brain); b.st={}; b.ctx={}
data=b.build_dataset(cfg,max_fetch=0); data.sort(key=lambda d:d["t"])
def stats(sel):
    if not sel: return dict(n=0,avg=None,pf=None)
    r=[d["ret"] for d in sel]; g=sum(x for x in r if x>0); l=-sum(x for x in r if x<=0)
    return dict(n=len(r),avg=round(sum(r)/len(r)*100,2),pf=round(g/l,2) if l else 99)
def model(tr,K,DP):
    B.K,B.DAMP=K,DP; m=b.fit(tr); t=B.Brain.__new__(B.Brain); t.st=m; t.ctx={}; return t
print("n",len(data))
cut=int(len(data)*0.7); tr,te=data[:cut],data[cut:]
t=model(tr,10,0.3); sel=[d for d in te if t._ev(d["S"])>0.01]
print("CUR OOS",stats(sel))
los=sorted(sel,key=lambda d:d["ret"])[:8]
for d in los: print("LOSS",round(d["ret"]*100,1),d.get("sym"),{k:v for k,v in d["S"].items() if v})
# feature on-rates among OOS losers vs winners
keys=list(data[0]["S"].keys())
L=[d for d in sel if d["ret"]<=0]; W=[d for d in sel if d["ret"]>0]
print("feat L/W rates",{k:(sum(bool(d["S"][k]) for d in L),sum(bool(d["S"][k]) for d in W)) for k in keys})
# missed winners: rejected by model but big ret
miss=sorted([d for d in te if t._ev(d["S"])<=0.01],key=lambda d:-d["ret"])[:5]
for d in miss: print("MISS",round(d["ret"]*100,1),d.get("sym"),round(t._ev(d["S"])*100,2))
# improvement candidates chosen on inner validation: min-support shrinkage via K and stricter EV
icut=int(len(tr)*0.7); best=None
for K in (5,10,20):
  for dp in (0.2,0.3,0.5):
    for th in (0.01,0.02,0.03):
      tm=model(tr[:icut],K,dp); s=stats([d for d in tr[icut:] if tm._ev(d["S"])>th])
      if s["n"]>=8 and (best is None or (s["avg"],s["pf"])>(best[0]["avg"],best[0]["pf"])): best=(s,K,dp,th)
print("inner best",best)
_,K,dp,th=best; tn=model(tr,K,dp); print("NEW OOS",stats([d for d in te if tn._ev(d["S"])>th]))
for c in (0.5,0.6,0.8):
    k=int(len(data)*c); a=model(data[:k],10,0.3); s1=stats([d for d in data[k:] if a._ev(d["S"])>0.01])
    n=model(data[:k],K,dp); s2=stats([d for d in data[k:] if n._ev(d["S"])>th]); print(c,"cur",s1,"new",s2)
