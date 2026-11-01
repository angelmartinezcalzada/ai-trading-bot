import json, csv, sys, collections; sys.path.insert(0, "."); import scam
cfg = json.load(open("config.json"))["exchanges"]["solana"]
mint = {}; price = {}
for l in open("candidates_solana.jsonl"):
    try: r = json.loads(l)
    except Exception: continue
    if r.get("pass"): mint[r["sym"]] = r["mint"]; price.setdefault(r["sym"], r.get("price"))
pnl = collections.defaultdict(float); rt = {}
for row in csv.DictReader(open("trades_solana_paper.csv")):
    if row["side"] == "SELL": pnl[row["symbol"]] += float(row["pnl"])
    else:
        import re; m = re.search(r" rt=([\d.]+)%", row["reason"]); rt[row["symbol"]] = float(m.group(1)) if m else None; price[row["symbol"]] = row["price"]
res = []; hit = collections.Counter(); hitL = collections.Counter(); hitW = collections.Counter()
for s, p in pnl.items():
    m = mint.get(s)
    if not m: continue
    f = scam.check(m, s, price.get(s), cfg, rt.get(s)); res.append((s, round(p, 2), f))
    for x in {re.sub(r"[\d.%/h]+$", "", y) for y in f}: hit[x] += 1; (hitL if p < 0 else hitW)[x] += 1
L = [r for r in res if r[1] < 0]; W = [r for r in res if r[1] >= 0]
print("trades", len(res), "losers", len(L), "winners", len(W))
for r in sorted(res, key=lambda r: r[1]): print(f"{r[0]:12} {r[1]:8.2f} {r[2]}")
print("\nflag: losers caught / winners blocked / loss avoided / profit forgone")
for k in hit: print(f"{k:20} {hitL[k]:3} / {hitW[k]:3}  {-sum(r[1] for r in L if any(y.startswith(k) for y in r[2])):8.2f} {sum(r[1] for r in W if any(y.startswith(k) for y in r[2])):8.2f}")
blk = [r for r in res if r[2]]
print("\nANY flag: loss avoided %.2f, profit forgone %.2f, net %.2f" % (-sum(r[1] for r in blk if r[1] < 0), sum(r[1] for r in blk if r[1] >= 0), -sum(r[1] for r in blk)))
