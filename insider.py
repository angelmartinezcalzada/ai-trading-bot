"""INSIDER / smart-money engine (Solana, public on-chain data only).
mine():   early buyers (first N swaps) of launches via public Solana RPC (getSignaturesForAddress on the mint + getTransaction)
label:    winner = peak mcap >= WIN_MC (>=10x+ from launch), loser = peak < LOSE_MC
score():  per wallet: hits/misses on winners/losers, bayes hit-rate, earliness, consistency (distinct days), PnL/win-rate/hold from
          GeckoTerminal trades (smart_money), bot/MEV/sniper filter, dev exclusion, funding-source clusters -> tiers elite/good/watch
live():   polls elite+good wallets' new swaps (RPC, ~60s), convergence = quality-weighted distinct wallets buying the same mint in WIN_CONV
exit intel for held tokens is in memebot via exit_intel()."""
import json, time, os, collections, requests, logging, datetime as dt, math, threading, sys
log = logging.getLogger("insider")
RPC = os.environ.get("SOL_RPC", "https://api.mainnet-beta.solana.com")
F_MINED = "research/insider_mined.jsonl"; F_W = "insider_wallets.json"; F_LIVE = "research/insider_live.jsonl"; F_ST = "insider_status.json"
F_PROMO = "insider_promoted.json"; F_CEX = "cex_labels.json"
WIN_MC, LOSE_MC, N_EARLY, MAX_PAGES = 300_000, 30_000, 100, 20
WSOL = "So11111111111111111111111111111111111111112"; TW = {"elite": 3, "good": 2, "watch": 1}
_lk = threading.Lock(); _last = [0.0]
def rpc(m, p, gap=0.13):
    for i in range(6):
        with _lk:
            d = time.time()-_last[0]
            if d < gap: time.sleep(gap-d)
            _last[0] = time.time()
        try:
            r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=25)
            if r.status_code == 429: time.sleep(2*(i+1)); continue
            j = r.json()
            if "error" in j:
                if j["error"].get("code") in (-32429, 429, -32005): time.sleep(2*(i+1)); continue
                return None
            return j.get("result")
        except Exception: time.sleep(1+i)
    return None
def oldest_sigs(addr, n=N_EARLY+20, max_pages=MAX_PAGES):
    before, pages = None, []
    for _ in range(max_pages):
        p = {"limit": 1000}
        if before: p["before"] = before
        s = rpc("getSignaturesForAddress", [addr, p])
        if s is None: return None
        if not s: break
        pages.append(s); before = s[-1]["signature"]
        if len(s) < 1000: break
    else: return None                                    # too many txs: launch not reachable cheaply
    allsig = [x for pg in pages for x in pg][::-1]       # oldest first
    return [x for x in allsig if not x.get("err")][:n]
def parse_swap(sig, mint=None, owner=None):
    """returns list of (signer, mint, token_delta, sol_delta, slot, ts) for the tx signer (owner if given)"""
    tx = rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])   # same commitment as the signature feed
    if not tx: return None                                                     # not fetchable yet (RPC error / not propagated): caller retries, never skips
    if not tx.get("meta") or tx["meta"].get("err"): return []
    keys = tx["transaction"]["message"]["accountKeys"]; signer = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]
    who = owner or signer; m = tx["meta"]; out = {}
    for b in m.get("preTokenBalances") or []:
        if b.get("owner") == who and (mint is None or b["mint"] == mint): out[b["mint"]] = out.get(b["mint"], 0)-float(b["uiTokenAmount"]["uiAmount"] or 0)
    for b in m.get("postTokenBalances") or []:
        if b.get("owner") == who and (mint is None or b["mint"] == mint): out[b["mint"]] = out.get(b["mint"], 0)+float(b["uiTokenAmount"]["uiAmount"] or 0)
    idx = next((i for i, k in enumerate(keys) if (k["pubkey"] if isinstance(k, dict) else k) == who), None)
    sol = (m["postBalances"][idx]-m["preBalances"][idx])/1e9 if idx is not None else 0
    wsol = out.pop(WSOL, 0); sol += wsol
    return [dict(w=who, signer=signer, mint=k, dq=v, dsol=sol, slot=tx["slot"], ts=tx.get("blockTime")) for k, v in out.items() if abs(v) > 0 and k not in ("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY2W8kiGNYCHDsK")]
