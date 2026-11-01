import json,numpy as np,pandas as pd,itertools,warnings;warnings.filterwarnings("ignore")
syms=json.load(open("data/syms.json")); import os;FEE=float(os.environ.get("FEE","0.0015"))  # per side: 0.1% taker + 0.05% slip
SPLIT=pd.Timestamp("2025-04-01")
def load(iv):
    C,H,L={},{},{}
    for s in syms:
        k=json.load(open(f"data/{s}_{iv}.json"))
        if not k: continue
        d=pd.DataFrame(k).iloc[:,:5].astype(float); i=pd.to_datetime(d[0],unit="ms")
        C[s]=pd.Series(d[4].values,i);H[s]=pd.Series(d[2].values,i);L[s]=pd.Series(d[3].values,i)
    return pd.DataFrame(C),pd.DataFrame(H),pd.DataFrame(L)
def pf(r):
    r=pd.Series(r).dropna(); g=r[r>0].sum(); b=-r[r<0].sum(); return g/b if b>0 else np.nan
def stats(r):
    r=pd.Series(r).dropna(); 
    if len(r)==0: return dict(pf=np.nan,ret=0,n=0)
    eq=(1+r).cumprod(); dd=(eq/eq.cummax()-1).min()
    return dict(pf=round(pf(r),3),ret=round((eq.iloc[-1]-1)*100,1),dd=round(dd*100,1),n=len(r))
res={}
def report(name,grid_fn,grid,kind="daily"):
    rows=[]
    for p in grid:
        r=grid_fn(*p)  # returns pd.Series of returns (daily portfolio or per-trade indexed by entry time)
        a=r[r.index<SPLIT];b=r[r.index>=SPLIT]
        rows.append((p,pf(a),pf(b),stats(a),stats(b)))
    rows=[x for x in rows if x[3]["n"]>=10]
    best=max(rows,key=lambda x:(x[1] if x[1]==x[1] else -9))
    rob=np.mean([x[2]>1 for x in rows if x[2]==x[2]])
    res[name]=dict(best_params=best[0],IS=best[3],OOS=best[4],grid_share_oos_pf_gt1=round(rob,2),
                   median_oos_pf=round(np.nanmedian([x[2] for x in rows]),3))
    print(name,res[name],flush=True)
C,H,L=load("1d"); R=C.pct_change()
btc=C["BTCUSDT"]
# --- A cross-sectional momentum rotation (daily) ---
def xsmom(look,topn,reb,regime):
    sc=C.pct_change(look); w=pd.DataFrame(0.0,index=C.index,columns=C.columns)
    on=(btc>btc.rolling(regime).mean()) if regime else pd.Series(True,index=C.index)
    last=None
    for i,t in enumerate(C.index):
        if i%reb==0:
            row=sc.loc[t].dropna()
            last=pd.Series(0.0,index=C.columns)
            if on.loc[t] and len(row)>=topn: last[row.nlargest(topn).index]=1/topn
        w.loc[t]=last if last is not None else 0
    w=w.shift(1).fillna(0); turn=w.diff().abs().sum(1).fillna(0)
    return (w*R).sum(1)-turn*FEE
report("xs_momentum_rotation_1d",xsmom,itertools.product([7,14,28,56],[3,5,10],[1,3,7],[0,50,100]))
# --- B BTC trend regime alone (benchmark) & dominance proxy ---
def btcreg(n):
    w=(btc>btc.rolling(n).mean()).astype(float).shift(1); return w*R["BTCUSDT"]-w.diff().abs().fillna(0)*FEE
report("btc_trend_regime_1d",btcreg,[(n,) for n in [20,50,100,150,200]])
alt=R.drop(columns="BTCUSDT").mean(1)
def dom(n,regime):
    rel=(1+alt).cumprod()/(1+R["BTCUSDT"]).cumprod()   # alt/btc ratio ~ inverse dominance
    altseason=(rel>rel.rolling(n).mean()).shift(1); on=(btc>btc.rolling(regime).mean()).shift(1).astype(float)
    r=np.where(altseason,alt,R["BTCUSDT"])*on; r=pd.Series(r,index=R.index)
    sw=altseason.astype(float).diff().abs().fillna(0)+on.diff().abs().fillna(0)
    return r-sw*FEE*2
