#!/usr/bin/env python3
"""trend_spot: jugada de TENDENCIA sobre los tokens líquidos de Solana (spot vía Jupiter), velas diarias. PAPEL por defecto.

Por qué: la regla validada en Keel (SuperTrend(10,3) verde + precio en la mitad alta de Bollinger(20,2) + ATR7/ATR21 > 0,85, un
día, solo largos) tiene ventaja medida en nombres líquidos (OOS Sharpe 1,15) y las memecoins recién nacidas pierden (PF 0,30 con
vetos). Aquí se aplica a los tokens de Solana con más volumen y liquidez (JUP, WIF, BONK, PYTH, JTO, RAY, ...): sin rugs, impacto
mínimo, posiciones de varios días (el rent de la cuenta de token se recupera al salir y es despreciable).

AVISO (1-nov, Keel): la misma regla sobre una cesta de perps del ecosistema Solana (31 nombres, top-5 causal por volumen) PIERDE:
ventana completa Sharpe −0,03 / −36 % / DD −72 % (btr_01m6cdsd8gwv5tegt661k8wqpb), fuera de muestra Sharpe −0,86 / −29 % / PF 0,63
(btr_01m6cdsgbvs2myvspjw7gt8p8q). La ventaja de la regla está en los grandes (BTC/ETH/SOL...), no en los tokens de Solana. Por eso esta
jugada queda SOLO en papel como evidencia hacia delante; el Director la apaga si su PF < 1 con ≥ 15 cierres y nunca la pasa a real.

Datos: GeckoTerminal público (pools por volumen; OHLCV diario), DexScreener para marcar. Evaluación una vez al día tras el cierre
de la vela UTC; marcado cada 15 min. Registro en trades_solana_trend_paper.csv (mismo formato que copytrade) y estado en
state/trend_paper.json + state/trend_status.json (panel). Pasar a real = decisión del dueño (`trend_live: true` en config.json,
exchanges.solana) y queda fuera de esta versión hasta tener 20 cierres en papel con PF > 1,3 (la misma vara que el pump play)."""
import os, sys, json, time, math, csv, logging, datetime as dt, requests

log = logging.getLogger("trend")
D = os.path.dirname(os.path.abspath(__file__))
GT, DS = "https://api.geckoterminal.com/api/v2", "https://api.dexscreener.com"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
STATE, STATUS, LEDGER = "state/trend_paper.json", "state/trend_status.json", "trades_solana_trend_paper.csv"
EXCLUDE = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY2W8kiGNYCHDsK",
           "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So", "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn", "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj",
           "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1", "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v", "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"}
P = {"universe_n": 8, "min_liq_usd": 1_500_000, "min_vol24_usd": 3_000_000, "max_positions": 3, "weight": 0.33, "budget_usd": 1000.0,
     "st_period": 10, "st_mult": 3.0, "bb_period": 20, "bb_std": 2.0, "atr_short": 7, "atr_long": 21, "atr_ratio": 0.85, "cost_pct": 0.6, "bars": 60}
_last = [0.0]


def get(url, **p):
    """GeckoTerminal free tier ~30 req/min: global spacing 2.1 s; 3 attempts"""
    for i in range(3):
        w = 2.1 - (time.time() - _last[0])
        if w > 0: time.sleep(w)
        _last[0] = time.time()
        try:
            r = requests.get(url, params=p or None, headers=H, timeout=15)
            if r.status_code == 429: time.sleep(5 + 5 * i); continue
            r.raise_for_status(); return r.json()
        except Exception as e: log.info("get %s: %s", url[-60:], e); time.sleep(2)
    return None


