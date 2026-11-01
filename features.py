"""Shared 1h feature engineering for trend strategy + ML direction model (used by live bot AND walk-forward backtest)."""
import numpy as np, pandas as pd
def ema(x, n): return x.ewm(span=n, adjust=False).mean()
def rsi(c, n=14):
    d = c.diff(); u = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean(); v = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + u/v.replace(0, np.nan))
def atr(df, n=14):
    pc = df.c.shift(); tr = pd.concat([df.h-df.l, (df.h-pc).abs(), (df.l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()
def adx(df, n=14):
    up, dn = df.h.diff(), -df.l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0); mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(df, n); pdi = 100*pd.Series(pdm, df.index).ewm(alpha=1/n, adjust=False).mean()/a; mdi = 100*pd.Series(mdm, df.index).ewm(alpha=1/n, adjust=False).mean()/a
    return (100*(pdi-mdi).abs()/(pdi+mdi)).ewm(alpha=1/n, adjust=False).mean(), pdi, mdi

FEATS = ["r1","r3","r6","r12","r24","r72","rsi","macdh","atrp","volr","d20","d50","d200","adx","dmi","don","tbr","tbr6",
         "btc_r6","btc_r24","btc_d200","rs24","hour","dow"]
def build(df, btc=None):
    """df: t,o,h,l,c,v,(tb taker-buy base vol). btc: same-index BTC close series."""
    c = df.c; f = pd.DataFrame(index=df.index)
    for k in (1,3,6,12,24,72): f[f"r{k}"] = c.pct_change(k)
    f["rsi"] = rsi(c); m = ema(c,12)-ema(c,26); f["macdh"] = (m-ema(m,9))/c
    A = atr(df); f["atrp"] = A/c; f["volr"] = df.v/df.v.rolling(48).mean()
    for n in (20,50,200): f[f"d{n}"] = c/ema(c,n)-1
    ad, p, mi = adx(df); f["adx"] = ad; f["dmi"] = (p-mi)/100
    hi, lo = df.h.rolling(20).max(), df.l.rolling(20).min(); f["don"] = (c-lo)/(hi-lo)
    tb = df["tb"] if "tb" in df else df.v*0.5
    f["tbr"] = tb/df.v.replace(0,np.nan); f["tbr6"] = tb.rolling(6).sum()/df.v.rolling(6).sum()   # order-flow: taker-buy ratio
    b = btc if btc is not None else c
    f["btc_r6"] = b.pct_change(6); f["btc_r24"] = b.pct_change(24); f["btc_d200"] = b/ema(b,200)-1
    f["rs24"] = c.pct_change(24) - b.pct_change(24)
    ts = pd.to_datetime(df.t, unit="ms"); f["hour"] = ts.dt.hour.values; f["dow"] = ts.dt.dayofweek.values
    f["atr"] = A; f["ema20"], f["ema50"], f["ema200"] = ema(c,20), ema(c,50), ema(c,200)
    f["don_hi"], f["don_lo"] = hi.shift(1), lo.shift(1)
    return f

def trend_signal(f, adx_min=22):
    """+1 long / -1 short / 0. Trend-following: EMA stack + ADX + Donchian-20 breakout."""
    up = (f.ema20 > f.ema50) & (f.ema50 > f.ema200) & (f.adx > adx_min) & (f.r1 > 0) & (f.don >= 0.999)
    dn = (f.ema20 < f.ema50) & (f.ema50 < f.ema200) & (f.adx > adx_min) & (f.r1 < 0) & (f.don <= 0.001)
    return up.astype(int) - dn.astype(int)
