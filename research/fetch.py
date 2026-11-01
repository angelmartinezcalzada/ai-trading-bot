import requests,json,time,os,pandas as pd
from concurrent.futures import ThreadPoolExecutor
B="https://data-api.binance.vision/api/v3"; F="https://fapi.binance.com/fapi/v1"
START=int(pd.Timestamp("2023-10-01").timestamp()*1000)
fut={s["symbol"] for s in requests.get(F+"/exchangeInfo").json()["symbols"] if s["contractType"]=="PERPETUAL"}
t=requests.get(B+"/ticker/24hr").json()
stable={"USDC","FDUSD","TUSD","USDP","DAI","EUR","USD1","XUSD","BFUSD","PAXG","WBTC","WBETH","AEUR"}
cand=[x for x in t if x["symbol"].endswith("USDT") and x["symbol"] in fut and x["symbol"][:-4] not in stable]
cand.sort(key=lambda x:-float(x["quoteVolume"]))
def kl(sym,iv):
    out=[];st=START
    while True:
        r=requests.get(B+"/klines",params=dict(symbol=sym,interval=iv,startTime=st,limit=1000),timeout=20).json()
        if not isinstance(r,list) or not r: break
        out+=r; st=r[-1][0]+1
        if len(r)<1000: break
    return out
def fr(sym):
    out=[];st=START
    while True:
        r=requests.get(F+"/fundingRate",params=dict(symbol=sym,startTime=st,limit=1000),timeout=20).json()
        if not isinstance(r,list) or not r: break
        out+=r; st=r[-1]["fundingTime"]+1
        if len(r)<1000: break
        time.sleep(0.3)
    return out
syms=[]
for x in cand:
    if len(syms)>=50: break
    d=kl(x["symbol"],"1d")
    if len(d)<500: continue
    syms.append(x["symbol"])
print(len(syms),syms)
def job(s):
    for iv in ("1d","4h","1h"):
        json.dump(kl(s,iv),open(f"data/{s}_{iv}.json","w"))
    json.dump(fr(s),open(f"data/{s}_fr.json","w"))
with ThreadPoolExecutor(5) as e: list(e.map(job,syms))
json.dump(syms,open("data/syms.json","w"))
