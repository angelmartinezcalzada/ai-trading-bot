"""Does Coinversa cohort positioning (Apex / Sharps / Crowd net bias) predict forward returns?
Inputs (research/data/coinversa_2026-10/): hourly candles from live_coin_risk_history and cohort-bias history for 3 tiers,
BTC / SOL / FARTCOIN, 2026-10-01 .. 2026-10-31 (30 days). Run: python3 research/coinversa_study.py
Caveat: 30 days of overlapping 1h/4h/24h returns give few independent observations (the 24h horizon has ~30); per-coin 24h
correlations reach |0.3| with OPPOSITE signs across coins, so the pooled ~0 is 'no consistent signal', not 'exactly zero'."""
import os, sys, json
import numpy as np, pandas as pd
T = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "coinversa_2026-10") + os.sep
CANDLES = {"BTC": "risk_history_BTC.txt", "SOL": "risk_history_SOL.txt", "FARTCOIN": "risk_history_FARTCOIN.txt"}
BIAS = ["cohort_bias_BTC.txt", "cohort_bias_SOL.txt", "cohort_bias_FARTCOIN.txt"]
def section(path, name):
    rows, on = [], False
    for ln in open(path):
        if ln.startswith(name + "["): on = True; continue
        if on:
            if not ln.startswith("  "): break
            rows.append([x.strip().strip('"') for x in ln.strip().split(",")])
    return rows
out = {}
for coin, f in CANDLES.items():
    c = pd.DataFrame(section(T + f, "candleHistory"), columns=["ts", "o", "h", "l", "c", "v"]).astype(float)
    c["t"] = pd.to_datetime(c.ts, unit="ms").dt.ceil("h")   # close time -> hour label
    c = c.set_index("t")[["c"]].sort_index()
    out[coin] = c
bias = []
for f in BIAS:
    rows = section(T + f, "rows")
    b = pd.DataFrame(rows, columns=["ts", "coin", "tierType", "tier", "long", "short", "netBias", "n"])
    b["t"] = pd.to_datetime(b.ts.astype(float), unit="ms"); b["netBias"] = b.netBias.astype(float)
    bias.append(b[["t", "coin", "tier", "netBias"]])
bias = pd.concat(bias)
TIER = {"money_printer": "apex", "smart_money": "sharps", "exit_liquidity": "crowd"}
res = []
for coin, c in out.items():
    b = bias[bias.coin == coin].pivot_table(index="t", columns="tier", values="netBias").rename(columns=TIER)
    d = c.join(b, how="inner").sort_index()
    # entry at the first close at/after the snapshot hour (the bar that closes T+1h) -> shift close by -1
    px = d.c.shift(-1)
    for k in (1, 4, 24):
        d[f"fwd{k}"] = np.log(px.shift(-k) / px)
    for tier in ("apex", "sharps", "crowd"):
        d[f"{tier}_d24"] = d[tier] - d[tier].shift(24)
        for feat in (tier, f"{tier}_d24"):
            for k in (1, 4, 24):
                x, y = d[feat], d[f"fwd{k}"]; m = x.notna() & y.notna()
                if m.sum() < 50: continue
                r = np.corrcoef(x[m], y[m])[0, 1]
                q = pd.qcut(x[m], 3, labels=["low", "mid", "high"], duplicates="drop")
                g = y[m].groupby(q, observed=True).mean() * 100
                res.append({"coin": coin, "feature": feat, "h": k, "n": int(m.sum()), "corr": round(r, 3),
                            "ret_low_%": round(g.get("low", np.nan), 3), "ret_high_%": round(g.get("high", np.nan), 3),
                            "spread_%": round(g.get("high", np.nan) - g.get("low", np.nan), 3)})
R = pd.DataFrame(res)
pd.set_option("display.width", 200); pd.set_option("display.max_rows", 200)
print("Window:", min(c.index.min() for c in out.values()), "->", max(c.index.max() for c in out.values()))
print(R.to_string(index=False))
print("\n=== pooled mean corr by feature/horizon (3 coins) ===")
P = R.assign(f=R.feature.str.replace(r"^(apex|sharps|crowd)", r"\1", regex=True)).groupby(["feature", "h"]).agg(n=("n", "sum"), corr_mean=("corr", "mean"), spread_mean=("spread_%", "mean")).round(3)
print(P.to_string())
# sign consistency across coins
S = R.groupby(["feature", "h"]).apply(lambda g: int((np.sign(g["corr"]) == np.sign(g["corr"].mean())).sum()), include_groups=False).rename("same_sign_coins")
print("\n=== sign consistency (of 3 coins) ==="); print(S.to_string())
print("\n=== per-coin max |corr| and independent observations (n / horizon) ===")
for (coin, h), g in R.groupby(["coin", "h"]): print(f"{coin:9s} h={h:<3d} max|corr|={g['corr'].abs().max():.2f}  n_eff~{int(g['n'].max()//h)}")
json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "coinversa_study.json"), "w"), indent=1)
