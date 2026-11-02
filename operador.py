#!/usr/bin/env python3
"""operador.py (no "operator": ese nombre es un módulo de la librería estándar). Operador automático: el "director financiero" que antes era una persona o una IA externa, ahora código.

Cada hora (run_forever.sh) hace lo que hacía la revisión horaria: mira la salud de cada proceso, el patrimonio, los escaneos,
los errores, el Director, el cerebro, el riesgo de Hyperliquid, el contexto de mercado (context.py: data/context_now.json y
data/context.jsonl, leídos a través de dash_data), el ranking de insiders y el estado de las cuentas de token; lo escribe en DIARIO.md (diario local de la máquina, fuera de git) con el mismo formato que las revisiones
anteriores de DECISIONS.md; guarda operator_state.json para el panel; y emite alerts.jsonl (y, si existe
la variable ALERT_CMD, ejecuta ese comando con el texto de la alerta: webhook, Telegram, lo que sea).

Acciones que toma SOLO (todas reversibles y dentro de las reglas del dueño):
  - close_atas: cierra las cuentas de token vacías del wallet real (rent 0,00204 SOL cada una vuelve al wallet), como mucho cada 6 h.
  - restart_hung: si un proceso sigue vivo pero su status lleva > 10 min sin escribirse, le manda SIGTERM (run_forever lo relanza);
    una vez por hora por proceso, nunca si hay STOP_<ex>.
  - director_refresh: si director_state.json falta o tiene > 2 h, recalcula el Director (director.compute) con la config base.
  - rotate_logs: recorta los logs de más de 50 MB a sus últimos 5 MB.
Lo que NUNCA hace: relajar vetos, tamaños o stops; cambiar papel↔real; activar el pump real; tocar config.json; mover fondos.
Una vez al día (a partir de las 08:00) añade el informe diario con las decisiones que quedan para Àngel."""
import os, sys, json, time, signal, subprocess, datetime as dt, logging

log = logging.getLogger("operator")
STATE, ALERTS, LOGF, DIARY = "operator_state.json", "alerts.jsonl", "operator_log.jsonl", "DIARIO.md"
HUNG_S, RESTART_EVERY_S, ATA_EVERY_S, DIRECTOR_MAX_AGE_S = 600, 3600, 6 * 3600, 2 * 3600
LOG_ROTATE_BYTES, LOG_KEEP_BYTES, ALERT_DEDUPE_S, DAILY_HOUR = 50_000_000, 5_000_000, 6 * 3600, 8


def _tz_now(now=None):
    now = now or time.time()
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.fromtimestamp(now, ZoneInfo("Europe/Madrid")), "Madrid"
    except Exception: return dt.datetime.fromtimestamp(now), "local"


def _atomic_json(path, obj):
    tmp = path + ".tmp"; json.dump(obj, open(tmp, "w"), indent=1, default=str); os.replace(tmp, path)


def _load(path, default):
    try: return json.load(open(path))
    except Exception: return default


