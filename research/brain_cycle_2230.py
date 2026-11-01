import json,sys,collections,datetime as dt,time
sys.path.insert(0,'.')
import brain as B
cfg=json.load(open("config.json"))["exchanges"]["solana"]
b=B.Brain.__new__(B.Brain); b.st={}; b.ctx={}
data=b.build_dataset(cfg,max_fetch=0); data.sort(key=lambda d:d["t"])
raw={}
for l in open("candidates_solana.jsonl"):
    try:r=json.loads(l)
    except:continue
    try: raw[(r["mint"],round(dt.datetime.fromisoformat(r["ts"]).timestamp()))]=r
    except: pass
for d in data:
    r=raw.get((d["mint"],round(d["t"])),{}); d["rt"]=(r.get("roundtrip_loss_pct") or 3.0)/100; d["sym"]=r.get("sym") or r.get("symbol")
def stats(sel):
    if not sel: return dict(n=0,avg=None,pf=None)
    r=[d["ret"] for d in sel]; g=sum(x for x in r if x>0); l=-sum(x for x in r if x<=0)
    return dict(n=len(r),avg=round(sum(r)/len(r)*100,2),pf=round(g/l,2) if l else 99,worst=round(min(r)*100,1))
def model(tr,K=10,DP=0.3):
    B.K,B.DAMP=K,DP; m=b.fit(tr); t=B.Brain.__new__(B.Brain); t.st=m; t.ctx={}; return t
print("n",len(data))
# critique on 70/30
cut=int(len(data)*0.7); tr,te=data[:cut],data[cut:]
t=model(tr); sel=[d for d in te if t._ev(d["S"])>0.01]; print("CUR 70/30",stats(sel))
for d in sorted(sel,key=lambda d:d["ret"])[:6]: print("LOSS",round(d["ret"]*100,1),d["sym"],round(d["rt"]*100,1),[k for k,v in d["S"].items() if v])
for d in sorted([d for d in te if t._ev(d["S"])<=0.01],key=lambda d:-d["ret"])[:4]: print("MISS",round(d["ret"]*100,1),d["sym"],round(t._ev(d["S"])*100,2))
W=[d for d in sel if d["ret"]>0];L=[d for d in sel if d["ret"]<=0]
print("rt cost W/L",round(sum(d["rt"] for d in W)/max(1,len(W))*100,2),round(sum(d["rt"] for d in L)/max(1,len(L))*100,2))
def addf(D,f): return [{**d,"S":{**d["S"],**f(d)}} for d in D]
variants={
 "young_hot": (lambda D: addf(D,lambda d:{"young_hot":d["S"]["young"] and d["S"]["h1_hot"]}), lambda t,d:t._ev(d["S"])>0.01),
 "ev_cost0.5": (lambda D:D, lambda t,d:t._ev(d["S"])>0.005+0.5*d["rt"]),
 "ev_cost1": (lambda D:D, lambda t,d:t._ev(d["S"])>d["rt"]),
 "ev_cost0.3": (lambda D:D, lambda t,d:t._ev(d["S"])>0.005+0.3*d["rt"]),
 "yh+cost0.5": (lambda D: addf(D,lambda d:{"young_hot":d["S"]["young"] and d["S"]["h1_hot"]}), lambda t,d:t._ev(d["S"])>0.005+0.5*d["rt"]),
}
for c in (0.5,0.6,0.7,0.8):
    k=int(len(data)*c); a=model(data[:k]); print(c,"cur",stats([d for d in data[k:] if a._ev(d["S"])>0.01]))
    for name,(prep,rule) in variants.items():
        D=prep(data); m=model(D[:k]); print("   ",name,stats([d for d in D[k:] if rule(m,d)]))
print("--- with live gate EV>=3x rt")
yh=lambda D: addf(D,lambda d:{"young_hot":d["S"]["young"] and d["S"]["h1_hot"]})
for c in (0.5,0.6,0.7,0.8):
    k=int(len(data)*c); a=model(data[:k]); D=yh(data); m=model(D[:k])
    g=lambda t,d: t._ev(d["S"])>max(0.01,3*d["rt"])
    print(c,"cur",stats([d for d in data[k:] if g(a,d)]),"yh",stats([d for d in D[k:] if g(m,d)]),"yh+c",stats([d for d in D[k:] if g(m,d) and m._ev(d["S"])>0.005+0.5*d["rt"]]))
