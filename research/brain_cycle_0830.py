import json,sys,bisect,datetime as dt
sys.path.insert(0,'.')
exec(open("research/brain_cycle_0630.py").read().split("for x in (0.02")[0])   # reuse dataset/stats/model/gate helpers
# flow features from Solana Tracker shadow log: nearest record for the mint within 2h before entry
st={}
for l in open("data/st_shadow.jsonl"):
    try:r=json.loads(l); st.setdefault(r["mint"],[]).append(r)
    except: pass
for v in st.values(): v.sort(key=lambda r:r["t"])
def flow(d):
    v=st.get(d["mint"]);
    if not v: return None
    ts=[r["t"] for r in v]; i=bisect.bisect_right(ts,d["t"])-1
    if i<0 or d["t"]-v[i]["t"]>7200: return None
    f=v[i].get("f") or {}; b,s=f.get("buys") or 0,f.get("sells") or 0
    return {"st_buy_dom":b>1.5*max(s,1),"st_snipers_lo":(f.get("snipers") or 0)<5,"st_bundle_lo":(f.get("bundlers") or 0)<5,
            "st_top10_lo":(f.get("top10") or 100)<25,"st_pass":v[i].get("verdict")=="pass","st_score_hi":(f.get("st_score") or 0)>=50}
cov=0
for d in data:
    F=flow(d); d["S2"]={**d["S"],**F} if F else d["S"]; cov+=bool(F)
print("rows",len(data),"with ST flow",cov,"U",len(U),stats(U),"latest",dt.datetime.fromtimestamp(data[-1]["t"]))
FU=[d for d in U if d["S2"] is not d["S"]]; print("flow-covered U",stats(FU))
for k in ("st_buy_dom","st_snipers_lo","st_bundle_lo","st_top10_lo","st_pass","st_score_hi"):
    print(k,"on",stats([d for d in FU if d["S2"][k]]),"off",stats([d for d in FU if not d["S2"][k]]))
for c in (0.5,0.6,0.7,0.8):
    k=int(len(U)*c); tc=U[k]["t"]; T=U[k:]
    cur=model(purge([d for d in data if d["t"]<tc],tc)); out={"cur":stats([d for d in T if gate(cur,d)])}
    for K in (5,10):
        tr=[{**d,"S":d["S2"]} for d in purge(U[:k],tc)]; m=model(tr,K,0.3)
        TT=[{**d,"S":d["S2"]} for d in T]; sel=[d for d in TT if gate(m,d)]
        out[f"flow_K{K}"]=stats(sel); out[f"flow_K{K}_maxev"]=round(max(m._ev(d["S"]) for d in TT)*100,2)
    print(c,"test",len(T),json.dumps(out))