# ---------------------------------------------------------------- review (pure)
def market_line(C):
    """One diary line from the dash_data `context` section (data/context_now.json): SOL/BTC 24 h, F&G, risk-off, heat, launches/h,
    breadth. Pure and never invents: a missing file is 'sin contexto', a missing field is '?', a stale file is prefixed with its age."""
    if not C.get("available"): return f"sin contexto ({C.get('error') or 'data/context_now.json ausente'})"
    sol, btc, nw, mk, br, rg = (C.get(k) if isinstance(C.get(k), dict) else {} for k in ("sol", "btc", "news", "market", "breadth", "regime"))
    N = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
    P = lambda x: f"{x:+.1f} %" if N(x) else "?"
    yn = lambda b: "sí" if b is True else "no" if b is False else "?"
    ro = nw.get("risk_off") if nw.get("risk_off") is not None else rg.get("risk_off")
    ne, nu = br.get("n_entry"), br.get("n_universe")
    amp = f"{ne if N(ne) else '?'}/{nu if N(nu) else '?'}" + (f" ({100 * ne / nu:.0f} %)" if N(ne) and N(nu) and nu > 0 else "")
    parts = [f"SOL 24 h {P(sol.get('r24h'))} ({rg.get('sol_trend') or '?'})",
             f"BTC 24 h {P(btc.get('r24h'))} ({'on' if rg.get('btc_on') is True else 'off' if rg.get('btc_on') is False else '?'}{', ' + btc['regime'] if btc.get('regime') else ''})",
             f"F&G {nw.get('fng') if N(nw.get('fng')) else '?'}", f"riesgo-off {yn(ro)}",
             f"calor {mk.get('heat') or '?'}" + (f" (×{mk['heat_ratio']:.2f})" if N(mk.get("heat_ratio")) else ""),
             f"lanzamientos/h {mk.get('new_pools_1h') if N(mk.get('new_pools_1h')) else '?'}" + (f", graduaciones {mk['graduations_1h']}" if N(mk.get("graduations_1h")) else ""),
             f"amplitud {amp}"]
    s = " · ".join(parts)
    if not C.get("fresh"): s = f"obsoleto ({(C.get('age_s') or 0) / 3600:.1f} h): " + s
    if C.get("stale"): s += " · sin calcular: " + ", ".join(str(x) for x in C["stale"][:6])
    return s