# ---------------------------------------------------------------- data
def universe(n=None, min_liq=None, min_vol=None, pages=2):
    """top Solana pools by 24 h volume -> one entry per base token: {sym, mint, pool, liq, vol}; stables/SOL/LSTs excluded"""
    n, min_liq, min_vol = n or P["universe_n"], min_liq or P["min_liq_usd"], min_vol or P["min_vol24_usd"]
    out, seen = [], set()
    for page in range(1, pages + 1):
        d = get(f"{GT}/networks/solana/pools", page=page, sort="h24_volume_usd_desc") or {}
        for pool in d.get("data") or []:
            a = pool.get("attributes") or {}; rel = (pool.get("relationships") or {}).get("base_token") or {}
            mint = ((rel.get("data") or {}).get("id") or "").replace("solana_", "")
            liq, vol = float(a.get("reserve_in_usd") or 0), float((a.get("volume_usd") or {}).get("h24") or 0)
            if not mint or mint in EXCLUDE or mint in seen or liq < min_liq or vol < min_vol: continue
            sym = (a.get("name") or "?").split(" /")[0].strip()
            seen.add(mint); out.append({"sym": sym, "mint": mint, "pool": a.get("address"), "liq": liq, "vol": vol})
            if len(out) >= n: return out
    return out


