"""Panel móvil v2 (solo lectura). Datos cacheados 4 s, lectura de colas de ficheros; nunca toca trading/config/claves."""
import os, json, time, re, csv, io, subprocess, threading, collections
from flask import jsonify, Response
D = os.path.dirname(os.path.abspath(__file__)); P = lambda f: os.path.join(D, f)
_C = {"t": 0, "d": None}; _L = threading.Lock()
def J(f, d=None):
    try: return json.load(open(P(f)))
    except Exception: return d
def tail(f, nbytes=250_000):
    try:
        with open(P(f), "rb") as h:
            h.seek(0, 2); s = h.tell(); h.seek(max(0, s-nbytes)); L = h.read().decode(errors="replace").splitlines()
            return L[1:] if s > nbytes else L
    except FileNotFoundError: return []
def csvrows(f, n):
    try: hdr = next(csv.reader([open(P(f)).readline()]))
    except Exception: return []
    L = [l for l in tail(f, 60_000) if l and not l.startswith(hdr[0]+",")][-n:]
    return [dict(zip(hdr, r)) for r in csv.reader(L)]
def mtime(f):
    try: return os.path.getmtime(P(f))
    except Exception: return None
TS = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
def procs():
    try: out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, timeout=2).stdout
    except Exception: out = ""
    defs = [("Solana (real)", "bot.py --exchange solana", "bot_solana.log"), ("Coinbase", "bot.py --exchange coinbase", "bot_coinbase.log"),
            ("Binance (papel)", "bot.py --exchange binance", "bot_binance.log"), ("Insiders", "insider", "stdout_insider.log"),
            ("Copytrade (papel)", "copytrade_paper.py", "stdout_copytrade.log"), ("Panel", "dashboard.py", None)]
    now = time.time(); r = []
    for name, pat, log in defs:
        up = any(pat in l and "grep" not in l for l in out.splitlines()); m = mtime(log) if log else now
        r.append({"name": name, "up": up, "log_age_s": None if m is None else round(now-m)})
    return r
def solana_activity():
    scans, blocked, reasons, events = [], [], collections.Counter(), []
    cut = time.time() - 24*3600; last_pref = None
    for l in tail("bot_solana.log", 400_000):
        m = TS.match(l)
        if not m: continue
        t = m.group(1)
        try:
            if time.mktime(time.strptime(t, "%Y-%m-%d %H:%M:%S")) < cut: continue
        except Exception: continue
        msg = l.split("] ", 1)[-1]; hm = t[11:16]
        if "prefilter" in msg:
            mm = re.search(r"prefilter (\d+)/(\d+) -> eval (\d+)(?: \((\d+) skipped)?", msg)
            if mm: last_pref = mm.groups()
        elif " SCAN " in l or msg.startswith("SCAN "):
            mm = re.search(r"SCAN (\d+) mints, (\d+) pairs, (\d+) >= liq, (\d+) passed", msg)
            if mm:
                a = mm.groups(); scans.append({"t": hm, "mints": int(a[0]), "liq": int(a[2]), "passed": int(a[3]),
                     "eval": int(last_pref[2]) if last_pref else None, "skipped": int(last_pref[3] or 0) if last_pref else None}); last_pref = None
        mm = re.search(r"SCAM block (\S+): (\S+)", msg)
        if mm:
            for k in mm.group(2).split(","): reasons["scam: "+re.sub(r"[\d.%h]+$", "", k)] += 1
            continue
        mm = re.search(r"buy (\S+) blocked: ([a-z ]+)", msg)
        if mm:
            reasons["bloqueo: "+mm.group(2).strip()] += 1; blocked.append({"t": hm, "sym": mm.group(1), "why": re.sub(r" tx=\S+", "", msg.split("blocked: ", 1)[1])[:120]}); continue
        mm = re.search(r"skipped: ([a-z][a-z_ ]*[a-z])", msg)
        if mm and "hard-vetoed" not in msg: reasons["descartada: "+mm.group(1).strip()[:30]] += 1
        if re.search(r"LIVE (buy|sell|BUY|SELL)|EXIT |HALT|KILL|SWITCHING|ERROR|Traceback", msg) and "blocked" not in msg:
            events.append(hm + " " + re.sub(r"wallet \S+|tx=\S+", "", msg)[:160])
    return scans[-12:][::-1], blocked[-10:][::-1], reasons.most_common(10), events[-10:][::-1]