def pending_swaps(sigs, done, parse, keep=64):
    """Fail-closed cursor for one wallet. `sigs` newest-first from getSignaturesForAddress, `done` the handled signatures (mutated).
    Yields the parsed events of every not-yet-handled signature, oldest first; a signature is marked handled only once its tx was
    fetched (parse -> list) so an RPC miss (parse -> None) is re-tried next cycle instead of being skipped by a cursor that ran ahead."""
    out = []
    for x in reversed(sigs):
        if x["signature"] in done: continue
        if x.get("err"): done.append(x["signature"]); continue
        ev = parse(x["signature"])
        if ev is None: continue
        done.append(x["signature"]); del done[:-keep]; out.extend(ev)
    return out
def mine_launch(mint):
    sigs = oldest_sigs(mint)
    if not sigs: return None
    t0, s0 = sigs[0].get("blockTime"), sigs[0]["slot"]; creator = None; buyers = []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex: P = list(ex.map(lambda s: parse_swap(s["signature"], mint) or [], sigs))
    for i, es in enumerate(P):
        for e in es:
            if i == 0 and creator is None: creator = e["signer"]
            if e["dq"] > 0 and e["dsol"] < 0: buyers.append(dict(w=e["w"], rank=len(buyers), dt=(e["ts"] or t0)-t0, dslot=e["slot"]-s0, sol=-e["dsol"], q=e["dq"]))
            elif e["dq"] < 0: buyers.append(dict(w=e["w"], sell=True, dt=(e["ts"] or t0)-t0, sol=e["dsol"], q=e["dq"]))
    return dict(mint=mint, t0=t0, creator=creator, ev=buyers)
# ---------- universe of launches with outcome labels ----------
def dex_batch(mints):
    out = {}
    for i in range(0, len(mints), 30):
        try:
            r = requests.get("https://api.dexscreener.com/tokens/v1/solana/"+",".join(mints[i:i+30]), timeout=20).json()
            for p in r:
                m = p["baseToken"]["address"]; mc = p.get("marketCap") or p.get("fdv") or 0
                if mc > out.get(m, {}).get("mc", -1): out[m] = dict(mc=mc, liq=(p.get("liquidity") or {}).get("usd", 0), created=(p.get("pairCreatedAt") or 0)/1000, sym=p["baseToken"]["symbol"])
        except Exception: pass
        time.sleep(0.3)
    return out
def universe():
    seen = collections.defaultdict(lambda: dict(peak=0, sym=None, creator=None, first=None))
    for l in open("candidates_solana.jsonl"):
        try: r = json.loads(l)
        except Exception: continue
        d = seen[r["mint"]]; d["peak"] = max(d["peak"], r.get("mcap") or 0); d["sym"] = r.get("sym"); d["creator"] = d["creator"] or (r.get("rug") or {}).get("creator"); d["first"] = d["first"] or r["ts"]
    gk = []
    for path in ["trending_pools?duration=24h&page=%d", "trending_pools?duration=6h&page=%d", "pools?sort=h24_volume_usd_desc&page=%d", "new_pools?page=%d"]:
        for pg in range(1, 6):
            try:
                j = requests.get("https://api.geckoterminal.com/api/v2/networks/solana/"+path % pg, headers={"Accept": "application/json"}, timeout=15).json()
                for p in j.get("data", []):
                    m = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]; a = p["attributes"]
                    d = seen[m]; d["peak"] = max(d["peak"], float(a.get("fdv_usd") or 0)); d["sym"] = d["sym"] or a["name"].split(" /")[0]
            except Exception: pass
            time.sleep(2.2)
    ds = dex_batch(list(seen))
    for m, v in ds.items(): seen[m]["peak"] = max(seen[m]["peak"], v["mc"]); seen[m]["created"] = v["created"]
    return seen
