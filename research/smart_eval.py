"""Forward validation of SHADOW smart-money flags: return from signal price to the price ~60 min later (same mint, later log rows)."""
import json, collections, statistics as st
R = [json.loads(l) for l in open("research/smart_shadow.jsonl")]
by = collections.defaultdict(list)
for r in R:
    if r.get("px"): by[r["mint"]].append(r)
res = collections.defaultdict(list)
for m, rows in by.items():
    rows.sort(key=lambda r: r["ts"])
    for i, r in enumerate(rows):
        fut = next((x for x in rows[i:] if 45*60 <= x["ts"]-r["ts"] <= 120*60), None)
        if not fut: continue
        ret = fut["px"]/r["px"]-1
        res["ALL"].append(ret)
        for f in r["flags"] or ["none"]: res[f].append(ret)
print("signals logged", len(R), "mints", len(by))
for k, v in sorted(res.items()): print(f"{k:12} n={len(v):4} mean_fwd_1h={st.mean(v)*100:+6.2f}% median={st.median(v)*100:+6.2f}% hit={sum(x>0 for x in v)/len(v)*100:4.0f}%")
print("VALIDATION RULE: a flag may affect trades only with n>=40 and mean beating 'none' by >2pp (entries) or avoiding >3pp drop (exits).")
