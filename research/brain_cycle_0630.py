import json,sys,datetime as dt
sys.path.insert(0,'.')
import brain as B
from memebot import brand_fake, stable_fake
cfg=json.load(open("config.json"))["exchanges"]["solana"]; floor=cfg.get("brain_min_score",0)
b=B.Brain.__new__(B.Brain); b.st={}; b.ctx={}
data=b.build_dataset(cfg,max_fetch=0); data.sort(key=lambda d:d["t"])
oc=json.load(open("ohlcv_cache.json"))
raw={}
for l in open("candidates_solana.jsonl"):
    try:r=json.loads(l); raw[(r["mint"],round(dt.datetime.fromisoformat(r["ts"]).timestamp()))]=r
    except: pass
for d in data:
    r=raw.get((d["mint"],round(d["t"])),{}); d["rt"]=(r.get("roundtrip_loss_pct") or 3.0)/100; d["sym"]=r.get("sym") or r.get("symbol") or ""; d["parts"]=r.get("parts") or {}; d["price"]=r.get("price"); d["pair"]=r.get("pair")
def vetoed(d): return brand_fake(d["sym"]) or stable_fake(d["sym"],d["price"]) or (d["parts"].get("h1") or 0)>cfg.get("max_entry_h1_pct",50)
U=[d for d in data if not vetoed(d)]
# quick-take relabel: exit at first bar whose high gives net >= x (after roundtrip cost), if it comes before the original exit; else keep original label
def quick(d,x):
    o=oc.get(d["pair"]) or {}; path=[b_ for b_ in o.get("bars",[]) if d["t"]<=b_[0]<=d.get("t_exit",d["t"])]
    if not path: return d["ret"]
    p0=path[0][1]
    for b_ in path[1:]:
        if p0 and b_[2]/p0-1-d["rt"]>=x: return x
    return d["ret"]
def stats(sel,key="ret"):
    if not sel: return dict(n=0)
    r=[d[key] for d in sel]; g=sum(x for x in r if x>0); l=-sum(x for x in r if x<=0)
    return dict(n=len(r),m=len({d["mint"] for d in sel}),avg=round(sum(r)/len(r)*100,2),pf=round(g/l,2) if l else 99)
def model(tr,K=10,DP=0.3):
    B.K,B.DAMP=K,DP; m=b.fit(tr); t=B.Brain.__new__(B.Brain); t.st=m; t.ctx={}; return t
def purge(D,tc): return [d for d in D if d.get("t_exit",d["t"])<=tc]
gate=lambda t,d: t._ev(d["S"])>max(0.01,3*d["rt"]) and d["score"]>=floor
print("rows",len(data),"all",stats(data),"| veto-consistent",len(U),stats(U),"mints",len({d["mint"] for d in U}),"latest",dt.datetime.fromtimestamp(data[-1]["t"]))
for x in (0.02,0.03,0.05):
    for d in data: d[f"q{x}"]=quick(d,x)
    print("quick",x,"U",stats(U,f"q{x}"))
for c in (0.5,0.6,0.7,0.8):
    k=int(len(U)*c); tc=U[k]["t"]; T=U[k:]
    cur=model(purge([d for d in data if d["t"]<tc],tc)); out={"cur":stats([d for d in T if gate(cur,d)])}
    for x in (0.02,0.03,0.05):
        for K in (5,10):
            tr=[{**d,"ret":d[f"q{x}"]} for d in purge(U[:k],tc)]
            m=model(tr,K,0.3); sel=[d for d in T if gate(m,d)]
            out[f"q{x}_K{K}"]=stats(sel,f"q{x}"); out[f"q{x}_K{K}_maxev"]=round(max(m._ev(d["S"]) for d in T)*100,2)
    print(c,"test",len(T),json.dumps(out))
