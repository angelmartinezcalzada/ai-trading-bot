import json,sys,datetime as dt
sys.path.insert(0,'.')
import brain as B
cfg=json.load(open("config.json"))["exchanges"]["solana"]; floor=cfg.get("brain_min_score",0)
b=B.Brain.__new__(B.Brain); b.st={}; b.ctx={}
data=b.build_dataset(cfg,max_fetch=0); data.sort(key=lambda d:d["t"])
raw={}
for l in open("candidates_solana.jsonl"):
    try:r=json.loads(l); raw[(r["mint"],round(dt.datetime.fromisoformat(r["ts"]).timestamp()))]=r
    except: pass
for d in data:
    r=raw.get((d["mint"],round(d["t"])),{}); d["rt"]=(r.get("roundtrip_loss_pct") or 3.0)/100; d["sym"]=r.get("sym") or r.get("symbol")
def stats(sel):
    if not sel: return dict(n=0)
    r=[d["ret"] for d in sel]; g=sum(x for x in r if x>0); l=-sum(x for x in r if x<=0)
    return dict(n=len(r),m=len({d["mint"] for d in sel}),avg=round(sum(r)/len(r)*100,2),pf=round(g/l,2) if l else 99,worst=round(min(r)*100,1))
def model(tr,K=10,DP=0.3):
    B.K,B.DAMP=K,DP; m=b.fit(tr); t=B.Brain.__new__(B.Brain); t.st=m; t.ctx={}; return t
def purge(D,k): tc=D[k]["t"]; return [d for d in D[:k] if d.get("t_exit",d["t"])<=tc]
print("n",len(data),"mints",len({d["mint"] for d in data}),"floor",floor,"all",stats(data))
cut=int(len(data)*0.7); te=data[cut:]; t=model(purge(data,cut))
evs=sorted(((round(t._ev(d["S"])*100,2),round(d["ret"]*100,1),d["sym"],d["score"]) for d in te),reverse=True)
print("top EV test",evs[:10])
print("worst test rows",sorted(((round(d["ret"]*100,1),d["sym"],[k for k,v in d["S"].items() if v]) for d in te))[:6])
print("best test rows (missed)",sorted(((round(d["ret"]*100,1),d["sym"],round(t._ev(d["S"])*100,2),d["score"]) for d in te),reverse=True)[:6])
gate=lambda t,d,th=0.01: t._ev(d["S"])>max(th,3*d["rt"]) and d["score"]>=floor
gate_nofloor=lambda t,d: t._ev(d["S"])>max(0.01,3*d["rt"])
for c in (0.5,0.6,0.7,0.8):
    k=int(len(data)*c); a=model(purge(data,k)); T=data[k:]
    out={"cur":stats([d for d in T if gate(a,d)]),"cur_nofloor":stats([d for d in T if gate_nofloor(a,d)])}
    for K,DP in ((5,0.3),(20,0.3),(10,0.5),(10,0.2),(20,0.5)):
        m=model(purge(data,k),K,DP); out[f"K{K}D{DP}"]=stats([d for d in T if gate(m,d)]); out[f"K{K}D{DP}_nf"]=stats([d for d in T if gate_nofloor(m,d)])
    print(c,"test",len(T),json.dumps(out))
print("--- tails")
bad=[d for d in data if d["ret"]<=-0.3]; print("rows<=-30%",len(bad),sorted({d["sym"] for d in bad}))
print("win rate",round(sum(d["ret"]>0 for d in data)/len(data),3))
def model_w(tr,cap,K=10,DP=0.3):
    t=model([{**d,"ret":max(d["ret"],cap)} for d in tr],K,DP); return t
for c in (0.5,0.6,0.7,0.8):
    k=int(len(data)*c); T=data[k:]; out={}
    for cap in (-0.3,-0.15,-0.08):
        m=model_w(purge(data,k),cap)
        out[f"cap{cap}"]=stats([d for d in T if gate(m,d)]); out[f"cap{cap}_ev0"]=stats([d for d in T if m._ev(d["S"])>0 and d["score"]>=floor])
        out[f"cap{cap}_maxev"]=round(max(m._ev(d["S"]) for d in T)*100,2)
    print(c,json.dumps(out))
