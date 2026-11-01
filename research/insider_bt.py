"""Walk-forward out-of-sample test of the insider convergence signal on mined launches.
For each test launch (chronological, after a warm-up), wallets are scored ONLY on launches that started >= GAP before it.
Feature = quality-weighted count of scored wallets among its first N_EARLY buyers (excluding slot-0/1 snipers).
Outcome = winner (peak mcap >= 300k, i.e. 10x+ from a pump launch) vs loser. Also: dev sold inside the first trades -> loser? (exit flag)."""
import json, sys, os, collections
sys.path.insert(0, "."); import insider as I
L = sorted([json.loads(l) for l in open(I.F_MINED)], key=lambda x: x["t0"] or 0)
GAP = 3600; WARM = max(20, len(L)//3); rows = []
for k in range(WARM, len(L)):
    x = L[k]; W = I.score(L[:k], None, cutoff_t=(x["t0"] or 0)-GAP)
    ws = {}; 
    for e in x["ev"]:
        if e.get("sell") or e["rank"] >= I.N_EARLY or e.get("dslot", 9) <= 1: continue
        if e["w"] in W: ws[e["w"]] = W[e["w"]]["tier"]
    conv = sum(I.TW[t] for t in ws.values()); elite = sum(t == "elite" for t in ws.values())
    dev_sold = any(e.get("sell") and e["w"] in (x["creator"], x.get("creator2")) for e in x["ev"])
    rows.append(dict(win=x["win"], conv=conv, elite=elite, n=len(ws), dev_sold=dev_sold, nW=len(W)))
def rate(rs): return (sum(r["win"] for r in rs)/len(rs), len(rs)) if rs else (None, 0)
base = rate(rows); out = dict(launches=len(L), test=len(rows), base_win=base)
for th in (1, 2, 3, 5, 8):
    out[f"conv>={th}"] = rate([r for r in rows if r["conv"] >= th])
out["conv=0"] = rate([r for r in rows if r["conv"] == 0]); out["elite>=1"] = rate([r for r in rows if r["elite"] >= 1])
out["dev_sold_early"] = rate([r for r in rows if r["dev_sold"]]); out["dev_held"] = rate([r for r in rows if not r["dev_sold"]])
out["wallets_last_train"] = rows[-1]["nW"] if rows else 0
# validation rule: conv>=3 needs n>=40 and winner-rate lift >= 1.5x base -> promote to paper
c = out["conv>=3"]; ok = bool(c[1] >= 40 and base[0] and c[0] >= 1.5*base[0]); out["convergence_validated"] = ok
d = out["dev_sold_early"]; out["exit_dev_validated"] = bool(d[1] >= 40 and base[0] is not None and d[0] <= 0.5*base[0])
json.dump(out, open("research/insider_bt.json", "w"), indent=1); print(json.dumps(out, indent=1))
if ok or out["exit_dev_validated"]:
    P = json.load(open(I.F_PROMO)) if os.path.exists(I.F_PROMO) else {}
    if ok: P["convergence"] = True; P["convergence_src"] = "walkforward"
    if out["exit_dev_validated"]: P["exit"] = True; P["exit_src"] = "walkforward_dev"
    json.dump(P, open(I.F_PROMO, "w"), indent=1)