def mine(limit_win=80, limit_lose=80, budget_s=3*3600):
    os.makedirs("research", exist_ok=True)
    done = {json.loads(l)["mint"] for l in open(F_MINED)} if os.path.exists(F_MINED) else set()
    U = universe(); W = [m for m, v in U.items() if v["peak"] >= WIN_MC and m not in done]; L = [m for m, v in U.items() if 0 < v["peak"] < LOSE_MC and m not in done]
    import random; random.seed(1); random.shuffle(L)
    W.sort(key=lambda m: -(U[m].get("created") or 0))          # youngest winners first (fewer txs -> launch reachable)
    W = [m for m in W if time.time()-(U[m].get("created") or 0) < 10*86400]
    log.warning("[insider] universe %d tokens: %d winners, %d losers to mine", len(U), len(W), len(L))
    t = time.time(); q = [(m, 1) for m in W[:limit_win]]; q2 = [(m, 0) for m in L[:limit_lose]]
    order = [x for pair in zip(q, q2) for x in pair] + q[len(q2):] + q2[len(q):]
    ok = 0
    for m, lab in order:
        if time.time()-t > budget_s: break
        try: r = mine_launch(m)
        except Exception as e: log.warning("mine %s %s", m, e); r = None
        if not r or not r["ev"]: continue
        r.update(win=lab, peak=U[m]["peak"], sym=U[m]["sym"], creator2=U[m]["creator"])
        open(F_MINED, "a").write(json.dumps(r)+"\n"); ok += 1
        if ok % 10 == 0: log.warning("[insider] mined %d launches (%.0f min)", ok, (time.time()-t)/60)
    return ok
# ---------- scoring ----------
def score(launches, gk_smart=None, cutoff_t=None):
    """launches: mined dicts (optionally only those with t0 < cutoff_t for walk-forward)"""
    L = [x for x in launches if cutoff_t is None or (x["t0"] or 0) < cutoff_t]
    devs = {x["creator"] for x in L} | {x.get("creator2") for x in L}
    A = collections.defaultdict(lambda: dict(h=0, m=0, ranks=[], days=set(), snipe=0, n=0, sells_early=0, sol=0.))
    for x in L:
        seen = set()
        for e in x["ev"]:
            if e.get("sell"):
                if e["w"] in A: A[e["w"]]["sells_early"] += 1
                continue
            if e["w"] in seen or e["rank"] >= N_EARLY: continue
            seen.add(e["w"]); a = A[e["w"]]; a["n"] += 1; a["ranks"].append(e["rank"]); a["sol"] += e["sol"]
            a["days"].add(dt.datetime.fromtimestamp(x["t0"] or 0, dt.timezone.utc).date().isoformat())
            if e.get("dslot", 9) <= 1: a["snipe"] += 1
            if x["win"]: a["h"] += 1
            else: a["m"] += 1
    nL = max(1, len(L)); out = {}
    for w, a in A.items():
        bot = (a["n"] >= 6 and a["n"]/nL > 0.5) or (a["snipe"] >= max(2, 0.6*a["n"])) or (a["sells_early"] > 3*a["n"])
        if w in devs or bot or a["n"] < 2: continue
        hr = (a["h"]+1)/(a["h"]+a["m"]+2); early = 1-sum(a["ranks"])/len(a["ranks"])/N_EARLY
        cons = len(a["days"]); sc = (hr-0.5)*math.log1p(a["h"])*(0.5+early)*(1+0.2*min(cons-1, 4))
        out[w] = dict(h=a["h"], m=a["m"], hr=round(hr, 3), early=round(early, 2), days=cons, sc=round(sc, 3), snipe=a["snipe"])
    for w, g in (gk_smart or {}).items():          # GeckoTerminal realized-PnL / win-rate profile (smart_money)
        o = out.setdefault(w, dict(h=0, m=0, hr=0.5, early=0, days=1, sc=0, snipe=0)); o.update(pnl=g["pnl"], wr=g["wr"], ntok=g["n"]); o["sc"] = round(o["sc"]+0.3*(g["wr"]-0.5)*math.log1p(g["n"]), 3)
    for w, o in out.items():
        o["tier"] = "elite" if (o["h"] >= 3 and o["hr"] >= 0.6) or (o["h"] >= 2 and o["hr"] >= 0.7 and o.get("wr", 0) >= 0.6) else \
                    "good" if (o["h"] >= 2 and o["hr"] >= 0.55) or (o.get("wr", 0) >= 0.6 and o.get("ntok", 0) >= 3) else "watch" if o["sc"] > 0 else None
    return {w: o for w, o in out.items() if o["tier"]}
