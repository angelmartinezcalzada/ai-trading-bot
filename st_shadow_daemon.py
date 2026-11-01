"""Shadow daemon: reads candidates_solana.jsonl (what live bot evaluated) and trades_solana_live.csv,
logs Solana Tracker shadow verdicts to data/st_shadow.jsonl, then fills forward prices (+1h,+6h,+24h)
into data/st_forward.jsonl. Never touches live state/orders."""
import json, time, os, csv, solanatracker as st
st.OWNER[0] = "daemon"
SEEN = {}
def live_bought():
    try: return {r.get("mint") or r.get("symbol") for r in csv.DictReader(open("trades_solana_live.csv"))}
    except Exception: return set()
def tail_candidates(n=300):
    try: lines = open("candidates_solana.jsonl").readlines()[-n:]
    except Exception: return []
    out = []
    for l in lines:
        try: out.append(json.loads(l))
        except Exception: pass
    return out
def forward():
    done = set()
    if os.path.exists("data/st_forward.jsonl"):
        for l in open("data/st_forward.jsonl"):
            try: d = json.loads(l); done.add((d["mint"], d["t0"], d["h"]))
            except Exception: pass
    if not os.path.exists(st.SHADOW_F): return
    for l in open(st.SHADOW_F):
        try: r = json.loads(l)
        except Exception: continue
        p0 = (r.get("f") or {}).get("price")
        if not p0: continue
        for h in (1, 6, 24):
            k = (r["mint"], r["t"], h); age = time.time() - r["t"]
            if k in done or age < h * 3600 or age > h * 3600 + 7200: continue
            p = st.get(f"/price?token={r['mint']}", "price")
            if p and p.get("price") is not None:
                with open("data/st_forward.jsonl", "a") as fh:
                    fh.write(json.dumps({"mint": r["mint"], "t0": r["t"], "h": h, "verdict": r["verdict"], "live": r["live"],
                                         "ret": round(float(p["price"]) / p0 - 1, 4)}) + "\n")
            done.add(k)
def loop():
    while not os.path.exists("STOP"):
        bought = live_bought()
        for c in tail_candidates():
            m = c.get("mint")
            # only coins with liquidity (live liq-fail spam is pointless); re-check at most every 30 min
            if not m or c.get("fail") == ["liq"] or time.time() - SEEN.get(m, 0) < 7200 or (c.get("score") or 0) < 35: continue
            SEEN[m] = time.time()
            live = {"pass": c.get("pass"), "fail": c.get("fail"), "src": c.get("src"), "bought": m in bought}
            st.shadow(m, live=live, sym=c.get("sym"))
        forward()
        time.sleep(60)
if __name__ == "__main__": loop()
