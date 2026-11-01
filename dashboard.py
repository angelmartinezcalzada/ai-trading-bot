#!/usr/bin/env python3
"""Panel web (español) del bot. Auth por contraseña (dashboard_password.txt). Puerto 8787."""
import os, json, time, csv, subprocess, secrets, hmac, collections
from flask import Flask, request, session, jsonify, redirect, Response
from dash_data import build_overview, ACT   # pure aggregator for /api/overview; ACT = activity regex table (importable without side effects)
D = os.path.dirname(os.path.abspath(__file__)); os.chdir(D)
PW = open("dashboard_password.txt").read().strip()
if not os.path.exists(".flask_secret"): open(".flask_secret", "w").write(secrets.token_hex(32)); os.chmod(".flask_secret", 0o600)
app = Flask(__name__); app.secret_key = open(".flask_secret").read().strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=7*86400)
FAILS = collections.defaultdict(list)
KEYS = {"binance": ["BINANCE_API_KEY", "BINANCE_API_SECRET"], "coinbase": ["COINBASE_API_KEY", "COINBASE_API_SECRET"], "solana": ["SOLANA_PRIVATE_KEY"]}
EDIT = {"risk_per_trade_pct": (0.005, 0.5), "max_positions": (1, 20), "daily_max_drawdown_pct": (0.005, 0.5), "cooldown_minutes": (0, 240),
        "atr_stop_mult": (0.3, 10), "take_profit_atr_mult": (0.3, 50), "max_spread_pct": (0.01, 2), "deep_scan_top": (3, 60)}

def cfg(): return json.load(open("config.json"))
def save_cfg(c): json.dump(c, open("config.json.tmp", "w"), indent=2); os.replace("config.json.tmp", "config.json")
def keys_present(ex):
    if not os.path.exists("keys.env"): return False
    txt = open("keys.env").read(); return all(f"{k}=" in txt and txt.split(f"{k}=")[1].split("\n")[0].strip() for k in KEYS.get(ex, ["X"]))
def pid_of(ex):
    try:   # pgrep missing or slow must never fail the response
        r = subprocess.run(["pgrep", "-f", f"python3 bot.py --exchange {ex}"], capture_output=True, text=True, timeout=3)
        return [int(x) for x in r.stdout.split() if x.isdigit()]
    except Exception: return []
def ctl(ex):
    f = f"control_{ex}.json"
    try: return json.load(open(f))
    except Exception: return {}
def set_ctl(ex, **kw):
    c = ctl(ex); c.update(kw); json.dump(c, open(f"control_{ex}.json.tmp", "w")); os.replace(f"control_{ex}.json.tmp", f"control_{ex}.json")
def tail(path, n):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); sz = f.tell(); f.seek(max(0, sz-200_000)); return f.read().decode(errors="replace").splitlines()[-n:]
    except FileNotFoundError: return []

@app.before_request
def guard():
    if request.path in ("/login", "/health"): return
    if not session.get("ok"):
        return (jsonify(error="auth"), 401) if request.path.startswith("/api") else redirect("/login")
    if request.method == "POST" and request.headers.get("X-CSRF") != session.get("csrf"): return jsonify(error="csrf"), 403

@app.route("/health")
def health(): return "ok"

@app.route("/login", methods=["GET", "POST"])
def login():
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr); now = time.time()
    FAILS[ip] = [t for t in FAILS[ip] if now-t < 900]; msg = ""
    if request.method == "POST":
        if len(FAILS[ip]) >= 8: msg = "Demasiados intentos. Espera 15 minutos."
        elif hmac.compare_digest(request.form.get("pw", ""), PW):
            session.permanent = True; session["ok"] = True; session["csrf"] = secrets.token_hex(16); return redirect("/")
        else: FAILS[ip].append(now); msg = "Contraseña incorrecta."
    return Response(LOGIN.replace("{{msg}}", msg), mimetype="text/html")

@app.route("/logout")
def logout(): session.clear(); return redirect("/login")

@app.route("/")
def root():
    """Panel v2 (dashboard_v2.html, csrf injected like /panel); falls back to the old /live redirect while the file is missing."""
    f = os.path.join(D, "dashboard_v2.html")
    if not os.path.exists(f): return redirect("/live")
    return Response(open(f, encoding="utf-8").read().replace("{{csrf}}", session.get("csrf") or ""), mimetype="text/html")
