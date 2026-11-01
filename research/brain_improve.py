import json, math, sys
sys.path.insert(0,'.')
import brain as B
cfg=json.load(open("config.json"))["exchanges"]["solana"]
b=B.Brain.__new__(B.Brain); b.st={}; b.ctx={}
data=b.build_dataset(cfg,max_fetch=0)
# raw recs for extra features
raw={}
for l in open("candidates_solana.jsonl"):
    try:r=json.loads(l)
    except:continue
    raw[(r.get("mint"),r.get("ts"))]=r
import datetime as dt
idx={}
for (m,ts),r in raw.items():
    try: idx[(m,round(dt.datetime.fromisoformat(ts).timestamp()))]=r
    except: pass
def extra(d):
    r=idx.get((d["mint"],round(d["t"])),{}); P=r.get("parts") or {}; Q=P.get("parts") or {}; I=r.get("insider") or {}
    return {"hg_strong":Q.get("holder_growth",0)>=6,"liq_trend_neg":Q.get("liq_growth",0)<0,
            "vol_hi":abs(P.get("m5") or 0)>=5,"h1_dump":(P.get("h1") or 0)<=-10,
            "ins_netbuy":(I.get("buys",I.get("conv",0)) or 0)>(I.get("sells",0) or 0),"liq_mid":150000>(r.get("liq") or 0)>=80000}
def stats(sel):
    if not sel: return dict(n=0,avg=None,pf=None)
    r=[d["ret"] for d in sel]; g=sum(x for x in r if x>0); l=-sum(x for x in r if x<=0)
    return dict(n=len(r),avg=round(sum(r)/len(r)*100,2),pf=round(g/l,2) if l else 99)
def run(data,K,DAMP,thr=0.0):
    B.K,B.DAMP=K,DAMP
    cut=int(len(data)*0.7); tr,te=data[:cut],data[cut:]
    m=b.fit(tr); t=B.Brain.__new__(B.Brain); t.st=m; t.ctx={}
    return stats([d for d in te if t._ev(d["S"])>thr]), tr
print("n",len(data))
cur,_=run(data,20,0.5); print("CURRENT",cur)
data2=[{**d,"S":{**d["S"],**extra(d)}} for d in data]
print("FEATS",run(data2,20,0.5)[0])
# hyperparams chosen on inner validation (last 30% of train) to avoid test snooping
cut=int(len(data)*0.7)
for name,D in (("base",data),("feats",data2)):
    tr=D[:cut]; best=None
    for K in (10,20,40):
        for dp in (0.3,0.5,0.8):
            for th in (0.0,0.01):
                s,_=run(tr,K,dp,th)
                if s["n"]>=8 and (best is None or s["avg"]>best[0]["avg"]): best=(s,K,dp,th)
    print(name,"best inner",best, "-> OOS",run(D,*best[1:])[0])
print("robustness splits")
for c in (0.5,0.6,0.7,0.8):
    k=int(len(data)*c)
    for lab,K,dp,th in (("cur",20,0.5,0.0),("new",10,0.3,0.01)):
        B.K,B.DAMP=K,dp; m=b.fit(data[:k]); t=B.Brain.__new__(B.Brain); t.st=m; t.ctx={}
        print(c,lab,stats([d for d in data[k:] if t._ev(d["S"])>th]))
print("extra feat on-rates",{k:sum(extra(d)[k] for d in data) for k in extra(data[0])})