def daily_bars(pool, limit=None):
    """[(t, o, h, l, c, v)] ascending, UTC daily candles from GeckoTerminal"""
    d = get(f"{GT}/networks/solana/pools/{pool}/ohlcv/day", aggregate=1, limit=limit or P["bars"], currency="usd") or {}
    rows = sorted(((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or [])
    return [tuple(float(x) for x in r[:6]) for r in rows if len(r) >= 6 and all(v is not None for v in r[:5])]


def prices(mints):
    """DexScreener: {mint: price_usd} for marking"""
    out = {}
    for i in range(0, len(mints), 30):
        try:
            for p in requests.get(f"{DS}/tokens/v1/solana/" + ",".join(mints[i:i + 30]), headers=H, timeout=10).json() or []:
                m = p["baseToken"]["address"]; px = float(p.get("priceUsd") or 0)
                if px > 0 and (m not in out or float((p.get("liquidity") or {}).get("usd") or 0) > out[m][1]): out[m] = (px, float((p.get("liquidity") or {}).get("usd") or 0))
        except Exception as e: log.info("prices %s", e)
    return {m: v[0] for m, v in out.items()}


# ---------------------------------------------------------------- indicators (pure, same definitions as the Keel components)
def atr_series(bars, n):
    tr = [bars[0][2] - bars[0][3]] + [max(h - l, abs(h - bars[i - 1][4]), abs(l - bars[i - 1][4])) for i, (_, _, h, l, _, _) in enumerate(bars) if i > 0]
    out, a = [], None
    for i, x in enumerate(tr):
        if i < n - 1: out.append(None); continue
        a = sum(tr[:n]) / n if a is None else (a * (n - 1) + x) / n       # Wilder smoothing
        out.append(a)
    return out


def supertrend(bars, period=None, mult=None):
    """direction per bar: +1 (green, price above the lower band) / -1 (red); None while warming up"""
    period, mult = period or P["st_period"], mult or P["st_mult"]
    atr = atr_series(bars, period); out = []; up_prev = dn_prev = None; d = None
    for i, (_, o, h, l, c, _) in enumerate(bars):
        if atr[i] is None: out.append(None); continue
        mid = (h + l) / 2; up, dn = mid + mult * atr[i], mid - mult * atr[i]
        pc = bars[i - 1][4] if i else c
        if up_prev is not None: up = min(up, up_prev) if pc <= up_prev else up; dn = max(dn, dn_prev) if pc >= dn_prev else dn
        if d is None: d = 1 if c > up else -1
        elif d == -1 and c > up: d = 1
        elif d == 1 and c < dn: d = -1
        up_prev, dn_prev = up, dn; out.append(d)
    return out


def bollinger_pos(closes, period=None, nstd=None):
    """position of the last close inside its Bollinger channel: 0 = lower band, 0.5 = middle, 1 = upper; None without data"""
    period, nstd = period or P["bb_period"], nstd or P["bb_std"]
    if len(closes) < period: return None
    w = closes[-period:]; m = sum(w) / period; sd = math.sqrt(sum((x - m) ** 2 for x in w) / period)
    if sd <= 0: return 0.5
    lo, hi = m - nstd * sd, m + nstd * sd
    return (closes[-1] - lo) / (hi - lo)


def signal(bars, p=None):
    """the Keel rule on daily bars: dict(st_green, bb_pos, atr_ratio, entry)"""
    p = p or P
    if len(bars) < max(p["bb_period"], p["atr_long"], p["st_period"]) + 2: return {"entry": False, "why": "pocas velas"}
    st = supertrend(bars, p["st_period"], p["st_mult"])[-1]
    bb = bollinger_pos([b[4] for b in bars], p["bb_period"], p["bb_std"])
    a_s, a_l = atr_series(bars, p["atr_short"])[-1], atr_series(bars, p["atr_long"])[-1]
    ratio = (a_s / a_l) if (a_s and a_l) else None
    ok = st == 1 and bb is not None and bb > 0.5 and ratio is not None and ratio > p["atr_ratio"]
    return {"st_green": st == 1, "bb_pos": round(bb, 3) if bb is not None else None, "atr_ratio": round(ratio, 3) if ratio is not None else None, "entry": bool(ok), "close": bars[-1][4], "t": bars[-1][0]}


# ---------------------------------------------------------------- paper engine
class TrendPaper:
    def __init__(s, root=D, p=None):
        s.root, s.p = root, dict(P, **(p or {}))
        s.state_f, s.status_f, s.ledger_f = os.path.join(root, STATE), os.path.join(root, STATUS), os.path.join(root, LEDGER)
        os.makedirs(os.path.dirname(s.state_f), exist_ok=True)
        try: s.st = json.load(open(s.state_f))
        except Exception: s.st = {"cash": s.p["budget_usd"], "pos": {}, "closed": 0, "pnl": 0.0, "last_eval_day": None, "signals": {}}
    def save(s):
        tmp = s.state_f + ".tmp"; json.dump(s.st, open(tmp, "w"), indent=1); os.replace(tmp, s.state_f)
    def rec(s, sym, side, px, usd, pnl, reason, mint):
        new = not os.path.exists(s.ledger_f)
        with open(s.ledger_f, "a", newline="") as f:
            w = csv.writer(f)
            if new: w.writerow(["time", "symbol", "side", "price", "usd", "pnl", "reason", "mint"])
            w.writerow([dt.datetime.now().isoformat(timespec="seconds"), sym, side, f"{px:.8g}", f"{usd:.2f}", f"{pnl:.4f}", reason, mint])
    def equity(s, px=None):
        px = px or {}
        return s.st["cash"] + sum(q["qty"] * px.get(m, q["entry"]) for m, q in s.st["pos"].items())
    def close(s, m, px, reason):
        q = s.st["pos"].pop(m); got = q["qty"] * px * (1 - s.p["cost_pct"] / 200); pnl = got - q["usd"]
        s.st["cash"] += got; s.st["closed"] += 1; s.st["pnl"] = round(s.st["pnl"] + pnl, 4)
        s.rec(q["sym"], "SELL", px, got, pnl, reason, m); log.info("[trend] SELL %s %+.2f $ (%s)", q["sym"], pnl, reason)
    def open(s, u, px):
        usd = min(s.p["weight"] * s.p["budget_usd"], s.st["cash"])
        if usd < 5: return
        e = px * (1 + s.p["cost_pct"] / 200); qty = usd / e
        s.st["cash"] -= usd; s.st["pos"][u["mint"]] = {"sym": u["sym"], "entry": e, "qty": qty, "usd": usd, "t": time.time(), "pool": u["pool"]}
        s.rec(u["sym"], "BUY", e, usd, 0, f"trend liq={u['liq']:.0f} vol24={u['vol']:.0f}", u["mint"]); log.info("[trend] BUY %s %.2f $ @ %.6g", u["sym"], usd, e)
    def evaluate(s, now=None, uni=None, bars_fn=None):
        """once per UTC day after the daily close: exits first (rule no longer true or token out of the universe), then entries"""
        now = now or time.time(); day = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%d")
        if s.st.get("last_eval_day") == day: return False
        uni = uni if uni is not None else universe(s.p["universe_n"], s.p["min_liq_usd"], s.p["min_vol24_usd"]); bars_fn = bars_fn or daily_bars
        by = {u["mint"]: u for u in uni}; sig = {}
        for m in set(list(by) + list(s.st["pos"])):
            pool = (by.get(m) or s.st["pos"].get(m) or {}).get("pool")
            b = bars_fn(pool) if pool else []
            if b and b[-1][0] >= now - 86400 * 2 and len(b) >= 2 and b[-1][0] > now - 86400: b = b[:-1]   # the bar that is still forming is not a closed bar
            sig[m] = dict(signal(b, s.p), sym=(by.get(m) or s.st["pos"].get(m) or {}).get("sym"), in_universe=m in by)
        for m in list(s.st["pos"]):
            sg = sig.get(m) or {}
            if not sg.get("entry") or not sg.get("in_universe"): s.close(m, sg.get("close") or s.st["pos"][m]["entry"], "rule_off" if sg.get("in_universe") else "left_universe")
        allowed = s.director_allows()
        for u in uni:
            if len(s.st["pos"]) >= s.p["max_positions"] or not allowed: break
            sg = sig.get(u["mint"]) or {}
            if sg.get("entry") and u["mint"] not in s.st["pos"]: s.open(u, sg["close"])
        s.st["last_eval_day"] = day; s.st["signals"] = {m: {k: v for k, v in sg.items() if k != "t"} for m, sg in sig.items()}; s.save(); return True
    def director_allows(s):
        """director_state.json plays.trend: 'off' (evidence says it loses) blocks new entries; missing state = allowed (paper)"""
        try:
            st = json.load(open(os.path.join(s.root, "director_state.json")))
            return (st.get("plays") or {}).get("trend", "paper") != "off"
        except Exception: return True
    def mark(s, px=None):
        px = px if px is not None else (prices(list(s.st["pos"])) if s.st["pos"] else {})
        pos = [{"sym": q["sym"], "mint": m, "entry": q["entry"], "mark": px.get(m), "usd": q["usd"], "pnl": round(q["qty"] * px[m] - q["usd"], 4) if m in px else None,
                "age_h": round((time.time() - q["t"]) / 3600, 1)} for m, q in s.st["pos"].items()]
        out = {"ts": time.time(), "mode": "paper", "budget_usd": s.p["budget_usd"], "equity": round(s.equity(px), 2), "cash": round(s.st["cash"], 2), "closed": s.st["closed"], "pnl": s.st["pnl"],
               "positions": pos, "last_eval_day": s.st.get("last_eval_day"), "signals": s.st.get("signals") or {}, "rule": "SuperTrend(10,3) verde + Bollinger(20,2) > 0,5 + ATR7/ATR21 > 0,85, diario, solo largos. Keel sobre perps de Solana: OOS Sharpe −0,86 → solo evidencia en papel"}
        tmp = s.status_f + ".tmp"; json.dump(out, open(tmp, "w"), indent=1); os.replace(tmp, s.status_f); return out


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"); os.chdir(D)
    t = TrendPaper()
    if "--loop" in argv:
        while not os.path.exists("STOP"):
            try:
                u = dt.datetime.now(dt.timezone.utc)
                if u.hour * 60 + u.minute >= 10: t.evaluate()          # once per UTC day, from 00:10 (the daily candle is closed); idempotent
                t.mark()
            except Exception as e: log.warning("[trend] %s", e)
            time.sleep(900)
        return 0
    changed = t.evaluate(); st = t.mark(); print(json.dumps({"evaluated": changed, **{k: st[k] for k in ("equity", "cash", "closed", "pnl", "last_eval_day")}, "positions": [p["sym"] for p in st["positions"]]}, ensure_ascii=False)); return 0


if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