@app.route("/v1")
def root_v1(): return redirect("/live")
@app.route("/api/overview")
def overview():
    """Everything the v2 panel shows, from files under D only (dash_data.build_overview: no network, never raises)."""
    return jsonify(build_overview(D))
@app.route("/panel")
def index(): return Response(_page().replace("{{csrf}}", session["csrf"]), mimetype="text/html")

def insider_view():
    def J(f, d=None):
        try: return json.load(open(f))
        except Exception: return d
    W = J("insider_wallets.json", {}) or {}; ws = W.get("wallets", {}); st = J("insider_status.json", {}) or {}; P = J("insider_promoted.json", {}) or {}
    top = sorted(({"w": k[:4]+"…"+k[-4:], **v} for k, v in ws.items()), key=lambda x: ({"elite": 0, "good": 1, "watch": 2}[x["tier"]], -x["sc"]))[:25]
    mined = sum(1 for _ in open("research/insider_mined.jsonl")) if os.path.exists("research/insider_mined.jsonl") else 0
    sh = lambda L: [dict(x, w=x["w"][:4]+"…"+x["w"][-4:], mint=x["mint"]) for x in (L or [])[-15:]][::-1]
    return dict(tiers=W.get("tiers", {}), launches=W.get("launches", 0), mined=mined, built_t=W.get("t"), top=top, tracked=st.get("tracked", 0), live_ts=st.get("ts"),
                buys=sh(st.get("buys")), sells=sh(st.get("sells")), alerts=(st.get("alerts") or [])[-10:][::-1], feed=(st.get("feed") or [])[-40:][::-1], tokens=sorted(({"mint": k, **v} for k, v in (st.get("tokens") or {}).items()), key=lambda x: -abs(x.get("score", 0)))[:15], tok_valid=st.get("tok_valid"), counts=st.get("counts"), cycle_s=st.get("cycle_s"), promoted=P, bt=J("research/insider_bt.json"))
@app.route("/api/copytrade")
def copytrade():
    """PAPER copy-trade of elite insider alerts (copytrade_paper.py)"""
    try: st = json.load(open("state/copytrade_paper.json"))
    except Exception: st = {}
    rows = tail("trades_solana_copy_paper.csv", 50) if os.path.exists("trades_solana_copy_paper.csv") else []
    return {"mode": "paper", "closed": st.get("closed", 0), "pnl": round(st.get("pnl", 0), 4), "open": st.get("pos", {}), "recent": rows}
@app.route("/api/hl")
def hl():
    """Hyperliquid leg: Keel paper run + backtest evidence + Coinversa risk context (hl_leg/, data/hl_*). Read-only."""
    def J(f, d=None):
        try: return json.load(open(f))
        except Exception: return d
    return jsonify(paper=J("hl_leg/hl_paper.json", {}), evidence=(J("hl_leg/evidence.json", {}) or {}).get("selected", {}),
                   risk=J("data/hl_risk.json", {}), context=tail("data/hl_context.csv", 60))
