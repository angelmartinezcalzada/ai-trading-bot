import json,sys,datetime as dt,re
sys.path.insert(0,'.')
import brain as B
cfg=json.load(open("config.json"))["exchanges"]["solana"]
b=B.Brain.__new__(B.Brain); b.st={}; b.ctx={}
data=b.build_dataset(cfg,max_fetch=0)
raw={}
for l in open("candidates_solana.jsonl"):
    try:r=json.loads(l); raw[(r["mint"],round(dt.datetime.fromisoformat(r["ts"]).timestamp()))]=r
    except: pass
for d in data:
    r=raw.get((d["mint"],round(d["t"])),{}); d["sym"]=r.get("sym") or ""; d["parts"]=r.get("parts") or {}; d["price"]=r.get("price")
from memebot import brand_fake, stable_fake
def summ(n,S):
    W=[d for d in S if d["ret"]>0]; L=[d for d in S if d["ret"]<=-0.30]
    print(n,"n",len(S),"win",len(W),"loss30",len(L),"avg%.1f"%(100*sum(d["ret"] for d in S)/max(1,len(S))))
summ("all",data)
bv=[d for d in data if brand_fake(d["sym"]) or stable_fake(d["sym"],d["price"])]
summ("brand_vetoed",bv); print(sorted({d["sym"] for d in bv}))
rest=[d for d in data if d not in bv]; summ("after_brand",rest)
print("parts keys",list((data[0]["parts"] or {}).keys())[:30])
for k in ("m5","h1"):
  for th in (3,5,8,10,15,20,30,50):
    v=[d for d in rest if (d["parts"].get(k) or 0)>th]; summ(f"{k}>{th} vetoed",v)
fin=[d for d in rest if (d["parts"].get("h1") or 0)<=50]; summ("after_both",fin)
