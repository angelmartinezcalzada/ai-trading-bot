#!/usr/bin/env python3
"""Diagnóstico en una pantalla (02-nov): ¿está el bot de Solana en REAL, ha operado y, si no, por qué?
Solo lee ficheros locales del bot (logs, estado, libro de operaciones). Nunca abre solana_wallet.json ni imprime claves:
de keys.env solo dice si una clave está puesta. Direcciones y firmas salen acortadas; URLs sin ruta ni parámetros.
Uso:  python3 tools/diagnostico.py [--horas 24] [--root DIR]"""
import os, re, sys, csv, json, time, argparse, subprocess, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_MAX_BYTES = 16 * 1024 * 1024                        # tail of bot_solana.log that is parsed (~1-2 days of a busy log)
GAP_S = 20 * 60                                         # a silence longer than this in the bot log counts as a gap (PC asleep / bot down)
B58 = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,90}\b")
SECRET = re.compile(r"(?i)\b(api[-_]?key|apikey|token|secret|password|passwd|auth)=([^&\s'\",)]+)")
URL = re.compile(r"((?:https?|wss?)://[^/\s'\"?]+)[^\s'\"]*")
PY = r"^\d+ \S*python3?(\.\d+)? "                         # 'PID python3 …' / 'PID /usr/bin/python3.12 …': the process itself, never a wrapper shell
PROCS = [("solana", PY + r"bot\.py --exchange solana( |$)"), ("binance", PY + r"bot\.py --exchange binance( |$)"), ("coinbase", PY + r"bot\.py --exchange coinbase( |$)"),
         ("panel", PY + r"dashboard\.py"), ("insiders", PY + r"insider\.py daemon"), ("WS insiders", PY + r"insider_ws\.py"), ("tendencia", PY + r"trend_spot\.py"),
         ("supervisor", r"^\d+ \S*(bash|sh) \S*run_forever\.sh( |$)"), ("vigilante", r"^\d+ \S*(bash|sh) \S*keepalive\.sh( |$)")]
BLOCK = [("slippage", "deslizamiento"), ("not sellable", "no vendible"), ("impact", "impacto de precio"), ("real round-trip", "coste ida y vuelta"), ("EV ", "EV < 3× coste")]


# ---------------------------------------------------------------- helpers
def short(a): return f"{a[:4]}…{a[-4:]}" if isinstance(a, str) and len(a) > 12 else (a or "?")
def clean(s, n=160):
    """safe to print: URLs reduced to scheme+host, key=value secrets masked, base58 strings (addresses, signatures) shortened"""
    s = URL.sub(r"\1/…", str(s)); s = SECRET.sub(lambda m: m.group(1) + "=***", s); s = B58.sub(lambda m: short(m.group(0)), s)
    return s.replace("\n", " ")[:n]
def num(x, d=2):
    """Spanish number: 1.234,56"""
    try: s = f"{float(x):,.{d}f}"
    except Exception: return "?"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")
def sgn(x, d=1):
    """signed Spanish number (+1,2 / -0,4); '?' when unknown"""
    v = _f(x)
    return "?" if v is None else ("+" if v > 0 else "") + num(v, d)
def ago(sec):
    if sec is None: return "?"
    sec = max(0, int(sec))
    return f"{sec} s" if sec < 120 else f"{sec // 60} min" if sec < 7200 else f"{num(sec / 3600, 1)} h"
def jload(path):
    try: return json.load(open(path, encoding="utf-8"))
    except Exception: return None
def _f(x):
    try: return float(x)
    except Exception: return None
def tail_lines(path, max_bytes=LOG_MAX_BYTES):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); n = f.tell(); f.seek(max(0, n - max_bytes)); b = f.read()
    except Exception: return []
    L = b.decode("utf-8", "replace").splitlines()
    return L[1:] if n > max_bytes else L
def log_ts(line):
    try: return time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S"))
    except Exception: return None
def key_set(root, name):
    """True when keys.env has a NON-empty `name=`; the value is never returned"""
    try:
        for ln in open(os.path.join(root, "keys.env"), encoding="utf-8"):
            if ln.startswith(name + "=") and ln.split("=", 1)[1].strip().strip("'\""): return True
    except Exception: pass
    return False