@app.route("/api/state")
def state():
    c = cfg(); out = {"ts": time.time(), "exchanges": {}}
    tun = open("tunnel_url.txt").read().strip() if os.path.exists("tunnel_url.txt") else None
    for ex, ec in c["exchanges"].items():
        try: st = json.load(open(f"status_{ex}.json"))
        except Exception: st = {}
        eqs = []
        try:
            for line in tail(f"equity_{ex}.csv", 2880):
                t, v = line.split(","); eqs.append([int(t)*1000, float(v)])
        except Exception: pass
        mode = ec.get("mode", "paper"); tf = f"trades_{ex}_{mode}.csv"; trades = []
        if os.path.exists(tf):
            with open(tf) as f: trades = list(csv.DictReader(f))[-150:][::-1]
        pids = pid_of(ex); age = time.time()-st.get("ts", 0)
        health = "parado" if os.path.exists(f"STOP_{ex}") and not pids else "ok" if pids and age < 120 else "arrancando" if pids else "caído"
        out["exchanges"][ex] = {"status": st, "equity_curve": eqs, "trades": trades, "pids": pids, "status_age_s": age, "health": health,
                                "stopped": os.path.exists(f"STOP_{ex}"), "paused": bool(ctl(ex).get("pause")), "mode": mode,
                                "keys_present": keys_present(ex), "enabled": ec.get("enabled", True), "start_equity": ec.get("starting_equity", c.get("starting_equity", 1000))+(st.get("net_deposits") or 0), "net_deposits": st.get("net_deposits") or 0}
    try:
        sst = out["exchanges"]["solana"]["status"]; lt = []
        if os.path.exists("trades_solana_live.csv"):
            with open("trades_solana_live.csv") as f: lt = list(csv.DictReader(f))[-100:][::-1]
        addr = (sst.get("wallet") or {}).get("addr")
        if not addr and os.path.exists("solana_wallet.json"):
            import live_sol; addr = live_sol.address()
        out["sol_real"] = {"addr": addr, "wallet": sst.get("wallet"), "active": sst.get("mode") == "live", "min_sol": sst.get("live_min_sol", 0.05),
                           "killed": os.path.exists("KILL_solana"), "trades": lt, "equity": sst.get("equity") if sst.get("mode") == "live" else None,
                           "positions": sst.get("positions") if sst.get("mode") == "live" else []}
    except Exception as e: out["sol_real"] = {"error": str(e)}
    for ex, E in out["exchanges"].items():
        ec = c["exchanges"][ex]; E["risk"] = {k: ec.get(k, c.get(k)) for k in VEX.get(ex, {})}; E["risk_limits"] = VEX.get(ex, {}); E["killed"] = os.path.exists(f"KILL_{ex}")
    out["config"] = {k: c[k] for k in EDIT}; out["config"]["strategies"] = c["strategies"]; out["tunnel"] = tun
    try: out["research"] = json.load(open("research/summary.json"))
    except Exception: out["research"] = []
    try: out["news"] = json.load(open("news_state.json"))
    except Exception: out["news"] = None
    out["insider"] = insider_view()
    out["supervisor"] = tail("supervisor.log", 12)
    return jsonify(out)

@app.route("/api/logs")
def logs():
    ex = request.args.get("ex", "binance"); n = min(int(request.args.get("n", 120)), 500)
    if ex not in cfg()["exchanges"] and ex != "supervisor": return jsonify(error="bad ex"), 400
    return jsonify(lines=tail("supervisor.log" if ex == "supervisor" else f"bot_{ex}.log", n))


VEX = {"solana": {"risk_per_trade": (0.001, 0.01), "max_position_pct": (0.005, 0.08), "max_gap_loss_pct": (0.005, 0.05), "max_trade_loss_pct": (0.002, 0.03),
                  "daily_max_drawdown_pct": (0.01, 0.12), "max_positions": (1, 10), "min_score": (30, 90)},
       "binance": {"daily_max_drawdown_pct": (0.01, 0.1), "max_trade_loss_pct": (0.005, 0.05)},
       "coinbase": {"daily_max_drawdown_pct": (0.01, 0.1), "max_trade_loss_pct": (0.005, 0.05)}}
# ACT (activity classifier regex table) lives in dash_data.py and is imported at the top of this file.
@app.route("/api/activity")
def activity():
    out = []
    for ex in cfg()["exchanges"]:
        for l in tail(f"bot_{ex}.log", 400):
            if len(l) < 24 or not l[:4].isdigit(): continue
            k = next((k for k, r in ACT if r.search(l)), None)
            if not k: continue
            msg = l[24:].split(" ", 1)[-1]
            out.append({"t": l[:19], "ex": ex, "kind": k, "msg": msg[:300]})
    out.sort(key=lambda x: x["t"], reverse=True)
    kinds = request.args.get("kinds"); 
    if kinds: out = [o for o in out if o["kind"] in kinds.split(",")]
    return jsonify(items=out[:int(request.args.get("n", 150))])