def funding_source(w):
    s = oldest_sigs(w, n=3, max_pages=3)
    if not s: return None
    for x in s:
        tx = rpc("getTransaction", [x["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])
        for ins in ((tx or {}).get("transaction", {}).get("message", {}).get("instructions") or []):
            inf = (ins.get("parsed") or {}).get("info", {}) if isinstance(ins.get("parsed"), dict) else {}
            if inf.get("destination") == w and inf.get("source"): return inf["source"]
    return None
def cluster(W, max_n=150):
    """same funding source -> one cluster; cluster containing a dev or >5 members (farm) is excluded"""
    top = sorted(W, key=lambda w: -W[w]["sc"])[:max_n]; src = {}
    for w in top: src[w] = funding_source(w)
    try: cex = set(json.load(open(F_CEX)))
    except Exception: cex = set()
    C = collections.defaultdict(list)
    for w, s in src.items():
        if s and s not in cex: C[s].append(w)
    for s, ws in C.items():
        for w in ws: W[w]["cluster"] = s[:8]; W[w]["cluster_n"] = len(ws)
        if len(ws) > 5:
            for w in ws: W[w]["tier"] = None; W[w]["excluded"] = "farm_cluster"
    return {w: o for w, o in W.items() if o.get("tier")}
def build(do_cluster=True):
    import smart_money as sm
    L = [json.loads(l) for l in open(F_MINED)]
    W = score(L, sm.load())
    if do_cluster: W = cluster(W)
    tiers = collections.Counter(o["tier"] for o in W.values())
    json.dump(dict(t=time.time(), launches=len(L), wallets=W, tiers=tiers), open(F_W, "w"))
    log.warning("[insider] wallets %d %s from %d launches", len(W), dict(tiers), len(L)); return W
def load():
    try: return json.load(open(F_W))["wallets"]
    except Exception: return {}
# ---------- live tracking ----------
F_WL = "insider_wallet_live.json"; F_TOKV = "research/insider_tok_signals.jsonl"
def _gk(path, **p):
    """GeckoTerminal free tier: own spacing (>=2.5s) so the insider never starves memebot's 30/min budget"""
    w = 2.5-(time.time()-_gk.t)
    if w > 0: time.sleep(w)
    _gk.t = time.time()
    try:
        r = requests.get("https://api.geckoterminal.com/api/v2/networks/solana/"+path, params=p or None, timeout=15, headers={"Accept": "application/json"})
        return r.json() if r.status_code == 200 else {}
    except Exception: return {}
_gk.t = 0
BASE_W = 0.7   # owner order 2026-10-30: insider is TOP priority, active immediately at a high fixed weight
def tok_weight(min_n=20):
    """fixed starting weight BASE_W (owner order). Rolling out-of-sample check on every |score|>=3 snapshot (1h forward return):
    weight is cut only when, with n>=20, the directional edge is clearly negative (mean < -1% and hit < 45%) -> 0.2; mildly negative -> 0.45."""
    try: L = [json.loads(l) for l in open(F_TOKV)][-2000:]
    except Exception: L = []
    R = [x for x in L if x.get("kind") == "outcome" and x.get("fwd1h") is not None][-200:]
    if not R: return dict(n=0, hit=None, edge=None, weight=BASE_W, why="fixed start (owner)")
    dirn = [(1 if x["score"] > 0 else -1)*x["fwd1h"] for x in R]
    hit = sum(d > 0 for d in dirn)/len(dirn); edge = sum(dirn)/len(dirn); w, why = BASE_W, "fixed start (owner)"
    if len(R) >= min_n and edge < -0.01 and hit < 0.45: w, why = 0.2, "AUTO-REDUCED: validated edge clearly negative"
    elif len(R) >= min_n and edge < 0 and hit < 0.5: w, why = 0.45, "reduced: validated edge mildly negative"
    if w < BASE_W and getattr(tok_weight, "_last", None) != w: log.warning("[insider] WEIGHT %s -> %.2f (n=%d hit=%.2f edge=%.3f)", why, w, len(R), hit, edge)
    tok_weight._last = w
    return dict(n=len(R), hit=round(hit, 3), edge=round(edge, 4), weight=w, why=why)
def live(conv_win=1800, poll=8, max_wallets=120):
    """v3 real-time: elite wallets polled every cycle (~15-25s), good every 2nd; live per-wallet re-ranking from 1h forward outcomes of
    their buys; per-token score = cluster buys + elite + smart sells + whale net flow + dev sells + early-buyer exits + new-pool/liquidity;
    every |score|>=3 snapshot is validated forward (tok_weight) and that weight is what memebot applies."""
    import smart_money as sm
    st = dict(done={}, buys=[], sells=[], alerts=[], feed=[], tok={}, snaps=[], wbuys=[], pools={}); W = {}; wt = 0; cyc = 0; gkt = 0; npt = 0
    try: WL = json.load(open(F_WL))
    except Exception: WL = {}
    def feed(kind, **k):
        e = dict(t=time.time(), kind=kind, **k); st["feed"] = (st["feed"]+[e])[-150:]
        open(F_LIVE, "a").write(json.dumps(e)+"\n")
    while True:
        try:
            cyc += 1; now = t0 = time.time()
            if now-wt > 900: W = load(); wt = now
            def rank(w):
                o = W[w]; l = WL.get(w) or {}; n = l.get("n", 0)
                return o["sc"] + (0.6*((l.get("h", 0)+1)/(n+2)-0.5)*math.log1p(n) if n else 0)
            ranked = sorted([w for w, o in W.items() if o.get("tier") in ("elite", "good")], key=lambda w: -rank(w))[:max_wallets]
            track = [w for w in ranked if W[w]["tier"] == "elite" or cyc % 2 == 0]
            for w in track:
                s = rpc("getSignaturesForAddress", [w, {"limit": 8, "commitment": "confirmed"}], gap=0.12) or []   # confirmed instead of finalized: ~12 s less detection lag
                done = st["done"].get(w)
                if done is None:                                               # first sight of a wallet: adopt its history without replaying it
                    st["done"][w] = [x["signature"] for x in s]; continue
                for e in pending_swaps(s, done, lambda sig: parse_swap(sig, owner=w)):
                        ev = dict(t=e["ts"] or time.time(), w=w, tier=W[w]["tier"], mint=e["mint"], usd_sol=round(abs(e["dsol"]), 3), lag_s=round(time.time()-(e["ts"] or time.time())))
                        if e["dq"] > 0 and e["dsol"] < 0: st["buys"].append(ev); k = "buy"; st["wbuys"].append(dict(ev, px=_px(e["mint"])))
                        elif e["dq"] < 0 and e["dsol"] > 0: st["sells"].append(ev); k = "sell"
                        else: continue
                        feed("smart_"+k, w=w, tier=ev["tier"], mint=e["mint"], sol=ev["usd_sol"], lag_s=ev["lag_s"])
            now = time.time(); st["buys"] = [b for b in st["buys"] if now-b["t"] < 6*3600]; st["sells"] = [b for b in st["sells"] if now-b["t"] < 6*3600]
            # live wallet re-rank: 1h forward of each smart buy
            keep = []
            for b in st["wbuys"]:
                if now-b["t"] < 3600: keep.append(b); continue
                p1 = _px(b["mint"]) if b.get("px") else None
                if p1:
                    l = WL.setdefault(b["w"], dict(n=0, h=0, sum=0.0)); r = p1/b["px"]-1; l["n"] += 1; l["h"] += r > 0; l["sum"] = round(l["sum"]+r, 4)
            st["wbuys"] = keep[-500:]; json.dump(WL, open(F_WL, "w"))
            by = collections.defaultdict(dict)
            for b in st["buys"]:
                if now-b["t"] <= conv_win: by[b["mint"]][b["w"]] = b["tier"]
            conv = {m: dict(score=sum(TW[t] for t in ws.values()), n=len(ws), elite=sum(t == "elite" for t in ws.values())) for m, ws in by.items()}
            sbm = {m: sum(TW[s["tier"]] for s in st["sells"] if s["mint"] == m and now-s["t"] < conv_win) for m in {s["mint"] for s in st["sells"]}}
            for m, c in conv.items():
                if c["n"] >= 2 and not any(a["mint"] == m and now-a["t"] < conv_win for a in st["alerts"]):
                    a = dict(t=now, mint=m, px=_px(m), **c); st["alerts"].append(a); feed("cluster_buy", mint=m, **c)
                    log.warning("[insider] CLUSTER BUY %s score=%d wallets=%d elite=%d", m, c["score"], c["n"], c["elite"])
            for a in st["alerts"]:
                if a.get("px") and "fwd1h" not in a and now-a["t"] >= 3600:
                    p1 = _px(a["mint"]); a["fwd1h"] = round(p1/a["px"]-1, 4) if p1 else None
                    open(F_LIVE, "a").write(json.dumps(dict(kind="outcome", mint=a["mint"], t=a["t"], fwd1h=a["fwd1h"], score=a["score"]))+"\n")
            # new pools + liquidity events (GeckoTerminal new_pools, every 60s)
            if now-npt > 60:
                npt = now
                for p in (_gk("new_pools", page=1).get("data") or [])[:20]:
                    a = p["attributes"]; m = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]; liq = float(a.get("reserve_in_usd") or 0)
                    old = st["pools"].get(p["id"])
                    if old is None: st["pools"][p["id"]] = dict(m=m, liq=liq, t=now, name=a.get("name")); feed("new_pool", mint=m, name=a.get("name"), liq=round(liq)) if liq >= 5000 else None
                    elif old["liq"] > 5000 and liq < old["liq"]*0.5: feed("liq_pull", mint=m, name=old["name"], liq=round(liq), was=round(old["liq"])); old["liq"] = liq
                    elif liq > old["liq"]*1.5 and liq > 10000: feed("liq_add", mint=m, name=old["name"], liq=round(liq), was=round(old["liq"])); old["liq"] = liq
                st["pools"] = {k: v for k, v in st["pools"].items() if now-v["t"] < 6*3600}
            # deep flow (whale accumulation/distribution, dev + early-buyer sells) for the hottest tokens, 1 per ~20s
            hot = sorted(set(conv) | set(sbm), key=lambda m: -(conv.get(m, {}).get("score", 0)+sbm.get(m, 0)))[:8]
            if hot and now-gkt > 20:
                gkt = now; m = min(hot, key=lambda m: st["tok"].get(m, {}).get("flow_t", 0))
                try:
                    pr = requests.get("https://api.dexscreener.com/tokens/v1/solana/"+m, timeout=10).json(); best = max(pr, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))
                    try:
                        import scam; dev = scam.jup(m).get("dev")
                    except Exception: dev = None
                    g = sm.signals(best["pairAddress"], dev, None, W, 3000)
                    T = st["tok"].setdefault(m, {}); T.update(flow_t=now, sym=best["baseToken"]["symbol"], liq=(best.get("liquidity") or {}).get("usd"), whale_net=g["whale_net_usd"],
                                                            dev_sell=g["dev_sell_usd"], early_sellers=g["early_sellers"], early_n=g["early_n"])
                    if abs(g["whale_net_usd"]) >= 10000: feed("whale_accum" if g["whale_net_usd"] > 0 else "whale_dist", mint=m, sym=T["sym"], usd=g["whale_net_usd"])
                    if g["dev_sell_usd"] > 0: feed("dev_sell", mint=m, sym=T["sym"], usd=g["dev_sell_usd"])
                except Exception as e: log.debug("flow %s %s", m, e)
            # per-token score
            for m in set(conv) | set(sbm) | set(st["tok"]):
                T = st["tok"].setdefault(m, {}); c = conv.get(m, {})
                if now-T.get("flow_t", now) > 3600 and not c: st["tok"].pop(m); continue
                sc = c.get("score", 0) + 2*c.get("elite", 0) - 1.5*sbm.get(m, 0) + max(-4, min(4, (T.get("whale_net") or 0)/5000)) - (4 if (T.get("dev_sell") or 0) > 0 else 0) \
                     - (3 if T.get("early_n") and (T.get("early_sellers") or 0) >= max(3, 0.3*T["early_n"]) else 0)
                T.update(score=round(max(-15, min(15, sc)), 1), conv=c.get("score", 0), n=c.get("n", 0), elite=c.get("elite", 0), sells=sbm.get(m, 0))
                if abs(T["score"]) >= 3 and now-T.get("snap_t", 0) > 1800:
                    T["snap_t"] = now; px = _px(m)
                    if px: st["snaps"].append(dict(t=now, mint=m, score=T["score"], px=px)); open(F_TOKV, "a").write(json.dumps(dict(kind="snap", t=now, mint=m, score=T["score"], px=px))+"\n")
            keep = []
            for s_ in st["snaps"]:
                if now-s_["t"] < 3600: keep.append(s_); continue
                p1 = _px(s_["mint"])
                if p1: open(F_TOKV, "a").write(json.dumps(dict(kind="outcome", t=s_["t"], mint=s_["mint"], score=s_["score"], fwd1h=round(p1/s_["px"]-1, 4)))+"\n")
            st["snaps"] = keep
            if now-st.get("promo_t", 0) > 600: st["promo_t"] = now; promote()
            st["alerts"] = st["alerts"][-50:]; TV = tok_weight()
            json.dump(dict(ts=now, v=3, tracked=len(ranked), cycle_s=round(time.time()-t0+poll, 1), conv=conv, alerts=st["alerts"], buys=st["buys"][-40:], sells=st["sells"][-40:],
                           sells_by_mint=sbm, tokens={m: {k: v for k, v in T.items() if k != "snap_t"} for m, T in st["tok"].items()}, tok_valid=TV, feed=st["feed"][-60:],
                           counts=dict(collections.Counter(e["kind"] for e in st["feed"])), live_ranked=sum(1 for w in ranked if (WL.get(w) or {}).get("n"))),
                      open(F_ST+".tmp", "w")); os.replace(F_ST+".tmp", F_ST)
        except Exception as e: log.warning("live %s", e)
        time.sleep(poll)
def _px(m):
    try:
        r = requests.get("https://api.dexscreener.com/tokens/v1/solana/"+m, timeout=10).json()
        return float(max(r, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))["priceUsd"])
    except Exception: return None