def review(ov, cfg, now):
    """findings [{level: ok|info|warn|crit, code, msg}] + a summary dict from a dash_data overview. No side effects."""
    F = []; add = lambda level, code, msg: F.append({"level": level, "code": code, "msg": msg})
    H = (ov.get("health") or {}).get("exchanges") or {}; meta = ov.get("meta") or {}
    for ex, e in H.items():
        mode = ((meta.get("exchanges") or {}).get(ex) or {}).get("mode", "paper")
        if e.get("stopped"): add("info", f"{ex}_stopped", f"{ex} parado a propósito (STOP_{ex})"); continue
        if not e.get("pids"): add("crit", f"{ex}_down", f"{ex} ({mode}) sin proceso: run_forever debería relanzarlo; si no, ./run_forever.sh")
        elif e.get("status_age_s") is not None and e["status_age_s"] > HUNG_S: add("warn", f"{ex}_hung", f"{ex} vivo pero su status lleva {e['status_age_s']/60:.0f} min sin escribirse")
        if e.get("killed"): add("warn", f"{ex}_killed", f"{ex} con KILL_{ex}: no abre entradas y cierra posiciones")
    if ov.get("health", {}).get("available") and not (ov["health"].get("insider_pid")): add("warn", "insider_down", "insider.py sin proceso (inteligencia de wallets parada)")
    S = ov.get("solana") or {}; br = S.get("brain") or {}   # brain/limits can exist (files) while the status does not: never reference them unbound
    if S.get("available"):
        if not S.get("fresh"): add("warn", "solana_stale", f"status_solana.json obsoleto ({(S.get('age_s') or 0)/60:.0f} min)")
        if S.get("halted"): add("warn", "solana_halted", "Solana en halt (stop diario o kill switch): sin entradas hasta el día siguiente o override")
        lim = S.get("limits") or {}; dd = lim.get("daily_max_drawdown_pct"); dpp = S.get("day_pnl_pct")
        if isinstance(dd, (int, float)) and isinstance(dpp, (int, float)) and dpp <= -dd * 100 * 0.8 and not S.get("halted"): add("warn", "solana_near_stop", f"Solana hoy {dpp:+.2f} %: cerca del stop diario (−{dd*100:.1f} %)")
        w = S.get("wallet") or {}
        if S.get("mode") == "live" and isinstance(w.get("sol"), (int, float)) and isinstance(S.get("live_min_sol"), (int, float)) and w["sol"] < S["live_min_sol"]:
            add("crit", "sol_low", f"SOL en wallet {w['sol']:.4f} < mínimo {S['live_min_sol']}: no puede pagar comisiones ni abrir")
        sc = S.get("scan") or {}
        if sc.get("available"):
            if (sc.get("age_s") or 0) > 900: add("warn", "scan_gap", f"último escaneo hace {(sc.get('age_s') or 0)/60:.0f} min (> 15)")
            pf = sc.get("secs")
            if isinstance(pf, (int, float)) and pf > 300: add("warn", "scan_slow", f"escaneo de {pf:.0f} s (RugCheck {sc.get('rc_fetched')}/{sc.get('rc_needed')}, {sc.get('rc_past_budget')} fuera de presupuesto)")
        for p in S.get("positions") or []:
            if (p.get("sellfail") or 0) >= 3 or (p.get("noroute") or 0) >= 5: add("warn", f"pos_stuck_{p.get('sym')}", f"posición {p.get('sym')} con {p.get('sellfail', 0)} ventas fallidas / {p.get('noroute', 0)} sin ruta")
        if br.get("available") and not br.get("fresh"): add("warn", "brain_stale", f"cerebro sin reentrenar desde {br.get('updated')}")
        k = S.get("kpi_30d") or {}
        if k.get("available") and (k.get("n") or 0) >= 20 and isinstance(k.get("profit_factor"), (int, float)) and k["profit_factor"] < 1:
            add("warn", "solana_pf_lt_1", f"Solana 30 d: PF {k['profit_factor']:.2f} con {k['n']} ventas → proponer a Àngel pasar a papel (decisión suya, el operador no la toma)")
    A = ov.get("activity") or {}
    errs = [x for x in (A.get("items") or []) if x.get("kind") == "error" and isinstance(x.get("ts"), (int, float)) and now - x["ts"] < 3600]
    if errs: add("warn", "errors_1h", f"{len(errs)} error(es) en logs la última hora; último: {errs[0].get('ex')} {errs[0].get('msg', '')[:120]}")
    I = ov.get("insider") or {}
    if I.get("available") and not I.get("fresh"): add("warn", "insider_stale", f"insider_status.json obsoleto ({(I.get('age_s') or 0)/60:.0f} min)")
    if I.get("available"):   # insider_rank.json (insider_rank.py): the wallet ranking the panel table and the convergence tiers come from
        rk = I.get("rank") or {}
        if not rk.get("available"): add("info", "insider_rank_stale", "sin insider_rank.json: insider_rank.py aún no ha puntuado las wallets (tabla de insiders vacía)")
        elif not rk.get("fresh"): add("info", "insider_rank_stale", f"ranking de insiders obsoleto ({(rk.get('age_s') or 0)/3600:.1f} h; insider_rank.py debería correr cada hora)")
    if br.get("available"):   # brain_state.json written by an older brain.py than the one on disk: the state may not match the code
        if not br.get("code_version"): add("info", "brain_state_older_than_code", "brain_state.json sin code_version: estado de una versión anterior del cerebro (se regenera en el próximo reentreno)")
        elif isinstance(br.get("code_newer_s"), (int, float)) and br["code_newer_s"] > 86400:
            add("info", "brain_state_older_than_code", f"brain.py es {br['code_newer_s']/86400:.1f} d más nuevo que el último reentreno ({br.get('updated')}): el estado puede no corresponder al código")
    # market context (context.py via dash_data): stale -> warn (alerts, deduped 6 h like every code); the rest are notes, never alerts
    C = ov.get("context") or {}
    if not C.get("available"): add("warn", "context_stale", "sin contexto de mercado: data/context_now.json ausente o ilegible (context.py no ha corrido)")
    elif not C.get("fresh"): add("warn", "context_stale", f"contexto de mercado obsoleto ({(C.get('age_s') or 0)/3600:.1f} h): el memebot decide sin régimen actualizado")
    else:
        n6, k6 = C.get("riskoff_6h_n"), C.get("riskoff_6h")
        if isinstance(n6, int) and n6 >= 6 and k6 == n6: add("info", "news_riskoff_6h", f"riesgo-off por noticias sostenido en las últimas {n6} filas horarias (el memebot sube el umbral +10 y reduce el tamaño ×0,5)")
        mk = C.get("market") or {}; np_ = mk.get("new_pools_1h")
        if isinstance(np_, int) and not isinstance(np_, bool) and np_ == 0 and mk.get("heat") == "cold": add("info", "market_dead", "mercado muerto: 0 pools nuevos en la última hora y calor 'cold' (pocas oportunidades; no es un fallo)")
    D = ov.get("director") or {}
    if not D.get("available"): add("info", "director_missing", "sin director_state.json: el Director aún no ha corrido (se recalcula)")
    elif not D.get("fresh"): add("warn", "director_stale", f"director_state.json obsoleto ({(D.get('age_s') or 0)/3600:.1f} h): se recalcula")
    elif D.get("shadow"): add("info", "director_shadow", "Director en sombra (primeras 24 h): calcula y registra, no manda")
    HL = ov.get("hl") or {}; rk = (HL.get("risk") or {}) if HL.get("available") else {}
    if rk.get("status") in ("degraded", "partial"): add("info", "hl_risk_degraded", f"contexto Coinversa {rk.get('status')} (ok {rk.get('ok')}, fallos {rk.get('failed')})")
    CX = (ov.get("cex") or {}).get("exchanges") or {}
    for ex, e in CX.items():
        if e.get("available") and e.get("no_cash"): add("warn", f"{ex}_no_cash", f"{ex} sin efectivo para operar")
    if not F: add("ok", "all_ok", "sin incidencias")
    # summary lines (same shape as the hourly reviews in DECISIONS.md)
    legs = []
    for ex, e in CX.items():
        if e.get("available"): legs.append(f"{ex} {e.get('mode', '?')} {e.get('equity'):.2f} $ ({(e.get('day_pnl_pct') or 0):+.2f} % hoy{', halt' if e.get('halted') else ''})" if isinstance(e.get("equity"), (int, float)) else f"{ex} sin status")
    if S.get("available") and isinstance(S.get("equity"), (int, float)):
        w = S.get("wallet") or {}
        legs.append(f"Solana {'REAL' if S.get('mode') == 'live' else 'papel'} {S['equity']:.2f} $ ({(S.get('day_pnl_pct') or 0):+.2f} % hoy), {len(S.get('positions') or [])} abiertas, efectivo {S.get('cash') or 0:.2f} $"
                    + (f", wallet {w.get('sol'):.3f} SOL" if isinstance(w.get("sol"), (int, float)) else "") + (f", SOL {S.get('sol_usd'):.2f} $" if isinstance(S.get("sol_usd"), (int, float)) else ""))
    dp = S.get("daily_pnl") or {}; today = (dp.get("days") or [{}])[-1] if dp.get("available") else {}
    fu = S.get("funnel") or {}; sc = S.get("scan") or {}
    summary = {"legs": legs, "today": {"n": today.get("n", 0), "pnl": today.get("pnl", 0.0), "wins": today.get("wins", 0)},
               "scan": (f"{sc.get('ok')}/{sc.get('total')} con liquidez → eval {sc.get('eval')}, rugcheck {sc.get('rc_fetched')}/{sc.get('rc_needed')} en {sc.get('secs')} s" if sc.get("available") and sc.get("ok") is not None else "sin línea de escaneo"),
               "funnel": (f"{fu.get('rows')} candidatos, {fu.get('passed')} pasan; vetos: " + ", ".join(f"{r['reason']} {r['n']}" for r in (fu.get('by_fail') or [])[:4])) if fu.get("available") else "sin embudo",
               "director": (f"{'sombra' if D.get('shadow') else 'manda'}: jugadas {D.get('plays')}, score ≥ {D.get('min_score_eff')}, EV ≥ {100*(D.get('ev_min_eff') or 0):.2f} %, tamaño {(D.get('size_policy') or {}).get('target_usd')} $, {len(D.get('windows') or [])}/24 h, máx {D.get('max_trades_day')} op/día") if D.get("available") else "sin estado",
               "brain": (f"{'activo' if br.get('active') else 'sombra'}, modelo {br.get('model_choice') or 'beta'}" + (f" ({br['code_version']})" if br.get("code_version") else "")
                         + f", {br.get('n_labelled')} etiquetadas, OOS {br.get('oos')}") if (S.get("brain") or {}).get("available") else "sin estado",
               "copytrade": (f"{(ov.get('copytrade') or {}).get('closed')} cierres, {(ov.get('copytrade') or {}).get('pnl')} $ papel") if (ov.get("copytrade") or {}).get("available") else "sin estado",
               "hl": (f"paper {((HL.get('paper') or {}).get('deployment_id') or '?')}, riesgo Coinversa {rk.get('status') or 'sin fichero'}") if HL.get("available") else "sin ficheros",
               "market": market_line(C)}
    return F, summary


