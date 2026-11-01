"""Forward evaluation of the memecoin filters/score using candidates_solana.jsonl.
 - ret_now : price now vs price at first sighting (DexScreener)
 - replay  : GeckoTerminal 1m OHLCV path from first sighting, simulating the bot's exits (impact-aware stop, 50% TP at +25%, trail, 12h)
             with round-trip cost = logged roundtrip_loss_pct (or 3% default). Cached in replay_cache.json, ~25 new pools per run.
Writes eval_solana.json (shown on dashboard)."""
import json, time, os, datetime as dt, statistics as st, requests, sys
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
def get(u, **p):
    for i in range(3):
        try:
            r = requests.get(u, params=p or None, headers=H, timeout=15)
            if r.status_code == 429: time.sleep(5+5*i); continue
            return r.json()
        except Exception: time.sleep(2)
def load(hours=72):
    first = {}; cut = time.time()-hours*3600
    for l in open("candidates_solana.jsonl"):
        try: r = json.loads(l)
        except Exception: continue
        t = dt.datetime.fromisoformat(r["ts"]).timestamp()
        if t < cut or not r.get("price"): continue
        r["_t"] = t
        if r["mint"] not in first: first[r["mint"]] = r
        elif r["pass"] and not first[r["mint"]]["pass"]: first[r["mint"]] = r          # entry moment if it ever passed
    return first
def group(r):
    if r["pass"]: return "PASS (comprado/elegible)"
    f = [x.split(":")[0] for x in r["fail"]]
    return "rechazo:" + (f[0] if len(f) == 1 else "varios" if f else "?")
def sim(path, rt, c, info=None):
    """path: list of (t, o,h,l,c) after entry. returns net return incl. costs; `info` (dict) receives exit reason and time.
    Replays the LIVE exit rule: exit_mode='trail' = memebot.trail_exit (hard stop net of costs, trail from peak, no TP / time exit);
    otherwise the v3.1 bracket. Bars are resolved conservatively (31-oct review): stop with the low first, trail against the
    PREVIOUS bar's best, then the partial TP with the high - never TP-before-stop inside one candle."""
    if not path: return None
    info = info if info is not None else {}
    e = path[0][1]; t0 = path[0][0]
    def done(ret, why, t): info.update(exit=why, t_exit=t); return ret
    if c.get("exit_mode") == "trail":
        cost = rt/100; hs = c.get("hard_stop_pct", 6)/100; tr = c.get("trail_pct_tt", 12)/100; best = e
        net = lambda x: x/e*(1-cost)-1
        for t, o, h, l, cl in path:
            if net(l) <= -hs: return done(min(-hs, net(cl)), "hard_stop", t)                      # a rug candle (close far below the stop) is a rug, not a -6%
            if best > e and l <= best*(1-tr): return done(min(net(best*(1-tr)), net(cl)), "trail", t)
            best = max(best, h)
        return done(net(path[-1][4]), "open", path[-1][0])
    stop = max(c["stop_pct"], min(c["max_stop_pct"], c["stop_pct"]+rt/100)); half = 1.0; real = 0.0; best = e; part = False
    for t, o, h, l, cl in path:
        if l <= e*(1-stop): return done(real + half*min(-stop, cl/e-1) - rt/100, "stop", t)
        tr = c["runner_trail_pct"] if part else c["trail_pct"]
        if best >= e*(1+c["trail_activate_pct"]) and l <= best*(1-tr): return done(real + half*min(best*(1-tr)/e-1, cl/e-1) - rt/100, "trail", t)
        if not part and h >= e*(1+c["partial_tp_pct"]): real += c["partial_tp_frac"]*c["partial_tp_pct"]; half -= c["partial_tp_frac"]; part = True; stop = 0.0
        best = max(best, h)
        if t-t0 > c["max_hold_hours"]*3600: return done(real + half*(cl/e-1) - rt/100, "time", t)
    return done(real + half*(path[-1][4]/e-1) - rt/100, "open", path[-1][0])
