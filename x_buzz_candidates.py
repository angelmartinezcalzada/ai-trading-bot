#!/usr/bin/env python3
"""Prints up to N current candidates for the X-buzz routine as JSON: [{sym, mint, name, why}].
Picks open positions + coins from the last 30 min of scans that passed or only failed soft checks
(momentum / score / concentration / sellability-not-checked). Read-only."""
import json, sys, datetime as dt
SOFT = ("no_momentum", "no_momentum_m5", "top10", "no_sellability_check", "brain_ev<=0", "insider_negative", "price_impact", "slippage")
def soft(f): return all(x.startswith(SOFT) or x.startswith("score<") for x in f)
def main(n=15, mins=30):
    cut = (dt.datetime.now()-dt.timedelta(minutes=mins)).isoformat(timespec="seconds"); best = {}
    for l in open("candidates_solana.jsonl"):
        try: r = json.loads(l)
        except Exception: continue
        if r.get("ts", "") < cut or not r.get("mint"): continue
        f = r.get("fail") or []
        if not (r.get("pass") or (f and soft(f))): continue
        sc = (r.get("score") or 0) + (100 if r.get("pass") else 0)
        if sc >= best.get(r["mint"], {}).get("_k", -1): best[r["mint"]] = dict(sym=r.get("sym"), mint=r["mint"], name=r.get("name") or r.get("sym"), why="pass" if r.get("pass") else ",".join(f), _k=sc)
    out = []
    try:
        for m, p in (json.load(open("state_solana_live.json")).get("pos") or {}).items(): out.append(dict(sym=p.get("sym"), mint=m, name=p.get("sym"), why="open_position"))
    except Exception: pass
    for v in sorted(best.values(), key=lambda v: -v["_k"]):
        if len(out) >= n: break
        if v["mint"] not in {o["mint"] for o in out}: v.pop("_k"); out.append(v)
    print(json.dumps(out, ensure_ascii=False, indent=1))
if __name__ == "__main__": main(int(sys.argv[1]) if len(sys.argv) > 1 else 15)