# ---------------------------------------------------------------- actions (side effects, all gated)
def act(root, ov, findings, cfg, state, now, dry_run=False):
    """returns [{action, detail}] of what was done (or would be, with dry_run)"""
    A = []; done = lambda a, d: A.append({"action": a, "detail": d, "dry_run": dry_run})
    sol = (cfg.get("exchanges") or {}).get("solana") or {}; S = ov.get("solana") or {}
    # 1) rent recovery: empty token accounts of the REAL wallet, at most every ATA_EVERY_S
    if sol.get("ata_autoclose", True) and S.get("available") and S.get("mode") == "live" and os.path.exists(os.path.join(root, "solana_wallet.json")) and now - (state.get("last_ata") or 0) > ATA_EVERY_S:
        try:
            if dry_run: done("close_atas", "dry run: se cerrarían las cuentas de token vacías")
            else:
                sys.path.insert(0, root); import live_sol
                r = live_sol.close_empty_atas(dry_run=False, skip={p.get("mint") for p in (S.get("positions") or []) if p.get("mint")})
                state["last_ata"] = now; done("close_atas", f"{r['closed']}/{r['found']} cuentas cerradas, SOL recuperado {r['sol_recovered']}, fallos {len(r['failed'])}")
                if r["found"]:
                    os.makedirs(os.path.join(root, "research"), exist_ok=True)
                    with open(os.path.join(root, "research", "ata_close.jsonl"), "a") as f: f.write(json.dumps({"t": now, **{k: v for k, v in r.items() if k != "mints"}}) + "\n")
        except Exception as e: done("close_atas_failed", str(e)[:160])
    # 2) hung process: alive but silent > HUNG_S -> SIGTERM (run_forever relaunches); once per hour per leg; never with STOP_<ex>
    for f in findings:
        if f["code"].endswith("_hung"):
            ex = f["code"][:-5]; e = ((ov.get("health") or {}).get("exchanges") or {}).get(ex) or {}
            last = (state.get("last_restart") or {}).get(ex, 0)
            if e.get("stopped") or now - last < RESTART_EVERY_S or not e.get("pids"): continue
            if dry_run: done("restart_hung", f"dry run: SIGTERM a {ex} pids {e['pids']}"); continue
            for pid in e["pids"]:
                try: os.kill(pid, signal.SIGTERM)
                except Exception as ex_: done("restart_failed", f"{ex} pid {pid}: {ex_}")
            state.setdefault("last_restart", {})[ex] = now; done("restart_hung", f"SIGTERM a {ex} (pids {e['pids']}); run_forever lo relanza")
    # 3) director stale/missing -> recompute with the base config and the real status
    D = ov.get("director") or {}
    if not D.get("available") or (D.get("age_s") or 0) > DIRECTOR_MAX_AGE_S:
        try:
            if dry_run: done("director_refresh", "dry run: se recalcularía director_state.json")
            else:
                sys.path.insert(0, root); import director
                eq = S.get("equity") if isinstance(S.get("equity"), (int, float)) else float(sol.get("starting_equity", 48) or 48)
                su = S.get("sol_usd") if isinstance(S.get("sol_usd"), (int, float)) else 100.0
                st = director.compute(root, dict(sol), eq, su, now=now, data=None)
                done("director_refresh", director.summary_line(st))
        except Exception as e: done("director_refresh_failed", str(e)[:160])
    # 4) log rotation
    for fn in os.listdir(root):
        if (fn.startswith("bot_") or fn.startswith("stdout_") or fn in ("supervisor.log", "tunnel.log")) and fn.endswith(".log"):
            p = os.path.join(root, fn)
            try: sz = os.path.getsize(p)
            except OSError: continue
            if sz > LOG_ROTATE_BYTES:
                if dry_run: done("rotate_logs", f"dry run: {fn} {sz/1e6:.0f} MB → últimos {LOG_KEEP_BYTES/1e6:.0f} MB"); continue
                with open(p, "rb") as fh: fh.seek(-LOG_KEEP_BYTES, 2); tail = fh.read()
                with open(p, "wb") as fh: fh.write(tail)
                done("rotate_logs", f"{fn}: {sz/1e6:.0f} MB → {LOG_KEEP_BYTES/1e6:.0f} MB")
    return A