def run(c, max_new=25):
    first = load(); mints = list(first); now = {}
    for i in range(0, len(mints), 30):
        for p in get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(mints[i:i+30])) or []:
            m = p["baseToken"]["address"]
            if m in first and (p.get("pairAddress") == first[m].get("pair") or m not in now):
                now[m] = float(p.get("priceUsd") or 0); first[m].setdefault("pair", p.get("pairAddress"))
    cache = json.load(open("replay_cache.json")) if os.path.exists("replay_cache.json") else {}
    todo = [m for m, r in sorted(first.items(), key=lambda x: (not x[1]["pass"], x[1]["_t"])) if r.get("pair") and r["liq"] >= c["min_liquidity_usd"]
            and time.time()-r["_t"] > 1200 and (m not in cache or (not cache[m].get("final") and time.time()-cache[m]["at"] > 1800))]
    for m in todo[:max_new]:
        r = first[m]; time.sleep(2.5)
        d = get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{r['pair']}/ohlcv/minute", aggregate=1, limit=1000, currency="usd")
        try: rows = sorted(d["data"]["attributes"]["ohlcv_list"])
        except Exception: continue
        path = [x[:5] for x in rows if x[0] >= r["_t"]-60]
        if not path or path[0][0]-r["_t"] > 300: continue   # candles start long after the sighting: the replay would start at a different price
        rt = r.get("roundtrip_loss_pct") or 3.0
        cache[m] = {"at": time.time(), "ret": sim(path, rt, c), "final": time.time()-r["_t"] > c["max_hold_hours"]*3600, "bars": len(path)}
    json.dump(cache, open("replay_cache.json", "w"))
    G = {}
    for m, r in first.items():
        if r["liq"] < c["min_liquidity_usd"]: g = "rechazo:liq<min"
        else: g = group(r)
        x = G.setdefault(g, {"n": 0, "now": [], "rep": []}); x["n"] += 1
        if now.get(m) and float(r["price"]) > 0: x["now"].append(now[m]/float(r["price"])-1)
        if cache.get(m, {}).get("ret") is not None: x["rep"].append(cache[m]["ret"])
    def agg(v):
        v = [max(-1, min(a, 5)) for a in v]   # clip outliers at +500% for the mean
        return {"n": len(v), "media_%": round(st.mean(v)*100, 1) if v else None, "mediana_%": round(st.median(v)*100, 1) if v else None,
                        "win_%": round(sum(1 for a in v if a > 0)/len(v)*100) if v else None}
    groups = {g: {"candidatos": x["n"], "precio_ahora": agg(x["now"]), "replay_estrategia": agg(x["rep"])} for g, x in sorted(G.items())}
    # score thresholds among tokens passing all hard filters
    sb = {}
    for m, r in first.items():
        if r.get("score") is None or [f for f in r["fail"] if not f.startswith("score")]: continue
        b = f"{int(r['score']//10*10)}-{int(r['score']//10*10+9)}"; v = cache.get(m, {}).get("ret")
        y = sb.setdefault(b, {"now": [], "rep": []})
        if now.get(m): y["now"].append(now[m]/float(r["price"])-1)
        if v is not None: y["rep"].append(v)
    buckets = {b: {"precio_ahora": agg(y["now"]), "replay": agg(y["rep"])} for b, y in sorted(sb.items())}
    out = {"generado": dt.datetime.now().isoformat(timespec="seconds"), "ventana_h": 72, "tokens": len(first), "replay_cacheados": len(cache),
           "grupos": groups, "score_buckets (pasan filtros duros)": buckets}
    json.dump(out, open("eval_solana.json", "w"), indent=1); return out
if __name__ == "__main__":
    c = json.load(open("config.json"))["exchanges"]["solana"]; print(json.dumps(run(c, int(sys.argv[1]) if len(sys.argv) > 1 else 25), indent=1, ensure_ascii=False))
