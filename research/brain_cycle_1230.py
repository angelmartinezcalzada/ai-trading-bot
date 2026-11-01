import json,sys,datetime as dt
sys.path.insert(0,'.')
exec(open("research/brain_cycle_0630.py").read().split("for x in (0.02")[0])
# improvement: exit timing - relabel with shorter max hold (exit at close of first bar >= H minutes after entry, if before original exit)
def hold(d,H):
    o=oc.get(d["pair"]) or {}; path=[b_ for b_ in o.get("bars",[]) if d["t"]<=b_[0]<=d.get("t_exit",d["t"])]
    if len(path)<2 or not path[0][1]: return d["ret"]
    p0=path[0][1]
    for b_ in path[1:]:
        if b_[0]-d["t"]>=H*60: return b_[4]/p0-1-d["rt"]
    return d["ret"]
cov=0
for H in (15,30,60):
    for d in data: d[f"h{H}"]=hold(d,H)
    print("hold",H,"U",stats(U,f"h{H}"))
for c in (0.5,0.6,0.7,0.8):
    k=int(len(U)*c); tc=U[k]["t"]; T=U[k:]
    cur=model(purge([d for d in data if d["t"]<tc],tc)); out={"cur":stats([d for d in T if gate(cur,d)])}
    for H in (15,30,60):
        for K in (5,10):
            tr=[{**d,"ret":d[f"h{H}"]} for d in purge(U[:k],tc)]
            m=model(tr,K,0.3); sel=[d for d in T if gate(m,d)]
            out[f"h{H}_K{K}"]=stats(sel,f"h{H}"); out[f"h{H}_K{K}_maxev"]=round(max(m._ev(d["S"]) for d in T)*100,2)
    print(c,"test",len(T),json.dumps(out))
