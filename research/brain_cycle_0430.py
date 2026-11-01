import json,sys,datetime as dt
sys.path.insert(0,'.')
import brain as B
from memebot import brand_fake, stable_fake
cfg=json.load(open("config.json"))["exchanges"]["solana"]; floor=cfg.get("brain_min_score",0)
b=B.Brain.__new__(B.Brain); b.st={}; b.ctx={}
data=b.build_dataset(cfg,max_fetch=0); data.sort(key=lambda d:d["t"])
raw={}
for l in open("candidates_solana.jsonl"):
    try:r=json.loads(l); raw[(r["mint"],round(dt.datetime.fromisoformat(r["ts"]).timestamp()))]=r
    except: pass
for d in data:
    r=raw.get((d["mint"],round(d["t"])),{}); d["rt"]=(r.get("roundtrip_loss_pct") or 3.0)/100; d["sym"]=r.get("sym") or r.get("symbol") or ""; d["parts"]=r.get("parts") or {}; d["price"]=r.get("price")
def vetoed(d): return brand_fake(d["sym"]) or stable_fake(d["sym"],d["price"]) or (d["parts"].get("h1") or 0)>cfg.get("max_entry_h1_pct",50)
U=[d for d in data if not vetoed(d)]
for d in data:
    h1=d["parts"].get("h1") or 0; d["S"]={**d["S"],"rt_low":d["rt"]<0.015,"score_hi":d["score"]>=60,"h1_neg":h1<0,"h1_mid":0<=h1<=20}
def stats(sel):
    if not sel: return dict(n=0)
    r=[d["ret"] for d in sel]; g=sum(x for x in r if x>0); l=-sum(x for x in r if x<=0)
    return dict(n=len(r),m=len({d["mint"] for d in sel}),avg=round(sum(r)/len(r)*100,2),pf=round(g/l,2) if l else 99)
def model(tr,K=10,DP=0.3):
    B.K,B.DAMP=K,DP; m=b.fit(tr); t=B.Brain.__new__(B.Brain); t.st=m; t.ctx={}; return t
def purge(D,tc): return [d for d in D if d.get("t_exit",d["t"])<=tc]
gate=lambda t,d: t._ev(d["S"])>max(0.01,3*d["rt"]) and d["score"]>=floor
print("rows",len(data),"all",stats(data),"| veto-consistent",len(U),stats(U),"mints",len({d["mint"] for d in U}),"latest",dt.datetime.fromtimestamp(data[-1]["t"]))
for c in (0.5,0.6,0.7,0.8):
    k=int(len(U)*c); tc=U[k]["t"]; T=U[k:]
    cur=model(purge([d for d in data if d["t"]<tc],tc)); out={"cur":stats([d for d in T if gate(cur,d)])}
    for K,DP in ((10,0.3),(5,0.3)):
        for cap in (None,-0.15):
            tr=purge(U[:k],tc); tr=[{**d,"ret":max(d["ret"],cap)} if cap else d for d in tr]
            m=model(tr,K,DP); out[f"U_K{K}D{DP}c{cap}"]=stats([d for d in T if gate(m,d)])
            out[f"U_K{K}D{DP}c{cap}_maxev"]=round(max(m._ev(d["S"]) for d in T)*100,2)
    print(c,"test",len(T),json.dumps(out))