report("btc_dominance_rotation_1d",dom,itertools.product([10,20,50],[50,100]))
# --- C funding contrarian / filter ---
FR={}
for s in syms:
    f=json.load(open(f"data/{s}_fr.json"))
    if f: FR[s]=pd.Series([float(x["fundingRate"]) for x in f],pd.to_datetime([x["fundingTime"] for x in f],unit="ms")).resample("1D").sum()
FR=pd.DataFrame(FR).reindex(C.index)
def fund(look,topn,hold,side):
    sc=FR.rolling(look).mean(); w=pd.DataFrame(0.0,index=C.index,columns=C.columns); last=pd.Series(0.0,index=C.columns)
    for i,t in enumerate(C.index):
        if i%hold==0:
            row=sc.loc[t].dropna(); last=pd.Series(0.0,index=C.columns)
            if len(row)>=topn: last[(row.nsmallest(topn) if side=="neg" else row.nlargest(topn)).index]=1/topn
        w.loc[t]=last
    w=w.shift(1).fillna(0); return (w*R).sum(1)-w.diff().abs().sum(1).fillna(0)*FEE
report("funding_contrarian_long_lowest",fund,itertools.product([1,3,7],[3,5,10],[1,3,7],["neg"]))
report("funding_long_highest",fund,itertools.product([1,3,7],[3,5,10],[1,3,7],["pos"]))
# --- D volatility breakout (Donchian) on 4h and 1d, trade-based ---
def breakout_fn(C_,H_,L_,bpd):
    b=C_["BTCUSDT"]
    def f(n,m,regime):
        trades={}
        on=(b>b.rolling(regime*bpd).mean()) if regime else pd.Series(True,index=C_.index)
        for s in C_.columns:
            c=C_[s].values;hh=H_[s].rolling(n).max().shift(1).values;ll=L_[s].rolling(m).min().shift(1).values;o=on.values;idx=C_.index
            pos=None
            for i in range(len(c)):
                if np.isnan(c[i]) or np.isnan(hh[i]): continue
                if pos is None and c[i]>hh[i] and o[i]: pos=(i,c[i])
                elif pos is not None and (c[i]<ll[i]):
                    trades[(idx[pos[0]],s)]=c[i]/pos[1]-1-2*FEE; pos=None
        r=pd.Series(trades); r.index=[x[0] for x in r.index]; return r.sort_index()/10  # 10% size per trade
    return f
report("vol_breakout_1d",breakout_fn(C,H,L,1),itertools.product([10,20,55],[5,10,20],[0,50]))
C4,H4,L4=load("4h")
report("vol_breakout_4h",breakout_fn(C4,H4,L4,6),itertools.product([20,55,120],[10,20,40],[0,50]))
# --- E cross-sectional momentum on 4h ---
R4=C4.pct_change(); b4=C4["BTCUSDT"]
def xs4(look,topn,reb,regime):
    sc=C4.pct_change(look); on=(b4>b4.rolling(regime*6).mean()) if regime else pd.Series(True,index=C4.index)
    rk=sc.rank(1,ascending=False); w=((rk<=topn)&on.values[:,None]).astype(float)/topn
    w=w.where(pd.Series(np.arange(len(w))%reb==0,index=w.index),np.nan).ffill().shift(1).fillna(0)
    r=(w*R4).sum(1)-w.diff().abs().sum(1).fillna(0)*FEE; return r.resample("1D").sum()
report("xs_momentum_rotation_4h",xs4,itertools.product([6,18,42],[3,5,10],[1,6],[0,50]))
# --- F time-of-day (BTC + basket 1h) ---
C1,_,_=load("1h"); R1=C1.pct_change().mean(1)
hr=R1.index.hour
def tod(k):
    ins=R1[R1.index<SPLIT]; best=ins.groupby(ins.index.hour).mean().nlargest(k).index
    w=pd.Series(np.isin(hr,best).astype(float),index=R1.index); r=w*R1-w.diff().abs().fillna(0)*FEE
    return r.resample("1D").sum()
report("time_of_day_long_best_hours",tod,[(k,) for k in [2,4,6,8]])
json.dump(res,open("research_results.json","w"),default=str,indent=1)