# ---------------------------------------------------------------- parsers (pure)
def parse_log(lines, since, now=None):
    """counters of the real-money funnel inside [since, now] from bot_solana.log lines ('YYYY-mm-dd HH:MM:SS,mmm LEVEL msg')"""
    d = dict(lines=0, scans=0, passed=0, alt_st=0, alt_score=0, attempts=0, failed=0, kill=0, stop_checks=0, rebased=0, kill_file=0, insider_trig=0, scam=0,
             errors=0, st=collections.Counter(), blocked=collections.Counter(), director=collections.Counter(), last_error=None, last_equity=None,
             real_switch=None, first_t=None, last_t=None, gaps=[])
    prev = None
    for l in lines:
        t = log_ts(l)
        if t is None or t < since: continue
        d["lines"] += 1
        if prev is not None and t - prev > GAP_S: d["gaps"].append((prev, t - prev))
        prev = t; d["first_t"] = d["first_t"] or t; d["last_t"] = t
        if l[24:].startswith("ERROR"): d["errors"] += 1; d["last_error"] = clean(l[30:], 140)
        if "[solana] " not in l: continue
        m = l.split("[solana] ", 1)[1]
        if m.startswith("SCAN "):
            d["scans"] += 1; mm = re.search(r"(\d+) passed all filters", m); d["passed"] += int(mm.group(1)) if mm else 0
        elif m.startswith("ALT gate"):
            if "Solana Tracker" in m: d["alt_st"] += 1
            elif "score" in m: d["alt_score"] += 1
        elif m.startswith("ST check"):
            mm = re.search(r"verdict=(\S+)", m); d["st"][mm.group(1) if mm else "?"] += 1
        elif m.startswith("LIVE buy"):
            if " blocked" in m: d["blocked"][next((es for k, es in BLOCK if k in m), "otro motivo")] += 1
            elif "gate=alt size=" in m: d["attempts"] += 1
            elif " failed" in m: d["failed"] += 1
        elif m.startswith("KILL SWITCH"): d["kill"] += 1
        elif m.startswith("daily stop check"): d["stop_checks"] += 1
        elif m.startswith("day_start rebased") or m.startswith("daily stop cleared"): d["rebased"] += 1
        elif m.startswith("KILL_solana"): d["kill_file"] += 1
        elif m.startswith("INSIDER TRIGGER"): d["insider_trig"] += 1
        elif m.startswith("SCAM block"): d["scam"] += 1
        elif m.startswith("equity="): d["last_equity"] = clean(m, 120)
        elif "SWITCHING TO REAL MONEY" in m: d["real_switch"] = t
        if ": director: " in m: d["director"][re.sub(r"\d+", "N", m.split(": director: ", 1)[1])[:60]] += 1
    if prev is not None and now is not None and now - prev > GAP_S: d["gaps"].append((prev, now - prev))   # silent until now
    return d


