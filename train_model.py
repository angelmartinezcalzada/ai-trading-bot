"""Optional: train the ML direction model (HistGradientBoosting) on recent 1h data -> model.pkl.
Walk-forward OOS AUC was ~0.50 (no edge), so ml_filter is OFF by default. Retrain + re-check before enabling."""
import pickle, numpy as np, pandas as pd, sys
from sklearn.ensemble import HistGradientBoostingClassifier
import features as F, backtest_wf as B
days = int(sys.argv[1]) if len(sys.argv) > 1 else 120
btc = B.fetch("BTCUSDT", days); X, Y = [], []
for s in ["ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","NEARUSDT","SUIUSDT","ADAUSDT","LINKUSDT","AVAXUSDT"]:
    df = B.fetch(s, days).merge(btc[["t","c"]].rename(columns={"c":"btc"}), on="t"); f = F.build(df, df.btc)
    fut = df.c.shift(-B.HOLD)/df.c-1; m = fut.notna() & (fut.abs() > 0.003) & f[F.FEATS].notna().all(axis=1)
    X.append(f.loc[m, F.FEATS]); Y.append(fut[m] > 0)
mdl = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05, l2_regularization=1.0, min_samples_leaf=200).fit(pd.concat(X), pd.concat(Y))
pickle.dump(mdl, open("model.pkl", "wb")); print("saved model.pkl")