def decisions(n=4):
    txt = "\n".join(tail("DECISIONS.md", 40_000)); parts = re.split(r"\n(?=## )", txt)
    return [p.strip()[:900] for p in parts if p.startswith("## ")][-n:][::-1]
def build():
    st = J("status_solana.json", {}) or {}; raw = (J("state_solana_live.json", {}) or {}).get("pos", {})
    eq = []
    for l in tail("equity_solana.csv", 80_000):
        try:
            a, b = l.split(",")[:2]; t = int(float(a)); v = float(b)
            if v < 500 and t > time.time()-48*3600: eq.append((t, round(v, 3)))
        except Exception: pass
    eq = eq[::max(1, len(eq)//200)]
    pos = []
    for p in st.get("positions") or []:
        e = p.get("entry") or 0; best = (raw.get(p.get("mint")) or {}).get("best") or max(e, p.get("mark") or 0)
        pos.append({"sym": p.get("sym"), "entry": e, "mark": p.get("mark"), "pnl": p.get("pnl"), "pnl_pct": p.get("pnl_pct"), "age_min": p.get("age_min"),
                    "cost": p.get("cost"), "stop": e*0.94, "trail": best*0.88, "peak": best})
    trades = [{"t": r.get("time", "")[5:16].replace("T", " "), "sym": (r.get("symbol") or "").strip(), "side": r.get("side"),
               "pnl": float(r.get("pnl") or 0), "why": re.sub(r" tx=\S+", "", r.get("reason", ""))[:70]} for r in csvrows("trades_solana_live.csv", 15)][::-1]
    scans, blocked, reasons, events = solana_activity()
    b = J("brain_state.json", {}) or {}; o = b.get("oos") or {}
    brain = {"active": b.get("active"), "updated": b.get("updated"), "n": b.get("n_labelled"), "policy": o.get("policy"),
             "trades": o.get("brain_trades"), "base_ret": o.get("baseline_avg_ret_%"), "ret": o.get("brain_avg_ret_%")}
    ex = {}
    for k in ("coinbase", "binance"):
        s = J(f"status_{k}.json", {}) or {}
        ex[k] = {"mode": s.get("mode"), "equity": s.get("equity"), "cash": s.get("cash"), "day": s.get("day_pnl_pct"), "halted": s.get("halted"),
                 "open": len(s.get("positions") or []), "age_s": round(time.time()-(s.get("ts") or 0))}
    stt = st.get("stats") or {}
    return {"now": time.time(), "ts": st.get("ts"), "equity": st.get("equity"), "cash": st.get("cash"), "day_pct": st.get("day_pnl_pct"),
            "halted": st.get("halted"), "paused": st.get("paused"), "mode": st.get("mode"), "eq": eq, "pos": pos, "trades": trades,
            "stats": stt, "scans": scans, "blocked": blocked, "reasons": reasons, "events": events, "brain": brain, "ex": ex,
            "procs": procs(), "decisions": decisions()}
def api():
    with _L:
        if time.time()-_C["t"] > 4 or _C["d"] is None:
            try: _C["d"] = build()
            except Exception as e: _C["d"] = {"error": str(e), "now": time.time()}
            _C["t"] = time.time()
        return _C["d"]
PAGE = open(P("panel_v2.html")).read() if os.path.exists(P("panel_v2.html")) else "falta panel_v2.html"
def register(app):
    app.add_url_rule("/movil", "movil", lambda: Response(open(P("panel_v2.html")).read(), mimetype="text/html", headers={"Cache-Control": "no-store"}))
    app.add_url_rule("/api/live2", "api_live2", lambda: jsonify(api()))