# ---------------------------------------------------------------- writing
def entry_text(findings, summary, actions, now, daily=None):
    t, tz = _tz_now(now); lines = [f"## {t.strftime('%Y-%m-%d %H:%M')} ({tz}) — revisión horaria{' + informe diario' if daily else ''} (operador automático)"]
    sal = [f for f in findings if f["level"] in ("crit", "warn")]
    lines.append("- Salud: " + ("; ".join(f"{'⛔' if f['level'] == 'crit' else '⚠'} {f['msg']}" for f in sal) if sal else "todos los procesos vivos y con status fresco; sin errores nuevos en logs"))
    if summary.get("legs"): lines.append("- Equity: " + " · ".join(summary["legs"]) + f". Hoy Solana: {summary['today']['n']} cierres, {summary['today']['pnl']:+.3f} $, {summary['today']['wins']} ganados.")
    lines.append(f"- Escaneo: {summary.get('scan')}. Embudo: {summary.get('funnel')}.")
    if summary.get("market"): lines.append(f"- Mercado: {summary['market']}.")
    lines.append(f"- Director: {summary.get('director')}. Cerebro: {summary.get('brain')}.")
    lines.append(f"- Copytrade papel: {summary.get('copytrade')}. Hyperliquid: {summary.get('hl')}.")
    info = [f["msg"] for f in findings if f["level"] == "info"]
    if info: lines.append("- Notas: " + "; ".join(info))
    lines.append("- Acciones: " + ("; ".join(f"{a['action']}: {a['detail']}" for a in actions) if actions else "ninguna"))
    if daily: lines.extend(daily)
    return "\n".join(lines) + "\n"


