import json,sys,datetime as dt
sys.path.insert(0,'.')
exec(open("research/brain_cycle_0630.py").read().split("for x in (0.02")[0])
# improvement: cost-aware features (round-trip cost buckets) + score buckets + lower shrinkage hyperparams
for d in data:
    d["S3"]={**d["S"],"rt_lo":d["rt"]<=0.015,"rt_mid":0.015<d["rt"]<=0.025,"score50":d["score"]>=50}
print("U rt<=1.5%",stats([d for d in U if d["rt"]<=0.015]),"score>=50",stats([d for d in U if d["score"]>=50]),"both",stats([d for d in U if d["rt"]<=0.015 and d["score"]>=50]))
for c in (0.5,0.6,0.7,0.8):
    k=int(len(U)*c); tc=U[k]["t"]; T=U[k:]
    cur=model(purge([d for d in data if d["t"]<tc],tc)); out={"cur":stats([d for d in T if gate(cur,d)])}
    TT=[{**d,"S":d["S3"]} for d in T]
    for K in (3,5,10):
        for DP in (0.1,0.3):
            tr=[{**d,"S":d["S3"]} for d in purge(U[:k],tc)]; m=model(tr,K,DP)
            out[f"K{K}D{DP}"]=stats([d for d in TT if gate(m,d)]); out[f"K{K}D{DP}_maxev"]=round(max(m._ev(d["S"]) for d in TT)*100,2)
    print(c,"test",len(T),json.dumps(out))