def promote(min_n=40):
    """auto-promotion to paper decisions once 40+ live cases show an edge (convergence: mean 1h fwd > +2% and hit>50%;
    exit intel: flagged holdings fell >3pp more over the next hour than unflagged ones)"""
    P = {}
    try: P = json.load(open(F_PROMO))
    except Exception: pass
    out = [json.loads(l) for l in open(F_LIVE) if '"outcome"' in l] if os.path.exists(F_LIVE) else []
    v = [o["fwd1h"] for o in out if o.get("fwd1h") is not None]
    P["conv_live"] = dict(n=len(v), mean=round(sum(v)/len(v), 4) if v else None, hit=round(sum(x > 0 for x in v)/len(v), 3) if v else None)
    if len(v) >= min_n and P["conv_live"]["mean"] > 0.02 and P["conv_live"]["hit"] > 0.5 and not P.get("convergence"):
        P["convergence"] = True; P["convergence_src"] = "auto_live_%d" % len(v); log.warning("[insider] AUTO-PROMOTED convergence %s", P["conv_live"])
    try:
        import exit_eval; P["exit_live"] = exit_eval.run()
        e = P["exit_live"]
        if e.get("n_flag", 0) >= min_n and e.get("edge_pp", 0) > 3 and not P.get("exit"): P["exit"] = True; P["exit_src"] = "auto_live"; log.warning("[insider] AUTO-PROMOTED exit %s", e)
    except Exception as ex: P["exit_live_err"] = str(ex)[:80]
    P["t"] = time.time(); json.dump(P, open(F_PROMO, "w"), indent=1); return P
def daemon():
    """live tracking always on; rebuild wallet tiers every 30 min from mined launches; re-mine new launches every 6h"""
    threading.Thread(target=live, daemon=True).start(); mt = time.time() if os.path.exists(F_MINED) and time.time()-os.path.getmtime(F_MINED) < 6*3600 else 0; bt = 0
    while True:
        try:
            if time.time()-mt > 1200: mt = time.time(); mine(12, 12, 900)     # continuous mining: small batch every 20 min
            if time.time()-bt > 1200 and os.path.exists(F_MINED): bt = time.time(); build(); os.system("python3 research/insider_bt.py > research/insider_bt.out 2>&1")
        except Exception as e: log.warning("daemon %s", e)
        time.sleep(60)
if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    {"mine": lambda: (mine(int(sys.argv[2]) if len(sys.argv) > 2 else 80, int(sys.argv[2]) if len(sys.argv) > 2 else 80), build()), "build": build, "live": live, "daemon": daemon}[sys.argv[1]]()
