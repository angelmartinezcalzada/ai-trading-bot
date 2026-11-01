"""Backtest (5m bars) approximating bot.py's momentum strategy + regime filter. In-sample tune / out-of-sample test."""
import os, json, time, itertools, sys, numpy as np, pandas as pd, requests
from bot import ema, rsi, macd, atr
H = "https://data-api.binance.vision"; CACHE = "bt_data"; os.makedirs(CACHE, exist_ok=True)

def fetch(sym, days=60, tf="5m"):
    f = f"{CACHE}/{sym}_{tf}_{days}.pkl"
    if os.path.exists(f): return pd.read_pickle(f)
    end = int(time.time()*1000); start = end - days*86400000; rows = []
    while start < end:
        k = requests.get(H+"/api/v3/klines", params=dict(symbol=sym, interval=tf, startTime=start, limit=1000), timeout=15).json()
        if not k: break
        rows += k; start = k[-1][0] + 1
    df = pd.DataFrame(rows).iloc[:, :6].astype(float); df.columns = list("tohlcv"); df.to_pickle(f); return df

def features(df, btc):
    c = df.c; d = pd.DataFrame(index=df.index)
    d["atr"] = atr(df); _, _, h = macd(c); d["macd_up"] = (h > 0) & (h > h.shift())
    d["trend"] = (c > ema(c, 21)) & (ema(c, 21) > ema(c, 50))
    d["trend1h"] = c > ema(c, 12*21); d["trend4h"] = c > ema(c, 48*21)
    d["chg"] = (c / c.shift(1) - 1) * 100
    d["volr"] = df.v / df.v.shift(1).rolling(12).mean()
    d["brk"] = c > df.h.shift(1).rolling(6).max()
    tp = (df.h+df.l+df.c)/3; d["vwap"] = c > (tp*df.v).rolling(12*24).sum()/df.v.rolling(12*24).sum()
    d["rsi"] = rsi(c); d["rs"] = (c/c.shift(48)) / (btc/btc.shift(48)) - 1
    bc = btc; e50, e200 = ema(bc, 12*50), ema(bc, 12*200); sl = ema(bc, 48*20) / ema(bc, 48*20).shift(48*5) - 1
    d["bear"] = (bc < e50) & (e50 < e200) & (sl < -0.003)
    return d

def simulate(df, d, p, fee=0.001, slip=0.0005):
    sig = ((d.chg >= p["chg"]) & (d.volr >= p["vol"]) & d.macd_up & d.trend & d.vwap & d.brk & (d.rsi < 78)
           & ((d.trend1h.astype(int) + d.trend4h.astype(int)) >= 1) & (d.rs > 0) & ~d.bear).values
    o, h, l, c, a, t = df.o.values, df.h.values, df.l.values, df.c.values, d.atr.values, df.t.values
    trades = []; i = 300; n = len(c)
    while i < n - 1:
        if not sig[i]: i += 1; continue
        e = o[i+1] * (1+slip); A = a[i]; stop = e - p["stop"]*A; tp = e + p["tp"]*A; hi = e; j = i + 1
        while True:
            if l[j] <= stop: x = min(stop, o[j]); why = "stop"; break       # conservative: stop first
            if h[j] >= tp: x = max(tp, o[j]); why = "tp"; break
            hi = max(hi, h[j])
            if hi - e >= p["trail_on"]*A: stop = max(stop, hi - p["trail"]*A)
            if j - i >= p["hold"] or j == n-1: x = c[j]; why = "time"; break
            j += 1
        x *= (1-slip); trades.append((t[i+1], t[j], x/e*(1-fee)**2 - 1, why)); i = j + p["cool"]
    return trades

def portfolio(trades, risk=0.10, maxpos=3, eq0=1000):
    trades = sorted(trades); eq = eq0; open_ = []; curve = [eq]; taken = []
    for et, xt, r, _ in trades:
        open_ = [o for o in open_ if o > et]
        if len(open_) >= maxpos: continue
        open_.append(xt); pnl = eq*risk*r; eq += pnl; curve.append(eq); taken.append(pnl)
    curve = np.array(curve); dd = (curve/np.maximum.accumulate(curve) - 1).min()
    g = np.array(taken); w = g[g > 0].sum(); ls = -g[g < 0].sum()
    return dict(trades=len(g), win=round(float((g > 0).mean()) if len(g) else 0, 3), net_pct=round((eq/eq0-1)*100, 2),
                maxdd_pct=round(dd*100, 2), pf=round(w/ls, 2) if ls else None)

if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 60; N = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    t24 = requests.get(H+"/api/v3/ticker/24hr", timeout=15).json()
    excl = ("USDC","FDUSD","TUSD","USD1","EUR","PAXG","U","XUSD","BFUSD")
    syms = [x["symbol"] for x in sorted(t24, key=lambda x: -float(x["quoteVolume"])) if x["symbol"].endswith("USDT")
            and x["symbol"][:-4] not in excl and not (x["symbol"][:-4].endswith("B") and len(x["symbol"]) > 7 and x["symbol"] != "BNBUSDT")][:N]
    btc = fetch("BTCUSDT", days)
    data = {}
    for s in syms:
        try: df = fetch(s, days); df = df.merge(btc[["t","c"]].rename(columns={"c":"btc"}), on="t"); data[s] = (df, features(df, df.btc))
        except Exception as e: print("skip", s, e)
    split = btc.t.iloc[int(len(btc)*2/3)]
    base = dict(chg=0.6, vol=2.0, stop=1.5, tp=2.5, trail_on=1.0, trail=0.8, hold=9, cool=3)
    grid = dict(chg=[0.4, 0.6, 1.0], vol=[2.0, 3.0], stop=[1.5, 2.5], tp=[2.0, 3.0, 4.0], trail=[0.8, 1.5])
    def run(p, part):
        tr = []
        for s, (df, d) in data.items():
            tr += [x for x in simulate(df, d, p) if (x[0] < split) == (part == "is")]
        return portfolio(tr)
    print(f"pairs={len(data)} days={days} split(IS 2/3 | OOS 1/3) at", pd.to_datetime(split, unit="ms"))
    print("BASELINE IS ", run(base, "is")); print("BASELINE OOS", run(base, "oos"))
    res = []
    for vals in itertools.product(*grid.values()):
        p = {**base, **dict(zip(grid, vals))}; r = run(p, "is")
        if r["trades"] >= 30: res.append((r["net_pct"] / (1 + abs(r["maxdd_pct"])), p, r))
    res.sort(key=lambda x: -x[0])
    print("TOP-5 IN-SAMPLE (score=net/(1+|DD|)) and their OOS:")
    for sc, p, r in res[:5]: print({k: p[k] for k in grid}, "IS", r, "OOS", run(p, "oos"))
    json.dump({"best": res[0][1] if res else base}, open("bt_best.json", "w"), indent=1)