def daily_lines(root, ov, now):
    """the daily report: 24 h by leg, rent recovered, director changes, brain, and the decisions that remain Àngel's"""
    S = ov.get("solana") or {}; k = S.get("kpi_30d") or {}; dp = S.get("daily_pnl") or {}
    d24 = (dp.get("days") or [])[-1:] if dp.get("available") else []
    L = [f"- Solana 24 h: {d24[0]['n'] if d24 else 0} cierres, {d24[0]['pnl'] if d24 else 0:+.3f} $; 30 d: n={k.get('n')} PF={k.get('profit_factor')} acierto={k.get('win_rate')} esperanza={k.get('expectancy')} $/op comisiones={k.get('fees')} $"]
    rec = 0.0; n_close = 0
    try:
        for l in open(os.path.join(root, "research", "ata_close.jsonl")):
            r = json.loads(l)
            if now - (r.get("t") or 0) < 86400: rec += float(r.get("sol_recovered") or 0); n_close += int(r.get("closed") or 0)
    except Exception: pass
    L.append(f"- Rent de ATAs 24 h: {n_close} cuentas cerradas, {rec:+.5f} SOL de vuelta al wallet")
    D = ov.get("director") or {}; ch = [x for x in (D.get("log") or []) if isinstance(x.get("t"), (int, float)) and now - x["t"] < 86400 and x.get("changes")]
    L.append(f"- Director 24 h: {len(ch)} cambios de estado; ahora {D.get('plays')} · {'sombra' if D.get('shadow') else 'manda'}")
    br = S.get("brain") or {}
    L.append(f"- Cerebro: modelo {br.get('model_choice') or 'beta'}" + (f" ({br['code_version']})" if br.get("code_version") else "") + f", activo={br.get('active')}, OOS {br.get('oos')}")
    C = ov.get("context") or {}; ro6 = C.get("riskoff_6h")
    L.append("- Mercado (contexto horario de context.py): " + market_line(C) + (f"; riesgo-off en {ro6} de las últimas {C.get('riskoff_6h_n')} filas horarias" if isinstance(ro6, int) else "")
             + (f"; {len(C['history'])} filas en el histórico de 24 h" if C.get("history") else ""))
    pend = ["pasar el memebot a papel si el PF real a 30 días sigue < 1 (hoy: " + str(k.get("profit_factor")) + ")",
            "pasar la pata Hyperliquid a real en la web de Keel solo con ≥150 $ y ≥21 días de paper con paridad",
            "mantener o apagar el Director (director_enabled) tras leer director_log.jsonl"]
    L.append("- Decisiones que siguen siendo de Àngel (el operador no las toma): " + "; ".join(pend))
    return L