@app.route("/api/action", methods=["POST"])
def action():
    j = request.get_json(force=True); a = j.get("action"); ex = j.get("ex"); c = cfg()
    if ex and ex not in c["exchanges"]: return jsonify(ok=False, msg="exchange desconocido"), 400
    if a == "stop":
        open(f"STOP_{ex}", "w").close(); return jsonify(ok=True, msg=f"{ex} se está deteniendo")
    if a == "start":
        if os.path.exists(f"STOP_{ex}"): os.remove(f"STOP_{ex}")
        return jsonify(ok=True, msg=f"{ex} arrancando (unos segundos)")
    if a in ("pause", "resume"):
        set_ctl(ex, pause=(a == "pause")); return jsonify(ok=True, msg=f"{ex}: nuevas entradas {'pausadas' if a == 'pause' else 'reanudadas'}")
    if a == "close":
        sym = j.get("sym", ""); cl = ctl(ex).get("close", [])
        if sym not in cl: cl.append(sym)
        set_ctl(ex, close=cl); return jsonify(ok=True, msg=f"Cierre de {sym} solicitado")
    if a == "config":
        for k, v in (j.get("values") or {}).items():
            if k in EDIT:
                lo, hi = EDIT[k]; v = float(v)
                if not lo <= v <= hi: return jsonify(ok=False, msg=f"{k} fuera de rango [{lo}, {hi}]"), 400
                c[k] = int(v) if k in ("max_positions", "deep_scan_top") else v
        for k, v in (j.get("strategies") or {}).items():
            if k in c["strategies"]: c["strategies"][k] = bool(v)
        save_cfg(c); return jsonify(ok=True, msg="Configuración guardada (se aplica en el siguiente ciclo)")
    if a == "kill":
        st = {}
        try: st = json.load(open(f"status_{ex}.json"))
        except Exception: pass
        set_ctl(ex, pause=True, close=[p["sym"] for p in st.get("positions", [])])
        if ex == "coinbase": open("KILL_coinbase", "w").close()
        return jsonify(ok=True, msg=f"KILL {ex}: entradas pausadas y cierre de todas las posiciones solicitado")
    if a == "unkill":
        if os.path.exists(f"KILL_{ex}"): os.remove(f"KILL_{ex}")
        set_ctl(ex, pause=False, close=[]); return jsonify(ok=True, msg=f"{ex}: kill switch desactivado, entradas reanudadas")
    if a == "vconfig":
        lim = VEX.get(ex, {}); new = {}
        for k, v in (j.get("values") or {}).items():
            if k not in lim: return jsonify(ok=False, msg=f"{k} no editable"), 400
            lo, hi = lim[k]; v = float(v)
            if not lo <= v <= hi: return jsonify(ok=False, msg=f"{k} fuera de rango [{lo}, {hi}]"), 400
            new[k] = int(v) if k in ("max_positions",) else v
        c["exchanges"][ex].update(new); save_cfg(c); return jsonify(ok=True, msg=f"{ex}: guardado {new}")
    if a == "mode":
        m = j.get("mode")
        if m not in ("paper", "live"): return jsonify(ok=False, msg="modo inválido"), 400
        if m == "live":
            if not keys_present(ex): return jsonify(ok=False, msg=f"Faltan claves en keys.env ({', '.join(KEYS[ex])}). Modo real no activado."), 400
            if j.get("confirm") != "REAL": return jsonify(ok=False, msg="Escribe REAL para confirmar"), 400
        c["exchanges"][ex]["mode"] = m; save_cfg(c)
        for p in pid_of(ex): os.kill(p, 15)
        return jsonify(ok=True, msg=f"{ex} cambiado a {m}; reiniciando proceso")
    return jsonify(ok=False, msg="acción desconocida"), 400

LOGIN = """<!doctype html><html lang=es><meta name=viewport content="width=device-width,initial-scale=1"><title>Acceso · Bot Trading</title>
<style>body{background:#0b1020;color:#e6e9f2;font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#141b33;padding:28px;border-radius:14px;width:300px}input,button{width:100%;padding:11px;margin-top:10px;border-radius:8px;border:1px solid #2a3560;background:#0b1020;color:#fff;box-sizing:border-box}
button{background:#3b6cff;border:0;font-weight:600;cursor:pointer}.e{color:#ff6b6b;margin-top:8px}</style>
<form method=post><h2>🔐 Bot Trading</h2><input type=password name=pw placeholder="Contraseña" autofocus><button>Entrar</button><div class=e>{{msg}}</div></form></html>"""
def _page(): return open(os.path.join(D, "dashboard.html")).read()

import live_view; live_view.register(app)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8787, threaded=True)
