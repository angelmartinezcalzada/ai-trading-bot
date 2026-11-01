"""Walk-forward backtest (1h) of: trend-following, ML direction model (HistGradientBoosting), ensemble (trend+ML),
long-only (spot) and long+short (futures). Fees maker/taker configurable. Results -> bt_results.json"""
import os, sys, json, time, numpy as np, pandas as pd, requests
from sklearn.ensemble import HistGradientBoostingClassifier
import features as F
H = "https://data-api.binance.vision"; CACHE = "bt_data"; os.makedirs(CACHE, exist_ok=True)
HOLD = 6
def fetch(sym, days, tf="1h"):
    f = f"{CACHE}/{sym}_{tf}_{days}.pkl"
    if os.path.exists(f) and time.time()-os.path.getmtime(f) < 86400: return pd.read_pickle(f)
    end = int(time.time()*1000); start = end-days*86400000; rows = []
    while start < end:
        k = requests.get(H+"/api/v3/klines", params=dict(symbol=sym, interval=tf, startTime=start, limit=1000), timeout=15).json()
        if not k: break
        rows += k; start = k[-1][0]+1
    df = pd.DataFrame(rows).iloc[:, [0,1,2,3,4,5,9]].astype(float); df.columns = ["t","o","h","l","c","v","tb"]; df.to_pickle(f); return df

def sim(df, f, sig, fee_in, fee_out, stop_atr=2.0, trail_atr=3.0, hold=24*3, tp_atr=None):
    """sig: +1/-1/0 per bar (decided at close i, enter at open i+1). Exits: ATR stop, chandelier trail, time."""
    o,h,l,c,A,t = df.o.values, df.h.values, df.l.values, df.c.values, f.atr.values, df.t.values
    s = sig.values; out = []; i = 210; n = len(c)
    while i < n-1:
        d = s[i]
        if d == 0 or np.isnan(A[i]): i += 1; continue
        e = o[i+1]; a = A[i]; stop = e - d*stop_atr*a; best = e; j = i+1
        while True:
            if (d == 1 and l[j] <= stop) or (d == -1 and h[j] >= stop): x = stop if (d==1 and o[j]>stop) or (d==-1 and o[j]<stop) else o[j]; break
            if tp_atr and ((d==1 and h[j] >= e+tp_atr*a) or (d==-1 and l[j] <= e-tp_atr*a)): x = e + d*tp_atr*a; break
            best = max(best, h[j]) if d == 1 else min(best, l[j])
            stop = max(stop, best-trail_atr*a) if d == 1 else min(stop, best+trail_atr*a)
            if j-i >= hold or j == n-1: x = c[j]; break
            j += 1
        r = d*(x/e-1) - fee_in - fee_out; out.append((t[i+1], t[j], r, d)); i = j+1
    return out

def portfolio(tr, risk=0.15, maxpos=5):
    tr = sorted(tr); eq = 1.0; op = []; curve = [1.0]; g = []
    for et, xt, r, d in tr:
        op = [x for x in op if x > et]
        if len(op) >= maxpos: continue
        op.append(xt); p = eq*risk*r; eq += p; curve.append(eq); g.append(p)
    g = np.array(g); cv = np.array(curve); dd = (cv/np.maximum.accumulate(cv)-1).min()
    w, ls = g[g>0].sum(), -g[g<0].sum()
    return dict(trades=len(g), win=round(float((g>0).mean()),3) if len(g) else 0, net_pct=round((eq-1)*100,2),
                maxdd_pct=round(dd*100,2), pf=round(w/ls,2) if ls else None)