def parse_trades(path, since):
    """real ledger (trades_solana_live.csv: time ISO local, side BUY/SELL, pnl net $) -> counts and realized PnL in the window and in total"""
    out = dict(exists=os.path.exists(path), buys=0, sells=0, pnl=0.0, buys_all=0, sells_all=0, pnl_all=0.0, last=None)
    try: rows = list(csv.DictReader(open(path, encoding="utf-8")))
    except Exception: return out
    for r in rows:
        try: t = time.mktime(time.strptime((r.get("time") or "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception: t = None
        side = (r.get("side") or "").strip().upper(); pnl = _f(r.get("pnl")) or 0.0
        if side == "BUY": out["buys_all"] += 1
        elif side == "SELL": out["sells_all"] += 1; out["pnl_all"] += pnl
        if t is not None and t >= since:
            if side == "BUY": out["buys"] += 1
            elif side == "SELL": out["sells"] += 1; out["pnl"] += pnl
    if rows:
        r = rows[-1]
        out["last"] = f"{(r.get('time') or '')[:16].replace('T', ' ')} {clean((r.get('symbol') or '').strip(), 14)} {r.get('side')} pnl {num(_f(r.get('pnl')) or 0, 3)} $"
    return out


def parse_supervisor(lines, since, ex="solana"):
    """supervisor.log ('<date -Is> [solana] start mode=…' / '… exited code N' / '[supervisor] ya hay …') -> restarts in the window"""
    import datetime as _dt
    d = dict(starts=0, exits=0, bad_exits=0, last_code=None, lock_refused=0)
    for l in lines:
        try: t = _dt.datetime.fromisoformat(l.split(" ", 1)[0]).timestamp()
        except Exception: continue
        if t < since: continue
        if f"[{ex}] start" in l: d["starts"] += 1
        elif f"[{ex}] exited code" in l:
            m = re.search(r"exited code (-?\d+)", l); c = int(m.group(1)) if m else None
            d["exits"] += 1; d["last_code"] = c; d["bad_exits"] += 1 if c not in (0, None) else 0
        elif "[supervisor] ya hay" in l: d["lock_refused"] += 1
    return d


def last_crash(lines):
    """last error line of stdout_<ex>.log that is NOT a normal timestamped log line (traceback tail, 'Live refused', singleton exit)"""
    for l in reversed(lines):
        s = l.strip()
        if not s or re.match(r"^\d{4}-\d\d-\d\d[ T]\d\d:", s): continue
        if re.search(r"(Error|Exception|refused|ya corre|No module named|Killed)", s): return clean(s, 160)
    return None


def autostart(root):
    """Windows autostart (tools/autostart.sh writes the .vbs path into .autostart): True / False / None (not WSL)"""
    try: v = open(os.path.join(root, ".autostart"), encoding="utf-8").read().strip()
    except Exception: return False if os.environ.get("WSL_DISTRO_NAME") else None
    return bool(v) and os.path.exists(v)


def count_procs(lines):
    if lines is None: return {k: None for k, _ in PROCS}
    return {k: sum(1 for l in lines if re.search(p, l)) for k, p in PROCS}


def proc_age(lines, key="solana"):
    """seconds since the matching process started (ps etimes), None if unknown: right after a restart the status file is still old"""
    pat = dict(PROCS).get(key)
    pid = next((l.split()[0] for l in (lines or []) if pat and re.search(pat, l)), None)
    if not pid: return None
    try: return int(subprocess.run(["ps", "-o", "etimes=", "-p", pid], capture_output=True, text=True, timeout=5).stdout.strip())
    except Exception: return None


def pgrep():
    try: return subprocess.run(["pgrep", "-af", "python3|run_forever"], capture_output=True, text=True, timeout=5).stdout.splitlines()
    except Exception: return None


# ---------------------------------------------------------------- gather + verdict
def gather(root=ROOT, hours=24, now=None, procs=None):
    now = now or time.time(); since = now - hours * 3600; P = lambda *a: os.path.join(root, *a)
    st = jload(P("status_solana.json")) or {}
    stl = jload(P("state_solana_live.json")) or {}
    plines = pgrep() if procs is None else procs
    D = dict(now=now, hours=hours, root=root, procs=count_procs(plines), sol_age=proc_age(plines) if procs is None else None, status=st,
             status_age=(now - st["ts"]) if isinstance(st.get("ts"), (int, float)) else None, state=stl,
             wallet_file=os.path.exists(P("solana_wallet.json")), kill_file=os.path.exists(P("KILL_solana")),
             stop_file=os.path.exists(P("STOP")) or os.path.exists(P("STOP_solana")), st_key=key_set(root, "SOLANATRACKER_API_KEY"),
             log=parse_log(tail_lines(P("bot_solana.log")), since, now), trades=parse_trades(P("trades_solana_live.csv"), since),
             sup=parse_supervisor(tail_lines(P("supervisor.log"), 2 * 1024 * 1024), since), crash=last_crash(tail_lines(P("stdout_solana.log"), 256 * 1024)),
             autostart=autostart(root))
    try:
        sys.path.insert(0, root); import solanatracker as _st; cap, res = _st.DAILY_CAP, _st.BOT_RESERVE
    except Exception: cap, res = 300, 200
    b = jload(P("data", "st_budget.json")) or {}; today = time.strftime("%Y-%m-%d", time.localtime(now))
    used = int(b.get("n") or 0) if b.get("day") == today else 0
    D["st_budget"] = dict(used=used, cap=cap, daemon=int(b.get("nd") or 0) if b.get("day") == today else 0, insider=int(b.get("ni") or 0) if b.get("day") == today else 0)
    D["st_exhausted"] = used >= cap
    D["brain"] = jload(P("brain_state.json")) or jload(P("data", "brain_state.json")) or {}
    D["director"] = jload(P("director_state.json")) or {}
    D["context"] = jload(P("data", "context_now.json")) or {}
    D["rank"] = jload(P("insider_rank.json")) or {}
    D["insider"] = jload(P("insider_status.json")) or {}
    return D


def main_reason(D):
    L = D["log"]
    if L["scans"] == 0: return "no hay escaneos en el log de estas horas (¿bot parado o PC suspendido?)"
    if not D["st_key"] and L["alt_st"]: return f"falta la clave de Solana Tracker en keys.env: {L['alt_st']} candidatos aptos descartados por veredicto neutral"
    c = []
    if L["alt_st"]: c.append((L["alt_st"], f"Solana Tracker sin veredicto en {L['alt_st']} candidatos aptos" + (" (cupo diario agotado)" if D["st_exhausted"] else "")))
    if L["alt_score"]: c.append((L["alt_score"], f"puntuación por debajo del mínimo de la puerta ALT en {L['alt_score']} candidatos"))
    c += [(n, f"compra bloqueada por {why} ({n} veces)") for why, n in L["blocked"].items()]
    c += [(n, f"Director: {why} ({n} veces)") for why, n in L["director"].items()]
    if not c:
        if L["passed"] == 0: return f"ningún token pasó todos los filtros en {num(L['scans'], 0)} escaneos (los vetos anti-scam y de calidad son estrictos a propósito)"
        return "hubo candidatos aptos pero ninguno llegó a la orden; ver bot_solana.log"
    return max(c, key=lambda x: x[0])[1]


def verdict(D):
    v = []; pr = D["procs"]; sol = pr.get("solana"); st = D["status"]; H = D["hours"]
    sup = D.get("sup") or {}
    if sol == 0 and sup.get("bad_exits"):
        v.append(f"✖ El bot de Solana se cae al arrancar: el supervisor lo relanzó {sup['bad_exits']} veces (último código {sup.get('last_code')})"
                 + (f"; último error: {D['crash']}" if D.get("crash") else "") + ".")
    elif sol == 0: v.append("✖ El bot de Solana NO está corriendo: relánzalo con el comando de instalación (wsl_bootstrap.sh).")
    if D.get("autostart") is False:
        v.append("⚠ Sin arranque automático: en Windows el bot muere al cerrar la ventana de Ubuntu. El comando de instalación lo instala (tools/autostart.sh).")
    elif D.get("autostart") and pr.get("vigilante") == 0:
        v.append("⚠ El vigilante oculto no corre: el bot se parará al cerrar la ventana de Ubuntu. Arreglo: tools/autostart.sh start (o cerrar sesión en Windows y volver a entrar).")
    elif sol and sol > 1: v.append(f"⚠ Hay {sol} copias del bot de Solana (debería haber 1): relanza con el comando de instalación.")
    if sol and D["status_age"] is not None and D["status_age"] > 300:
        if D.get("sol_age") is not None and D["sol_age"] < 900 and D["status_age"] > D["sol_age"]:
            v.append(f"El bot de Solana arrancó hace {ago(D['sol_age'])}: está haciendo su primer escaneo (puede tardar unos minutos); repite el diagnóstico en 10 min.")
        else: v.append(f"⚠ El bot corre pero su estado no se actualiza desde hace {ago(D['status_age'])} (posible cuelgue; el operador lo reinicia cada hora).")
    if D["stop_file"]: v.append("⚠ Hay un fichero STOP o STOP_solana: el supervisor no relanza el bot de Solana.")
    if not st:
        v.append("Solana sin estado: el bot no ha arrancado todavía (no hay status_solana.json)" + ("" if D["wallet_file"] else "; además falta solana_wallet.json, sin él solo operaría en papel") + "."); return v
    if st.get("mode") != "live":
        why = ("no hay solana_wallet.json" if not D["wallet_file"] else "KILL_solana impide pasar a real" if D["kill_file"] else "el wallet aún no se ha leído o tiene menos de 0,05 SOL")
        v.append(f"Solana en PAPEL (no mueve dinero real): {why}."); return v
    T = D["trades"]
    if st.get("halted") or D["kill_file"]:
        v.append("⛔ En REAL pero sin compras: " + ("fichero KILL_solana presente." if D["kill_file"] else "saltó el stop diario del 5 % (se levanta a medianoche)."))
    if T["buys"] or T["sells"]:
        v.append(f"✅ En REAL y operando: {T['buys']} compras y {T['sells']} ventas en {H} h, PnL realizado {sgn(T['pnl'], 2)} $.")
    elif not (st.get("halted") or D["kill_file"]):
        v.append(f"En REAL, 0 compras en {H} h. Motivo principal: {main_reason(D)}.")
    big = [g for g in D["log"]["gaps"] if g[1] >= 3600]
    if big: v.append(f"⚠ El bot estuvo sin actividad {num(sum(g[1] for g in big) / 3600, 1)} h en estas {H} h (¿PC suspendido o apagado?).")
    return v


def report(D):
    st, L, T, now, H = D["status"], D["log"], D["trades"], D["now"], D["hours"]
    o = [f"== Diagnóstico del bot · {time.strftime('%d/%m %H:%M', time.localtime(now))} · últimas {H} h", "Veredicto:"] + [f"  {x}" for x in verdict(D)]
    pr = D["procs"]
    sup = D.get("sup") or {}
    o.append(f"Arranque automático: {'sí' if D.get('autostart') else 'NO' if D.get('autostart') is False else 'n/a (no es WSL)'} · supervisor {H} h: {sup.get('starts', 0)} arranques del bot, {sup.get('bad_exits', 0)} caídas con error"
             + (f" · último error: {D['crash']}" if D.get("crash") and sup.get("bad_exits") else ""))
    o.append("Procesos: " + (" · ".join(f"{k} {'✓' if n else '✖'}" + (f"×{n}" if n and n > 1 and k not in ("supervisor", "vigilante") else "") for k, n in pr.items()) if pr.get("solana") is not None else "no se pudo consultar (pgrep)"))
    w = st.get("wallet") if isinstance(st.get("wallet"), dict) else {}
    o.append(f"Solana: modo {'REAL' if st.get('mode') == 'live' else 'PAPEL' if st else '?'} · patrimonio {num(st.get('equity'))} $ (efectivo {num(st.get('cash'))} $) · hoy {sgn(st.get('day_pnl_pct'), 1)} %"
             + (f" · wallet {short(w.get('addr'))} {num(w.get('sol'), 4)} SOL" if w else "") + f" · estado hace {ago(D['status_age'])}" + (" · wallet: fichero presente" if D["wallet_file"] else " · sin solana_wallet.json"))
    sl = D["state"]
    o.append(f"Riesgo: stop diario {'SALTADO' if (st.get('halted') or sl.get('halted')) else 'no saltado'}" + (f" · base del día {num(sl.get('day_start'))} $" if sl.get("day_start") is not None else "") + f" · posiciones abiertas {len(st.get('positions') or sl.get('pos') or [])}"
             + f" · KILL_solana {'SÍ' if D['kill_file'] else 'no'} · STOP {'SÍ' if D['stop_file'] else 'no'}")
    o.append(f"Operaciones reales: {H} h: {T['buys']} compras / {T['sells']} ventas / PnL {sgn(T['pnl'], 2)} $ · total: {T['buys_all']} / {T['sells_all']} / PnL {sgn(T['pnl_all'], 2)} $"
             + (f" · última: {T['last']}" if T["last"] else " · sin libro real (trades_solana_live.csv)"))
    bl = ", ".join(f"{k} {n}" for k, n in L["blocked"].most_common()) or "ninguno"
    o.append(f"Embudo {H} h: {num(L['scans'], 0)} escaneos · {L['passed']} aptos (pasan todos los filtros) · sin veredicto ST {L['alt_st']} · puntuación ALT baja {L['alt_score']}"
             + f" · bloqueos {bl} · intentos de compra {L['attempts']} · fallidos {L['failed']} · disparos insider {L['insider_trig']} · bloqueos anti-scam {L['scam']}")
    sb = D["st_budget"]; sv = ", ".join(f"{k} {n}" for k, n in L["st"].most_common()) or "ninguno"
    o.append(f"Solana Tracker: clave {'sí' if D['st_key'] else 'NO (sin ella no hay compras reales)'} · hoy {sb['used']}/{sb['cap']} consultas (sombra {sb['daemon']}, insiders {sb['insider']}) · veredictos {H} h: {sv}")
    ds = D["director"]
    if ds:
        pl = ", ".join(f"{k}={v}" for k, v in (ds.get("plays") or {}).items()) or "?"
        rg = {k: v for k, v in ds["regime_gate"].items() if isinstance(v, list)} if isinstance(ds.get("regime_gate"), dict) else {}
        closed = (((ds.get("evidence") or {}).get("regime") or {}).get("closed") or {}) if isinstance((ds.get("evidence") or {}).get("regime"), dict) else {}
        o.append(f"Director: {'en sombra (calcula, no manda)' if ds.get('shadow') else 'MANDANDO (solo endurece)'} · jugadas {pl} · horas abiertas {len(ds.get('windows') or []) if isinstance(ds.get('windows'), list) else 24}/24"
                 + f" · régimen: {sum(len(v) for v in closed.values()) if closed else 0} valores cerrados" + (f" en {len(rg)} claves" if rg else " (sin puerta)"))
        if D["log"]["director"]: o.append("  bloqueos del Director: " + ", ".join(f"{k} ({n})" for k, n in D["log"]["director"].most_common(3)))
    else: o.append("Director: sin estado todavía")
    b = D["brain"]
    if b:
        oos = b.get("oos") if isinstance(b.get("oos"), dict) else {}
        o.append(f"Cerebro: {'ACTIVO' if b.get('active') else 'en sombra (no decide)'} · {b.get('n_labelled', '?')} etiquetas · archivo {b.get('archive_n', '?')} · modelo {b.get('model_choice', 'beta')}"
                 + f" · fuera de muestra: {oos.get('brain_trades', '?')} operaciones del modelo, regla base {oos.get('baseline_avg_ret_%', '?')} %/op")
    else: o.append("Cerebro: sin estado todavía")
    c = D["context"]
    if c:
        rg = c.get("regime") or {}; so = c.get("sol") or {}; nw = c.get("news") or {}
        o.append(f"Contexto: hace {ago(now - c['ts']) if isinstance(c.get('ts'), (int, float)) else '?'} · SOL {sgn(so.get('r24h'), 1)} % 24 h · BTC {'on' if rg.get('btc_on') else 'off' if rg.get('btc_on') is False else '?'}"
                 + f" · F&G {nw.get('fng', '?')} · riesgo-off {'sí' if rg.get('risk_off') else 'no' if rg.get('risk_off') is False else '?'} · calor {rg.get('heat') or '?'} · {len(c.get('stale') or [])} campos sin dato")
    else: o.append("Contexto: sin data/context_now.json todavía (context.py corre cada hora)")
    r, ins = D["rank"], D["insider"]
    if r or ins:
        tr = r.get("tiers") or {}
        o.append("Insiders: " + (f"ranking hace {ago(now - r['t'])} (elite {tr.get('elite', 0)} · good {tr.get('good', 0)} · watch {tr.get('watch', 0)})" if isinstance(r.get("t"), (int, float)) else "sin ranking todavía")
                 + (f" · siguiendo {ins.get('tracked', '?')} wallets · estado hace {ago(now - ins['ts'])}" if isinstance(ins.get("ts"), (int, float)) else ""))
    gaps = [g for g in L["gaps"]]
    o.append(f"Actividad: {num(L['lines'], 0)} líneas de log en {H} h" + (f" · {len(gaps)} huecos > {GAP_S // 60} min (el mayor {num(max(g[1] for g in gaps) / 3600, 1)} h)" if gaps else " · sin huecos"))
    o.append(f"Errores {H} h: {L['errors']}" + (f" · último: {L['last_error']}" if L["last_error"] else ""))
    return "\n".join(o)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Diagnóstico del bot (solo lectura)")
    ap.add_argument("--horas", type=float, default=24); ap.add_argument("--root", default=ROOT)
    a = ap.parse_args(argv)
    print(report(gather(a.root, a.horas)))


if __name__ == "__main__":
    main()
