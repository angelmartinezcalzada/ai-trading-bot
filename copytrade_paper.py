"""PAPER copy-trade of elite insider convergence alerts (insider_status.json). No keys, no swaps.
Entry: new alert with elite>=3, DexScreener liq>=min_liq, price*(1+COST/2). Exit: an elite wallet sells that mint, +15% / -8%, or 30 min. Cost 0.6% round trip."""
import json, time, csv, os, requests
D = os.path.dirname(os.path.abspath(__file__)); ST = os.path.join(D, "state", "copytrade_paper.json"); CSV = os.path.join(D, "trades_solana_copy_paper.csv")
COST, SIZE, TP, SL, HOLD, MINLIQ = 0.006, 2.0, 0.15, 0.08, 1800, 50000
st = json.load(open(ST)) if os.path.exists(ST) else {"pos": {}, "seen": [], "closed": 0, "pnl": 0.0}
def px(m, pair=None):
    """Price from the entry pool when known (a pulled pool must not be replaced by a dust pool's bogus quote)."""
    try:
        p = [x for x in requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{m}", timeout=10).json().get("pairs") or [] if x.get("chainId") == "solana"]
        if pair:
            q = [x for x in p if x.get("pairAddress") == pair]
            if not q: return 0.0, 0, "gone"  # entry pool vanished -> liquidity pulled
            p = q
        p = max(p, key=lambda x: (x.get("liquidity") or {}).get("usd", 0)); return float(p["priceUsd"]), (p.get("liquidity") or {}).get("usd", 0), p["baseToken"]["symbol"], p.get("pairAddress")
    except Exception: return None, 0, "?"
import scam
from copytrade_rules import rug_step, exit_reason
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
def veto(m, sym, p):
    try:
        C = json.load(open(os.path.join(D, "config.json")))["exchanges"]["solana"]
        r = scam.rc(m)
        if not r and m not in scam.verified()[0]: return ["no_rugcheck_report"]
        f = []
        if r.get("mintAuthority"): f.append("mint_auth")
        if r.get("freezeAuthority"): f.append("freeze_auth")
        lp = max([(mk.get("lp") or {}).get("lpLockedPct") or 0 for mk in r.get("markets") or []] or [0])
        if r and lp < C.get("min_lp_locked_pct", 90): f.append(f"lp_unlocked{lp:.0f}")
        import live_sol; q1 = live_sol.quote(USDC, m, SIZE*1e6, 100)
        q2 = live_sol.quote(m, USDC, q1["outAmount"], 100)
        rt = (1-int(q2["outAmount"])/(SIZE*1e6))*100
        if rt > C.get("max_roundtrip_loss_pct", 3): f.append(f"honeypot_rt{rt:.1f}")
        return f + scam.check(m, sym, p, C, rt)
    except Exception as e: return [f"veto_error:{str(e)[:40]}"]
def rec(*r):
    new = not os.path.exists(CSV)
    with open(CSV, "a", newline="") as f:
        w = csv.writer(f); new and w.writerow(["time", "symbol", "side", "price", "usd", "pnl", "reason", "mint"]); w.writerow(r)
while True:
    try:
        S = json.load(open(os.path.join(D, "insider_status.json"))); now = time.time()
        sells = {x["mint"] for x in S.get("sells", []) if x.get("tier") == "elite" and x["t"] > now-120}
        for a in S.get("alerts", []):
            m = a["mint"]
            if m in st["seen"] or a.get("elite", 0) < 3 or now-a["t"] > 180 or len(st["pos"]) >= 5: continue
            st["seen"] = (st["seen"]+[m])[-500:]; r0 = px(m); p, liq, sym = r0[:3]; pair = r0[3] if len(r0) > 3 else None
            if not p or liq < MINLIQ: continue
            v = veto(m, sym, p)   # same anti-rug vetoes as memebot (rugpull 31-oct); fail-closed
            if v: print("veto", sym, ",".join(v), flush=True); continue
            e = p*(1+COST/2); st["pos"][m] = {"sym": sym, "e": e, "t": now, "pair": pair, "liq": liq}; rec(time.strftime("%Y-%m-%dT%H:%M:%S"), sym, "BUY", e, SIZE, 0, f"elite={a['elite']} liq={liq:.0f}", m)
        for m, q in list(st["pos"].items()):
            r0 = px(m, q.get("pair")); p, liq = r0[0], r0[1]
            if p is None: continue
            rug = rug_step(q, p, liq)                      # 2 consecutive bad polls (see copytrade_rules.py)
            r = -1.0 if rug else p*(1-COST/2)/q["e"]-1
            why = exit_reason(q, rug, r, m in sells, now, TP, SL, HOLD)
            if why:
                pnl = SIZE*r; st["closed"] += 1; st["pnl"] += pnl; st["pos"].pop(m)
                rec(time.strftime("%Y-%m-%dT%H:%M:%S"), q["sym"], "SELL", p, SIZE, round(pnl, 4), why, m)
        os.makedirs(os.path.dirname(ST), exist_ok=True); json.dump(st, open(ST, "w"))
    except Exception as ex: print("err", ex, flush=True)
    time.sleep(20)