if __name__ == "__main__":
    days, N = int(sys.argv[1]) if len(sys.argv)>1 else 240, int(sys.argv[2]) if len(sys.argv)>2 else 30
    t24 = requests.get(H+"/api/v3/ticker/24hr", timeout=15).json()
    bad = {"USDC","FDUSD","TUSD","USD1","EUR","PAXG","U","XUSD","BFUSD","USDE"}
    syms = [x["symbol"] for x in sorted(t24, key=lambda x: -float(x["quoteVolume"])) if x["symbol"].endswith("USDT")
            and x["symbol"][:-4] not in bad and not (x["symbol"][:-4].endswith("B") and x["symbol"] not in ("BNBUSDT","ARBUSDT"))][:N]
    btc = fetch("BTCUSDT", days); D = {}
    for s in syms:
        try:
            df = fetch(s, days).merge(btc[["t","c"]].rename(columns={"c":"btc"}), on="t")
            if len(df) < days*20: continue
            f = F.build(df, df.btc); fut = df.c.shift(-HOLD)/df.c - 1
            f["y"] = np.where(fut.isna(), np.nan, (fut > 0.003).astype(float) - (fut < -0.003).astype(float)); D[s] = (df, f)
        except Exception as e: print("skip", s, e)
    print(f"pairs={len(D)} days={days}")
    # ---- walk-forward ML: train on all pairs' past 90d, predict next 15d, roll ----
    allt = np.sort(btc.t.values); step, train = 15*24*3600000, 90*24*3600000; t0 = allt[0]+210*3600000+train
    P = {s: pd.Series(np.nan, index=f.index) for s,(df,f) in D.items()}
    k = t0
    while k < allt[-1]:
        X, Y = [], []
        for s,(df,f) in D.items():
            m = (df.t >= k-train) & (df.t < k-HOLD*3600000) & f.y.notna() & (f.y != 0)
            X.append(f.loc[m, F.FEATS]); Y.append(f.loc[m, "y"])
        X, Y = pd.concat(X), pd.concat(Y)
        mdl = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05, l2_regularization=1.0, min_samples_leaf=200).fit(X, Y > 0)
        for s,(df,f) in D.items():
            m = (df.t >= k) & (df.t < k+step)
            if m.any(): P[s][m] = mdl.predict_proba(f.loc[m, F.FEATS])[:,1]
        k += step
    oos_start = t0
    from sklearn.metrics import roc_auc_score
    pp = pd.concat([P[s] for s in D]); yy = pd.concat([D[s][1].y for s in D]); m = pp.notna() & yy.notna() & (yy != 0)
    auc = roc_auc_score(yy[m] > 0, pp[m]); print("ML out-of-sample AUC (0.5 = coin flip):", round(auc, 4))
    FEES = {"taker 0.10%": (0.0010+0.0003, 0.0010+0.0003), "maker+BNB 0.075/0.075": (0.00075, 0.00075+0.0003)}
    res = {}
    for fname,(fi,fo) in FEES.items():
        for strat in ["trend_long","trend_longshort","ml_long","ml_longshort","ensemble_long","ensemble_longshort"]:
            for th in ([0.60, 0.65] if "trend" not in strat else [None]):
                tr = []
                for s,(df,f) in D.items():
                    p = P[s]; tsig = F.trend_signal(f)
                    if strat.startswith("trend"): sig = tsig
                    elif strat.startswith("ml"): sig = (p > th).astype(int) - (p < 1-th).astype(int)
                    else: sig = ((p > th-0.05) & (tsig == 1)).astype(int) - ((p < 1.05-th) & (tsig == -1)).astype(int)
                    if strat.endswith("_long"): sig = sig.clip(lower=0)
                    sig = sig.where(df.t >= oos_start, 0).fillna(0)
                    kw = dict(stop_atr=2.0, trail_atr=3.0, hold=72) if strat.startswith("trend") else dict(stop_atr=1.5, trail_atr=2.0, hold=HOLD*2, tp_atr=2.5)
                    tr += sim(df, f, sig, fi, fo, **kw)
                key = f"{strat}{'' if th is None else '@'+str(th)} | {fname}"; res[key] = portfolio(tr); print(key, res[key])
    json.dump({"oos_from": str(pd.to_datetime(oos_start, unit='ms')), "pairs": list(D), "results": res, "ml_auc": auc}, open("bt_results.json","w"), indent=1)
