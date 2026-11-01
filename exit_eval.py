"""exit-intel validation: for each flagged holding (research/exit_intel.jsonl + flagged smart_shadow rows on held tokens) compare
the next ~1h return vs unflagged held snapshots. edge_pp = mean(unflagged) - mean(flagged) in percentage points (positive = flags avoid drops)."""
import json, os
def run():
    R = [json.loads(l) for l in open("research/smart_shadow.jsonl")] if os.path.exists("research/smart_shadow.jsonl") else []
    R = [r for r in R if r.get("held") and r.get("px")]
    by = {}
    for r in R: by.setdefault(r["mint"], []).append(r)
    fl, nf = [], []
    for rows in by.values():
        rows.sort(key=lambda r: r["ts"])
        for i, r in enumerate(rows):
            f = next((x for x in rows[i:] if 2700 <= x["ts"]-r["ts"] <= 7200), None)
            if not f: continue
            ret = f["px"]/r["px"]-1; bad = [x for x in r["flags"] if x in ("dev_selling", "early_exit", "whale_dump", "insider_sell")]
            (fl if bad else nf).append(ret)
    m = lambda v: sum(v)/len(v) if v else 0
    return dict(n_flag=len(fl), n_noflag=len(nf), mean_flag=round(m(fl), 4), mean_noflag=round(m(nf), 4), edge_pp=round((m(nf)-m(fl))*100, 2) if fl and nf else 0)
if __name__ == "__main__": print(run())