def alert(root, state, f, now):
    """crit/warn findings -> alerts.jsonl (deduped per code for ALERT_DEDUPE_S) + optional ALERT_CMD hook"""
    seen = state.setdefault("alerted", {})
    if now - seen.get(f["code"], 0) < ALERT_DEDUPE_S: return False
    seen[f["code"]] = now
    with open(os.path.join(root, ALERTS), "a") as fh: fh.write(json.dumps({"t": now, **f}) + "\n")
    cmd = os.environ.get("ALERT_CMD")
    if cmd:
        try: subprocess.run(cmd, shell=True, input=f"[{f['level']}] {f['msg']}", text=True, timeout=20, capture_output=True)
        except Exception as e: log.warning("ALERT_CMD %s", e)
    return True


def run_once(root, now=None, dry_run=False, force_daily=False, overview=None):
    now = now or time.time(); root = os.path.abspath(root); os.chdir(root)
    sys.path.insert(0, root); import dash_data
    ov = overview or dash_data.build_overview(root, now)
    cfg = _load(os.path.join(root, "config.json"), {})
    state = _load(os.path.join(root, STATE), {})
    findings, summary = review(ov, cfg, now)
    actions = act(root, ov, findings, cfg, state, now, dry_run=dry_run)
    t, _ = _tz_now(now); today = t.strftime("%Y-%m-%d")
    daily = None
    if force_daily or (t.hour >= DAILY_HOUR and state.get("last_daily") != today):
        daily = daily_lines(root, ov, now); state["last_daily"] = today
    text = entry_text(findings, summary, actions, now, daily)
    alerted = [f["code"] for f in findings if f["level"] in ("crit", "warn") and not dry_run and alert(root, state, f, now)]
    if not dry_run:
        with open(os.path.join(root, DIARY), "a", encoding="utf-8") as fh: fh.write("\n" + text)   # local diary (untracked): git pull never conflicts
        with open(os.path.join(root, LOGF), "a") as fh: fh.write(json.dumps({"t": now, "findings": findings, "actions": actions, "daily": bool(daily)}, default=str) + "\n")
        state.update(ts=now, findings=findings, summary=summary, actions=actions, alerted_now=alerted, daily_written=bool(daily))
        _atomic_json(os.path.join(root, STATE), state)
    return {"findings": findings, "summary": summary, "actions": actions, "text": text, "daily": bool(daily), "alerted": alerted}


def main(argv):
    root = os.path.dirname(os.path.abspath(__file__)); dry = "--dry-run" in argv
    if "--loop" in argv:
        while not os.path.exists(os.path.join(root, "STOP")):
            try: r = run_once(root, dry_run=dry); print(r["text"], flush=True)
            except Exception as e: print("operator error:", e, file=sys.stderr, flush=True)
            time.sleep(3600)
        return 0
    r = run_once(root, dry_run=dry, force_daily="--daily" in argv); print(r["text"]); return 0


if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
