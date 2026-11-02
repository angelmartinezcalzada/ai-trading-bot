#!/usr/bin/env python3
"""Pure aggregator behind GET /api/overview (panel v2, contract in DASHBOARD.md section 1).

build_overview(root, now=None) reads ONLY files under `root` (the bot folder). It never touches the network or
live_sol, and it never raises: a missing, empty or corrupt file leaves its section with available=False and a short
`error`. Big files (logs, CSV, jsonl) are read with a byte tail capped at TAIL_CAP so a multi-MB log is never loaded
whole. Nothing is invented: every value comes from a file the bot wrote, and every section carries the timestamp of
that file (`ts`), its age and a `fresh` flag against the thresholds in FRESH.

Units worth knowing (passed through as the bot writes them):
  - solana.stats.win_rate is a fraction 0..1 (memebot); cex.<ex>.stats.win_rate is a percentage 0..100 (bot.py).
  - solana.kpi_30d.avg_loss is the mean of the losing SELL rows (a negative number); gross_loss is positive.
  - all `ts` are epoch seconds; `t` strings inside rows are the local-time ISO strings the bot wrote.
  - context.sol/btc returns (r1h, r4h, r24h, rv24h) are percentages as context.py writes them; insider.wallets[].rel and
    .part are fractions 0..1; booleans from context/rank files are kept strict (anything that is not a JSON bool -> null).
Secrets (keys.env, solana_wallet.json, dashboard_password.txt, .flask_secret) are never read here.
"""
import os, re, csv, json, time, math, socket, subprocess, collections, datetime as dt

TAIL_CAP = 300_000     # bytes per tail read (contract: 300 KB)
FRESH = {"status": 120, "equity": 300, "insider": 900, "copytrade": 900, "brain": 3 * 3600, "hl_risk": 2 * 3600,
         "candidates": 900, "log": 900, "supervisor": 3600, "eval": 2 * 3600, "director": 3 * 3600, "operator": 2 * 3600, "trend": 1800,
         "context": 2 * 3600, "insider_rank": 2 * 3600}
HEAT, TREND, BTC_REGIME, TIERS = ("hot", "normal", "cold"), ("up", "down", "flat"), ("bull", "bear", "range"), ("elite", "good", "watch")
CEX = ("binance", "coinbase")
TX_RE = re.compile(r" tx=\S+")
# Activity classifier (kind, regex): the first match wins. dashboard.py imports this table from here (importing
# dashboard.py itself has side effects: it opens dashboard_password.txt at import time).
ACT = [("scam", re.compile(r"SCAM block|stable_impersonator|BLACKLIST")), ("trade", re.compile(r"TRADE |LIVE order|ADOPT")),
       ("risk", re.compile(r"KILL|GAP LOSS|AUDIT|max_trade_loss|NO CASH|kill_switch")), ("news", re.compile(r"risk_off|NEWS|SENTIMENT")),
       ("signal", re.compile(r"SIGNAL|signal|breakout|rotation|LEVELS|levels ")), ("skip", re.compile(r" skip |aborted|reject|not filled")),
       ("scan", re.compile(r"SCAN |REGIME")), ("error", re.compile(r"ERROR|Traceback|Exception"))]
PREFILTER_RE = re.compile(r"prefilter (\d+)/(\d+) -> eval (\d+) \((\d+) skipped: hard-vetoed <(\d+)s ago\), "
                          r"rugcheck fetched (\d+)/(\d+) \((\d+) past budget\) in (\d+)s")
SCORE_RE = re.compile(r"meme s(\d+(?:\.\d+)?)")
LIMIT_KEYS = ("max_positions", "stop_pct", "trail_pct", "trail_activate_pct", "partial_tp_pct", "daily_max_drawdown_pct",
              "max_position_pct", "risk_per_trade", "min_score", "brain_min_score", "min_liquidity_usd", "max_hold_hours",
              "exit_mode", "pump_play", "trail_pct_tt", "hard_stop_pct", "size_pct", "runner_trail_pct")


# ---------------------------------------------------------------- small helpers
def _err(e):
    """Short reason for the `error` field: never a traceback, never a path with secrets."""
    s = str(e) or e.__class__.__name__
    return s[:120]


def _hdr(source, ts, now, fresh_after):
    """Common section header. fresh = age_s < fresh_after_s; with no threshold a known ts counts as fresh."""
    age = (now - ts) if isinstance(ts, (int, float)) else None
    fresh = age is not None and (fresh_after is None or age < fresh_after)
    return {"available": True, "source": source, "ts": ts, "age_s": round(age, 1) if age is not None else None,
            "fresh": bool(fresh), "fresh_after_s": fresh_after}


def _na(source, error, fresh_after=None):
    return {"available": False, "source": source, "ts": None, "age_s": None, "fresh": False, "fresh_after_s": fresh_after, "error": error}


def _safe(fn, source, fresh_after=None):
    """Run a section builder; any failure becomes available=False with a short reason."""
    try: return fn()
    except FileNotFoundError: return _na(source, "fichero ausente", fresh_after)
    except Exception as e: return _na(source, _err(e), fresh_after)


def _p(root, *parts): return os.path.join(root, *parts)


def _f(x, default=None):
    """float or default; NaN/inf become default so the JSON stays parseable in the browser."""
    try:
        if x is None or x == "": return default
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError): return default


def _i(x, default=0):
    v = _f(x)
    return int(v) if v is not None else default


def _s(x, n=64):
    """bounded string (token symbols, reasons and log lines are attacker-controlled; the UI escapes, we cap)."""
    return "" if x is None else str(x)[:n]


def _short(a, n=4):
    a = "" if a is None else str(a)
    return a if len(a) <= 2 * n + 1 else f"{a[:n]}…{a[-n:]}"


_URL_RE = re.compile(r"((?:https?|wss?)://[^/\s'\"?]+)[^\s'\"]*")
_KEY_RE = re.compile(r"(?i)\b(api[-_]?key|apikey|token|secret|password|passwd|auth)=([^&\s'\",)]+)")
def _clean(s, n):
    """drop ' tx=<signature>' tokens, reduce URLs to scheme+host (an RPC URL in an error line may carry an API key), mask key=value
    secrets, cap the length"""
    s = TX_RE.sub("", "" if s is None else str(s))
    return _KEY_RE.sub(lambda m: m.group(1) + "=***", _URL_RE.sub(r"\1/…", s))[:n]


def _iso_ts(s):
    """'2026-10-31T12:00:00' / '2026-10-31 12:00:00,123' (machine local time) -> epoch; numbers pass through; else None"""
    if isinstance(s, (int, float)): return float(s) if math.isfinite(float(s)) else None
    try: return time.mktime(time.strptime(str(s).strip()[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S"))
    except Exception: return None


def _load_json(path):
    """(object, mtime); raises on a missing / empty / corrupt file (callers map that to available=False)"""
    with open(path, encoding="utf-8") as f: obj = json.load(f)
    return obj, os.path.getmtime(path)


def _tail_lines(path, cap=TAIL_CAP):
    """Last `cap` bytes of `path` as complete lines (a line cut by the seek is dropped). Returns (lines, file_size)."""
    with open(path, "rb") as f:
        f.seek(0, 2); size = f.tell(); start = max(0, size - cap); f.seek(start); data = f.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines: lines = lines[1:]
    return [l for l in lines if l.strip()], size


def _csv_tail(path, cap=TAIL_CAP):
    """Rows (dicts) from the tail of a CSV whose header is the file's first line. Raises if the file is missing."""
    with open(path, encoding="utf-8", errors="replace") as f: hdr = [h.strip() for h in f.readline().strip().split(",")]
    if not hdr or hdr == [""]: raise ValueError("CSV sin cabecera")
    lines, _ = _tail_lines(path, cap)
    out = []
    for r in csv.reader(l for l in lines if not l.startswith(hdr[0] + ",")):
        if len(r) < len(hdr): continue
        if len(r) > len(hdr): r = r[:len(hdr) - 1] + [",".join(r[len(hdr) - 1:])]
        out.append(dict(zip(hdr, r)))
    return out


def _pgrep(pattern, timeout=3.0):
    """PIDs whose command line matches `pattern`; [] when pgrep is missing, slow or finds nothing. Never raises."""
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=timeout)
        return [int(x) for x in r.stdout.split() if x.isdigit()]
    except Exception: return []


def _sanitize(o):
    """Replace non-finite floats anywhere in the tree with None (json.dumps would emit NaN, which browsers reject)."""
    if isinstance(o, float): return o if math.isfinite(o) else None
    if isinstance(o, dict): return {str(k): _sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_sanitize(v) for v in o]
    return o


def _bounded(o, depth=2, n=16, s=64):
    """A foreign JSON tree (regime gate, regime table, rotation slice...) with bounded size: at most `n` keys/items per level,
    strings <= `s`, `depth` levels; deeper containers become a short JSON string. The UI renders these generically."""
    if isinstance(o, bool) or o is None: return o
    if isinstance(o, (int, float)): return o if math.isfinite(o) else None
    if isinstance(o, str): return o[:s]
    if depth <= 0: return _s(json.dumps(o, default=str, ensure_ascii=False), s)
    if isinstance(o, dict): return {_s(k, 32): _bounded(v, depth - 1, n, s) for k, v in list(o.items())[:n]}
    if isinstance(o, (list, tuple)): return [_bounded(v, depth - 1, n, s) for v in list(o)[:n]]
    return _s(o, s)


def _bool(x):
    """strict JSON bool or None: a string, a number or a missing key is never turned into a pass (fail-closed stays with the reader)"""
    return x if isinstance(x, bool) else None


def _enum(x, allowed):
    return x if isinstance(x, str) and x in allowed else None


def _fold_ret(f):
    """the out-of-sample return of one brain fold, whichever key brain.py used; None when the fold carries no return"""
    for k in ("brain_avg_ret_%", "avg_ret_%", "ret_%", "avg_ret", "ret"):
        v = _f(f.get(k))
        if v is not None: return v
    return None


def _labels(seq):
    """model labels of oos.models_hist (strings, or dicts with model_choice/choice/model); None when it is not a list"""
    if not isinstance(seq, list): return None
    out = []
    for x in seq:
        if isinstance(x, str): out.append(x[:16])
        elif isinstance(x, dict):
            lab = next((x[k] for k in ("model_choice", "choice", "model") if isinstance(x.get(k), str)), None)
            if lab: out.append(lab[:16])
    return out


# ---------------------------------------------------------------- sections
def _config(root):
    try:
        c, _ = _load_json(_p(root, "config.json"))
        if not isinstance(c, dict): raise ValueError("config.json no es un objeto")
        return c, None
    except FileNotFoundError: return {}, "config.json ausente"
    except Exception as e: return {}, _err(e)


def _meta(root, now, cfg_err, ex_cfg):
    try: ts = os.path.getmtime(_p(root, "config.json"))
    except OSError: ts = None
    try: host = socket.gethostname()
    except Exception: host = None
    m = _hdr("config.json + pgrep", ts, now, None) if ts is not None else _na("config.json + pgrep", cfg_err or "config.json ausente")
    if cfg_err: m["available"] = False; m["error"] = cfg_err
    m.update(now=now, host=host, stop_all=os.path.exists(_p(root, "STOP")), tunnel_url=None, fresh_after=dict(FRESH),
             exchanges={ex: {"mode": _s((ec or {}).get("mode", "paper"), 8), "enabled": bool((ec or {}).get("enabled", True))}
                        for ex, ec in ex_cfg.items() if isinstance(ec, dict)})
    try:
        tp = _p(root, "tunnel_url.txt")
        if os.path.exists(tp):
            u = open(tp, encoding="utf-8", errors="replace").read().strip()[:200]
            m["tunnel_url"] = u if u.startswith("https://") else None
    except Exception: pass
    return m


def _health(root, now, ex_cfg):
    exs = list(ex_cfg) or ["solana", "binance", "coinbase"]
    per = {}
    for ex in exs:
        pids = _pgrep(f"python3 bot.py --exchange {ex}")
        try: st_ts = _f(_load_json(_p(root, f"status_{ex}.json"))[0].get("ts"))
        except Exception: st_ts = None
        age = (now - st_ts) if st_ts is not None else None
        stopped = os.path.exists(_p(root, f"STOP_{ex}"))
        # same rule as /api/state in dashboard.py
        health = ("parado" if stopped and not pids else "ok" if pids and age is not None and age < FRESH["status"]
                  else "arrancando" if pids else "caído")
        try: ctl = _load_json(_p(root, f"control_{ex}.json"))[0] or {}
        except Exception: ctl = {}
        per[ex] = {"pids": pids, "health": health, "stopped": stopped, "killed": os.path.exists(_p(root, f"KILL_{ex}")),
                   "paused": bool(isinstance(ctl, dict) and ctl.get("pause")), "status_age_s": round(age, 1) if age is not None else None}
    sup_path = _p(root, "supervisor.log"); sup, sup_ts, sup_err = [], None, None
    try:
        lines, _ = _tail_lines(sup_path, 64_000); sup = [_s(l, 200) for l in lines[-12:]]; sup_ts = os.path.getmtime(sup_path)
    except FileNotFoundError: sup_err = "supervisor.log ausente"
    except Exception as e: sup_err = _err(e)
    h = _hdr("pgrep + supervisor.log", sup_ts, now, FRESH["supervisor"])   # process state is always observable: available stays True
    if sup_err: h["error"] = sup_err
    ins, dash = _pgrep("python3 insider.py"), _pgrep("python3 dashboard.py")
    h.update(exchanges=per, supervisor_tail=sup, insider_pid=ins[0] if ins else None, insider_pids=ins,
             dashboard_pid=dash[0] if dash else None, dashboard_pids=dash)
    return h


def _equity_curve(path, now, maxpts, src, want_7d=True):
    lines, size = _tail_lines(path)
    pts = []
    for l in lines:
        a, _, b = l.partition(","); t, v = _f(a), _f(b)
        if t is not None and v is not None: pts.append((t, v))
    if not pts: raise ValueError("sin filas válidas (epoch,equity)")
    pts.sort()
    w24 = [p for p in pts if p[0] >= now - 86400]

    def sub(w):   # uniform subsample to <= maxpts keeping first and last
        if len(w) <= maxpts: return [[int(t * 1000), v] for t, v in w]
        n = len(w) - 1
        idx = sorted({round(i * n / (maxpts - 1)) for i in range(maxpts)})
        return [[int(w[i][0] * 1000), w[i][1]] for i in idx]
    h = _hdr(src, pts[-1][0], now, FRESH["equity"])
    h.update(points_24h=sub(w24), first_24h=w24[0][1] if w24 else None, last=pts[-1][1],
             min_24h=min(v for _, v in w24) if w24 else None, max_24h=max(v for _, v in w24) if w24 else None,
             n_rows_read=len(pts), from_ts=pts[0][0], truncated=size > TAIL_CAP)
    if want_7d:
        w7 = [p for p in pts if p[0] >= now - 7 * 86400]
        h.update(points_7d=sub(w7), from_7d=w7[0][0] if w7 else None)
    return h


def _trade_row(r):
    reason = r.get("reason") or ""
    return {"time": _s(r.get("time"), 25), "sym": _s((r.get("symbol") or "").strip(), 24), "side": _s((r.get("side") or "").strip(), 8),
            "price": _f(r.get("price")), "qty": _f(r.get("qty")), "fee": _f(r.get("fee")), "pnl": _f(r.get("pnl")),
            "reason": _clean(reason, 120), "equity": _f(r.get("equity")), "is_real": "REAL" in reason}


def _trade_sections(path, src, now):
    """daily_pnl (14 d, SELL rows), kpi_30d (SELL rows, fees of every row) and trades (last 60) from ONE tail read."""
    try: rows = _csv_tail(path); ts = os.path.getmtime(path)
    except FileNotFoundError: na = _na(src, "fichero ausente"); return na, dict(na), dict(na)
    except Exception as e: na = _na(src, _err(e)); return na, dict(na), dict(na)
    sells = [r for r in rows if (r.get("side") or "").strip() == "SELL"]
    today = dt.date.fromtimestamp(now)
    days = [(today - dt.timedelta(days=k)).isoformat() for k in range(13, -1, -1)]
    agg = {d: {"day": d, "pnl": 0.0, "n": 0, "wins": 0} for d in days}
    for r in sells:
        a = agg.get((r.get("time") or "")[:10])
        if a is not None:
            p = _f(r.get("pnl"), 0.0); a["pnl"] += p; a["n"] += 1; a["wins"] += 1 if p > 0 else 0
    dp = _hdr(src, ts, now, None)
    dp.update(days=[dict(a, pnl=round(a["pnl"], 4)) for a in agg.values()], total_14d=round(sum(a["pnl"] for a in agg.values()), 4),
              window_from=days[0], window_to=days[-1], n_rows_read=len(rows))
    cut = now - 30 * 86400
    r30 = [r for r in rows if (_iso_ts(r.get("time")) or 0) >= cut]
    pn = [(_f(r.get("pnl"), 0.0), r) for r in r30 if (r.get("side") or "").strip() == "SELL"]
    wins = [p for p, _ in pn if p > 0]; losses = [p for p, _ in pn if p < 0]
    gw, gl = sum(wins), -sum(losses)
    pick = lambda t: {"sym": _s((t[1].get("symbol") or "").strip(), 24), "pnl": t[0], "time": _s(t[1].get("time"), 25)}
    k = _hdr(src, ts, now, None)
    k.update(n=len(pn), wins=len(wins), win_rate=round(len(wins) / len(pn), 4) if pn else None, gross_win=round(gw, 4), gross_loss=round(gl, 4),
             profit_factor=round(gw / gl, 4) if gl > 0 else None, avg_win=round(gw / len(wins), 4) if wins else None,
             avg_loss=round(sum(losses) / len(losses), 4) if losses else None, expectancy=round(sum(p for p, _ in pn) / len(pn), 4) if pn else None,
             fees=round(sum(_f(r.get("fee"), 0.0) for r in r30), 4), best=pick(max(pn, key=lambda t: t[0])) if pn else None,
             worst=pick(min(pn, key=lambda t: t[0])) if pn else None, n_rows_30d=len(r30))
    t = _hdr(src, ts, now, None)
    t.update(rows=[_trade_row(r) for r in rows[-60:][::-1]], n_rows_read=len(rows), file=src)
    return dp, k, t


def _scan(path, now, src):
    lines, _ = _tail_lines(path)
    pre = scan = block = None
    for l in lines:
        if "prefilter " in l: pre = l
        if " SCAN " in l: scan = l
        if "LIVE buy " in l and "blocked:" in l: block = l
    if pre is None and scan is None: raise ValueError("sin líneas SCAN/prefilter en la cola del log")
    msg = lambda l: _clean(l[24:].split(" ", 1)[-1], 160)   # drops 'YYYY-mm-dd HH:MM:SS,mmm LEVEL '
    out = {"ok": None, "total": None, "eval": None, "skipped_hardfail": None, "hardfail_skip_s": None, "rc_fetched": None,
           "rc_needed": None, "rc_past_budget": None, "secs": None, "prefilter_ts": None, "prefilter_text": None, "parse_error": None}
    if pre:
        out["prefilter_ts"], out["prefilter_text"] = _iso_ts(pre[:19]), msg(pre)
        m = PREFILTER_RE.search(pre)
        if m:
            g = [int(x) for x in m.groups()]
            out.update(ok=g[0], total=g[1], eval=g[2], skipped_hardfail=g[3], hardfail_skip_s=g[4], rc_fetched=g[5], rc_needed=g[6], rc_past_budget=g[7], secs=g[8])
        else: out["parse_error"] = "formato de la línea prefilter no reconocido"
    out["last_scan"] = {"ts": _iso_ts(scan[:19]), "text": msg(scan)} if scan else None
    out["last_buy_block"] = {"ts": _iso_ts(block[:19]), "text": msg(block)} if block else None
    stamps = [x for x in (out["prefilter_ts"], out["last_scan"]["ts"] if out["last_scan"] else None) if x]
    h = _hdr(src, max(stamps) if stamps else None, now, FRESH["log"])
    h.update(out); return h


def _funnel(path, now, src):
    lines, _ = _tail_lines(path)
    rows = []
    for l in lines[-500:]:
        try: r = json.loads(l)
        except Exception: continue
        if isinstance(r, dict): rows.append(r)
    if not rows: raise ValueError("sin filas JSON válidas")
    rows = rows[-500:]
    def first_fail(r):
        f = r.get("fail")
        if isinstance(f, list) and f: return _s(f[0], 40)
        return _s(f, 40) if f else "?"
    by_fail = collections.Counter(first_fail(r) for r in rows if not r.get("pass"))
    by_src = collections.Counter(_s(r.get("src") or "?", 40) for r in rows)
    passed = [r for r in rows if r.get("pass")]
    h = _hdr(src, _iso_ts(rows[-1].get("ts")), now, FRESH["candidates"])
    h.update(rows=len(rows), passed=len(passed), window_from=_s(rows[0].get("ts"), 25), window_to=_s(rows[-1].get("ts"), 25),
             by_fail=[{"reason": k, "n": n} for k, n in sorted(by_fail.items(), key=lambda kv: (-kv[1], kv[0]))],
             by_src=[{"src": k, "n": n} for k, n in sorted(by_src.items(), key=lambda kv: (-kv[1], kv[0]))],
             last_passed=[{"ts": _s(r.get("ts"), 25), "sym": _s(r.get("sym"), 24), "score": _f(r.get("score"))} for r in passed[-5:][::-1]])
    return h


def _brain(root, now, st, status_fresh):
    model = (st or {}).get("brain") if isinstance(st, dict) else None
    model = model if isinstance(model, dict) else {}
    dec = model.get("decisions") if isinstance(model.get("decisions"), list) else []
    if status_fresh and isinstance(model.get("model"), dict):
        m, ts, src = model["model"], _f(st.get("ts")), "status_solana.json (brain.model)"
    else:
        for cand in ("data/brain_state.json", "brain_state.json"):
            p = _p(root, cand)
            if os.path.exists(p): m, ts = _load_json(p); src = cand; break
        else: raise FileNotFoundError("data/brain_state.json")
        if not isinstance(m, dict): raise ValueError("brain_state.json no es un objeto")
    h = _hdr(src, ts, now, FRESH["brain"])
    h.update(active=bool(m.get("active")), updated=_s(m.get("updated"), 32), n_labelled=m.get("n_labelled"), n=m.get("n"),
             base=_f(m.get("base")), avg_win=_f(m.get("avg_win")), avg_loss=_f(m.get("avg_loss")),
             oos=m.get("oos") if isinstance(m.get("oos"), dict) else None,
             decisions=[{"t": _s(d.get("t"), 20), "sym": _s(d.get("sym"), 24), "score": _f(d.get("score")), "p": _f(d.get("p")), "ev_pct": _f(d.get("ev_pct")),
                         "kelly_pct": _f(d.get("kelly_pct")), "size": _f(d.get("size")), "pass": bool(d.get("pass")), "fail": _s(d.get("fail"), 80), "narr": _s(d.get("narr"), 60)}
                        for d in dec[:8] if isinstance(d, dict)],
             decisions_ts=_f((st or {}).get("ts")) if isinstance(st, dict) else None)
    # brain v3 fields (all optional: an older brain_state.json simply leaves them null)
    oos = h["oos"] or {}; fo = m.get("folds"); fl = [f for f in fo if isinstance(f, dict)] if isinstance(fo, list) else []
    rets = [v for v in (_fold_ret(f) for f in fl) if v is not None]; labs = _labels(oos.get("models_hist"))
    cal = m.get("calibration") if isinstance(m.get("calibration"), list) else None
    try: cm = os.path.getmtime(_p(root, "brain.py"))
    except OSError: cm = None
    ut = _iso_ts(m.get("updated"))
    h.update(model_choice=_s(m.get("model_choice"), 16) or None, code_version=_s(m.get("code_version"), 32) or None, archive_n=_i(m.get("archive_n"), None),
             folds_n=len(fl) if isinstance(fo, list) else (_i(fo, None) if isinstance(fo, (int, float)) and not isinstance(fo, bool) else None),
             folds_pos=sum(1 for v in rets if v > 0) if rets else None, folds_mean_ret=round(sum(rets) / len(rets), 3) if rets else None,
             folds=_bounded(fo, 2, 12) if isinstance(fo, (list, dict)) else None,
             models_hist_n=len(labs) if labs is not None else None, models_hist_flips=sum(1 for i in range(1, len(labs)) if labs[i] != labs[i - 1]) if labs else None,
             models_hist_last=labs[-1] if labs else None,
             calibration=[{"bin": _s(b.get("bin"), 12), "n": _i(b.get("n"), None), "p_avg": _f(b.get("p_avg")), "win_rate": _f(b.get("win_rate"))} for b in cal if isinstance(b, dict)][:10] if cal is not None else None,
             updated_ts=ut, code_mtime=cm, code_newer_s=round(cm - ut, 1) if (cm is not None and ut is not None) else None)
    lam = m.get("lambda"); h["lambda"] = _f(lam.get("logit")) if isinstance(lam, dict) else _f(lam); h["lambda_ridge"] = _f(lam.get("ridge")) if isinstance(lam, dict) else None   # brain v3 writes {logit, ridge}
    return h


def _eval(root, now):
    obj, mt = _load_json(_p(root, "eval_solana.json"))
    if not isinstance(obj, dict): raise ValueError("eval_solana.json no es un objeto")
    h = _hdr("eval_solana.json", mt, now, FRESH["eval"]); h.update(data=obj, generado=_s(obj.get("generado"), 32)); return h


def _limits(root, now, sol_cfg):
    if not sol_cfg: raise FileNotFoundError("config.json exchanges.solana")
    h = _hdr("config.json (exchanges.solana)", os.path.getmtime(_p(root, "config.json")), now, None)
    h.update({k: sol_cfg.get(k) for k in LIMIT_KEYS}); return h


def _positions(st, root, sol_cfg, mode):
    state_file = f"state_solana_{mode}.json"; raw, state_ok, state_err = {}, False, None
    try:
        raw = (_load_json(_p(root, state_file))[0] or {}).get("pos") or {}; state_ok = isinstance(raw, dict)
        if not state_ok: raw, state_err = {}, "pos no es un objeto"
    except FileNotFoundError: state_err = f"{state_file} ausente"
    except Exception as e: state_err = _err(e)
    # operative trailing distance: exit_mode 'trail' trails trail_pct_tt (percent) from the peak; the bracket modes use trail_pct (fraction)
    trail_pct = (_f(sol_cfg.get("trail_pct_tt"), 12) / 100) if sol_cfg.get("exit_mode") == "trail" else _f(sol_cfg.get("trail_pct")); out = []
    for p in st.get("positions") or []:
        if not isinstance(p, dict): continue
        m = _s(p.get("mint"), 64); sp = raw.get(m) if isinstance(raw.get(m), dict) else {}
        entry, mark, stop, best = _f(p.get("entry")), _f(p.get("mark")), _f(p.get("stop")), _f(sp.get("best"))
        trailing = bool(p.get("trailing")); strategy = _s(p.get("strategy"), 40)
        trail_level = best * (1 - trail_pct) if (trailing and best is not None and trail_pct is not None) else None
        score = _f(sp.get("score"))
        if score is None:
            mm = SCORE_RE.search(strategy); score = _f(mm.group(1)) if mm else None
        out.append({"sym": _s(p.get("sym"), 24), "mint": m, "mint_short": _short(m), "entry": entry, "mark": mark, "best": best, "cost": _f(p.get("cost")),
                    "pnl": _f(p.get("pnl")), "pnl_pct": _f(p.get("pnl_pct")), "age_min": _f(p.get("age_min")), "score": score, "strategy": strategy,
                    "partial": bool(sp.get("partial")) if "partial" in sp else ("½TP" in strategy), "stop": stop, "trail_level": trail_level,
                    "trail_pct": trail_pct, "trailing": trailing, "tp": _f(p.get("tp")), "pump": sp.get("play") == "pump",
                    "sellfail": _i(sp.get("sellfail")), "noroute": _i(sp.get("noroute")), "rent_usd": _f(sp.get("rent_usd")),
                    "dist_stop_pct": round((mark / stop - 1) * 100, 2) if mark and stop else None,
                    "dist_trail_pct": round((mark / trail_level - 1) * 100, 2) if mark and trail_level else None, "in_state": m in raw})
    return out, {"file": state_file, "ok": state_ok, "error": state_err}


def _solana_status(st, root, sol_cfg, cfg_mode):
    mode = _s(st.get("mode") or cfg_mode, 8)
    eq, dpp = _f(st.get("equity")), _f(st.get("day_pnl_pct"))
    day_usd = (eq - eq / (1 + dpp / 100)) if (eq is not None and dpp is not None and dpp > -100) else None
    w = st.get("wallet") if isinstance(st.get("wallet"), dict) else None
    reg = st.get("regime") if isinstance(st.get("regime"), dict) else {}
    stats = st.get("stats") if isinstance(st.get("stats"), dict) else {}
    pp = st.get("pump_play") if isinstance(st.get("pump_play"), dict) else None
    positions, state_info = _positions(st, root, sol_cfg, mode)
    L = lambda x: [i for i in (x or []) if isinstance(i, dict)] if isinstance(x, list) else []
    return {"mode": mode, "equity": eq, "cash": _f(st.get("cash")), "day_pnl_pct": dpp, "day_pnl_usd": round(day_usd, 4) if day_usd is not None else None,
            "halted": bool(st.get("halted")), "paused": bool(st.get("paused")),
            "wallet": {"addr_short": _short(w.get("addr")), "sol": _f(w.get("sol")), "usd": _f(w.get("usd")), "t": _f(w.get("t"))} if w else None,
            "live_min_sol": _f(st.get("live_min_sol")), "sol_usd": _f(reg.get("sol_usd")), "universe": _i(st.get("universe"), None),
            "positions": positions, "state": state_info, "open_pnl": round(sum(p["pnl"] for p in positions if p["pnl"] is not None), 4),
            "stats": {"closed": _i(stats.get("closed", stats.get("closed_trades")), None), "win_rate": _f(stats.get("win_rate")), "net_pnl": _f(stats.get("net_pnl"))},
            "pump_play": {"trades": _i(pp.get("trades"), None), "pnl": _f(pp.get("pnl")), "wins": _i(pp.get("wins"), None), "open": [_s(x, 24) for x in (pp.get("open") or [])][:10]} if pp else None,
            "signals": [{"t": _s(s.get("t"), 20), "sym": _s(s.get("sym"), 24), "type": _s(s.get("type"), 16), "strategy": _s(s.get("strategy"), 16), "side": s.get("side")} for s in L(st.get("signals"))[-10:][::-1]],
            "movers": [{"sym": _s(x.get("sym"), 24), "chg5": _f(x.get("chg5"))} for x in L(st.get("movers"))[:10]],
            "smart_items": [{"sym": _s(x.get("sym"), 24), "flags": [_s(f, 32) for f in (x.get("flags") or [])][:8], "held": bool(x.get("held"))} for x in L((st.get("smart") or {}).get("items") if isinstance(st.get("smart"), dict) else [])[:10]],
            "ai_pump": [{"sym": _s(x.get("sym"), 24), "pump": _f(x.get("pump")), "exh": _f(x.get("exh"))} for x in L(st.get("ai_pump"))[:6]]}


def _solana(root, now, sol_cfg):
    cfg_mode = _s(sol_cfg.get("mode", "paper"), 8) or "paper"; src = "status_solana.json"; st = None
    try:
        st, _ = _load_json(_p(root, src))
        if not isinstance(st, dict) or "ts" not in st: raise ValueError("sin campo ts")
        S = _hdr(src, _f(st.get("ts")), now, FRESH["status"])
        S.update(_solana_status(st, root, sol_cfg, cfg_mode))
    except FileNotFoundError: S = _na(src, "fichero ausente", FRESH["status"])
    except Exception as e: S = _na(src, _err(e), FRESH["status"])
    S["mode_cfg"] = cfg_mode
    S["equity_curve"] = _safe(lambda: _equity_curve(_p(root, "equity_solana.csv"), now, 300, "equity_solana.csv"), "equity_solana.csv", FRESH["equity"])
    tf = f"trades_solana_{cfg_mode}.csv"
    S["daily_pnl"], S["kpi_30d"], S["trades"] = _trade_sections(_p(root, tf), tf, now)
    S["scan"] = _safe(lambda: _scan(_p(root, "bot_solana.log"), now, "bot_solana.log"), "bot_solana.log", FRESH["log"])
    S["funnel"] = _safe(lambda: _funnel(_p(root, "candidates_solana.jsonl"), now, "candidates_solana.jsonl"), "candidates_solana.jsonl", FRESH["candidates"])
    S["brain"] = _safe(lambda: _brain(root, now, st, S["available"] and S["fresh"]), "data/brain_state.json", FRESH["brain"])
    S["eval"] = _safe(lambda: _eval(root, now), "eval_solana.json", FRESH["eval"])
    S["limits"] = _safe(lambda: _limits(root, now, sol_cfg), "config.json (exchanges.solana)")
    if cfg_mode == "paper":   # a paper panel must never hide real activity: count the REAL trade rows of the last 24 h
        S["real_trades_24h"] = None; S["real_trades_file"] = "trades_solana_live.csv"
        try:
            lp = _p(root, "trades_solana_live.csv")
            if os.path.exists(lp): S["real_trades_24h"] = sum(1 for r in _csv_tail(lp) if (_iso_ts(r.get("time")) or 0) >= now - 86400)
        except Exception as e: S["real_trades_error"] = _err(e)
    return S


def _insider(root, now):
    src = "insider_status.json"; st, mt = _load_json(_p(root, src))
    if not isinstance(st, dict): raise ValueError("insider_status.json no es un objeto")
    h = _hdr(src, _f(st.get("ts")) or mt, now, FRESH["insider"])
    L = lambda x: [i for i in (x or []) if isinstance(i, dict)] if isinstance(x, list) else []
    conv = st.get("conv") if isinstance(st.get("conv"), dict) else {}
    top = sorted(((m, c) for m, c in conv.items() if isinstance(c, dict)), key=lambda kv: -_f(kv[1].get("score"), 0))[:5]
    ws = None
    try:
        w, wmt = _load_json(_p(root, "insider_ws_status.json"))
        if isinstance(w, dict): ws = {"state": _s(w.get("state"), 40), "subs": _i(w.get("subs"), None), "events": _i(w.get("events"), None), "ts": _f(w.get("ts")) or wmt, "age_s": round(now - (_f(w.get("ts")) or wmt), 1)}
    except Exception: pass
    h.update(ws=ws, tracked=_i(st.get("tracked"), None), cycle_s=_f(st.get("cycle_s")), live_ranked=_i(st.get("live_ranked"), None),
             counts={_s(k, 24): _i(v, 0) for k, v in (st.get("counts") or {}).items()} if isinstance(st.get("counts"), dict) else {},
             alerts=[{"t": _f(a.get("t")), "mint_short": _short(a.get("mint")), "elite": _i(a.get("elite"), None), "n": _i(a.get("n"), None), "score": _f(a.get("score")), "fwd1h": _f(a.get("fwd1h"))}
                     for a in L(st.get("alerts"))[-10:][::-1]],
             conv=[{"mint_short": _short(m), "score": _f(c.get("score")), "n": _i(c.get("n"), None), "elite": _i(c.get("elite"), None)} for m, c in top],
             feed=[{"t": _f(e.get("t")), "kind": _s(e.get("kind"), 24), "w_short": _short(e.get("w")) if e.get("w") else None,
                    "mint_short": _short(e.get("mint")) if e.get("mint") else None, "sol": _f(e.get("sol")), "usd": _f(e.get("usd")), "tier": _s(e.get("tier"), 8) or None}
                   for e in L(st.get("feed"))[-20:][::-1]])
    # insider v4: status additions (insider.py) + the reliability ranking (insider_rank.py -> insider_rank.json), each None-safe
    tiers_d = lambda k: {_s(t, 16): _i(v, 0) for t, v in st[k].items()} if isinstance(st.get(k), dict) else {}
    sbm = st.get("sells_n_by_mint") if isinstance(st.get("sells_n_by_mint"), dict) else None
    rk = _safe(lambda: _insider_rank(root, now), "insider_rank.json", FRESH["insider_rank"])
    h.update(rank_t=_f(st.get("rank_t")), rank_tiers=tiers_d("rank_tiers"), tracked_by_tier=tiers_d("tracked_by_tier"),
             rotation_slice=_bounded(st.get("rotation_slice"), 2, 8), rpc_err_n=_i(st.get("rpc_err_n"), None),
             sells_n_by_mint=[{"mint_short": _short(m), "n": _i(n, 0)} for m, n in sorted(sbm.items(), key=lambda kv: (-_i(kv[1], 0), str(kv[0])))[:8]] if sbm is not None else None,
             sells_n_total=sum(_i(n, 0) for n in sbm.values()) if sbm is not None else None,
             wallets=rk.pop("wallets", []), rank=rk)
    return h


def _insider_rank(root, now):
    """insider_rank.json (insider_rank.py, cwd of the bot): reliability ranking of the mined wallets. Returns the header plus the
    top 10 by `rel` (short addresses only) and the tier counts; a missing/corrupt file leaves insider.rank available=False."""
    src = "insider_rank.json"; r, mt = _load_json(_p(root, src))
    if not isinstance(r, dict): raise ValueError("insider_rank.json no es un objeto")
    h = _hdr(src, _f(r.get("t")) or mt, now, FRESH["insider_rank"])
    W = r.get("wallets") if isinstance(r.get("wallets"), dict) else {}
    rel = lambda w: _f(w.get("rel")) if _f(w.get("rel")) is not None else -1.0
    ws = sorted(((a, w) for a, w in W.items() if isinstance(w, dict)), key=lambda kv: (-rel(kv[1]), str(kv[0])))
    def row(a, w):
        pnl = w.get("pnl") if isinstance(w.get("pnl"), dict) else {}
        return {"addr_short": _short(a), "tier": _enum(w.get("tier"), TIERS), "rel": _f(w.get("rel")), "h": _i(w.get("h"), None), "m": _i(w.get("m"), None),
                "h_eff": _f(w.get("h_eff")), "m_eff": _f(w.get("m_eff")), "hr_post": _f(w.get("hr_post")), "part": _f(w.get("part")), "bot": _bool(w.get("bot")),
                "bot_why": _s(w.get("bot_why"), 48) or None, "early": _f(w.get("early")), "days": _i(w.get("days"), None), "med_dt": _f(w.get("med_dt")),
                "med_dslot": _f(w.get("med_dslot")), "avg_sol": _f(w.get("avg_sol")), "last_hit_t": _f(w.get("last_hit_t")), "last_seen_t": _f(w.get("last_seen_t")),
                "cluster": _s(w.get("cluster"), 24) or None, "live_n": _i(w.get("live_n"), None), "live_hit": _i(w.get("live_hit"), None), "live_mean": _f(w.get("live_mean")),
                "pnl_win_pct": _f(pnl.get("win_pct")), "pnl_realized": _f(pnl.get("realized")), "pnl_unrealized": _f(pnl.get("unrealized")),
                "pnl_n_tokens": _i(pnl.get("n_tokens"), None), "why": _s(w.get("why"), 120)}
    T = r.get("tiers") if isinstance(r.get("tiers"), dict) else None
    tiers = {k: _i(T.get(k), None) for k in TIERS} if T is not None else {k: sum(1 for _, w in ws if w.get("tier") == k) for k in TIERS}
    dsc = r.get("discovery") if isinstance(r.get("discovery"), dict) else None
    h.update(code=_s(r.get("code"), 16), base_rate=_f(r.get("base_rate")), half_life_d=_f(r.get("half_life_d")), n_launches=_i(r.get("n_launches"), None),
             n_wallets=len(ws), n_bots=sum(1 for _, w in ws if w.get("bot") is True), tiers=tiers,
             discovery={"t": _f(dsc.get("t")), "n_candidates": _i(dsc.get("n_candidates"), None), "n_added": _i(dsc.get("n_added"), None), "note": _s(dsc.get("note"), 120)} if dsc is not None else None,
             wallets=[row(a, w) for a, w in ws[:10]])
    return h


def _copytrade(root, now):
    src = "state/copytrade_paper.json"; st, mt = _load_json(_p(root, "state", "copytrade_paper.json"))
    if not isinstance(st, dict): raise ValueError("copytrade_paper.json no es un objeto")
    h = _hdr(src, mt, now, FRESH["copytrade"])
    pos = st.get("pos") if isinstance(st.get("pos"), dict) else {}
    recent, wins, wr, n_closed, csv_err = [], None, None, 0, None
    try:
        rows = _csv_tail(_p(root, "trades_solana_copy_paper.csv"))
        closed = [p for p in (_f(r.get("pnl")) for r in rows if (r.get("side") or "").strip() != "BUY") if p is not None]
        n_closed = len(closed); wins = sum(1 for p in closed if p > 0); wr = round(wins / n_closed, 4) if n_closed else None
        recent = [{"time": _s(r.get("time"), 25), "symbol": _s((r.get("symbol") or "").strip(), 24), "side": _s((r.get("side") or "").strip(), 8), "price": _f(r.get("price")),
                   "usd": _f(r.get("usd")), "pnl": _f(r.get("pnl")), "reason": _clean(r.get("reason"), 80)} for r in rows[-20:][::-1]]
    except FileNotFoundError: csv_err = "trades_solana_copy_paper.csv ausente"
    except Exception as e: csv_err = _err(e)
    h.update(mode="paper", closed=_i(st.get("closed"), None), pnl=_f(st.get("pnl")),
             open=[{"sym": _s(q.get("sym"), 24), "mint_short": _short(m), "e": _f(q.get("e")), "t": _f(q.get("t")), "liq": _f(q.get("liq")), "rug_n": _i(q.get("rug_n"))}
                   for m, q in pos.items() if isinstance(q, dict)],
             recent=recent, wins=wins, win_rate=wr, n_closed_read=n_closed, csv_error=csv_err)
    return h


def _hl(root, now):
    paper = evidence = risk = None; risk_ts = None; errs = {}; ctx = []
    try:
        p, _ = _load_json(_p(root, "hl_leg", "hl_paper.json"))
        paper = {k: p.get(k) for k in ("deployment_id", "strategy_name", "strategy_version", "started", "simulated_capital_usd", "schedule",
                                        "expectation", "go_live_criteria", "replaces", "first_evaluation", "auto_pause")}
        u = str(p.get("url") or ""); paper["url"] = u[:200] if u.startswith("https://") else None
    except FileNotFoundError: errs["paper"] = "hl_leg/hl_paper.json ausente"
    except Exception as e: errs["paper"] = _err(e)
    try:
        ev, _ = _load_json(_p(root, "hl_leg", "evidence.json"))
        runs = ((ev.get("selected") or {}).get("runs") or {}); oos = runs.get("out_of_sample") or {}; full = runs.get("full") or {}
        evidence = {"oos": {k: _f(oos.get(k)) for k in ("sharpe", "return_pct", "max_dd_pct", "profit_factor")},
                    "full": {k: (_s(full.get(k), 16) if k == "quarters_positive" else _f(full.get(k))) for k in ("sharpe", "return_pct", "max_dd_pct", "quarters_positive")},
                    "honest_summary": _s(ev.get("honest_summary"), 700), "windows": ev.get("windows") if isinstance(ev.get("windows"), dict) else None,
                    "generated": _s(ev.get("generated"), 120)}
    except FileNotFoundError: errs["evidence"] = "hl_leg/evidence.json ausente"
    except Exception as e: errs["evidence"] = _err(e)
    try:
        r, risk_ts = _load_json(_p(root, "data", "hl_risk.json"))
        coins = r.get("coins") if isinstance(r.get("coins"), dict) else {}; lst = []
        for c, v in coins.items():
            if not isinstance(v, dict): continue
            fl = [_s(x, 32) for x in (v.get("flags_long") or [])]; fs = [_s(x, 32) for x in (v.get("flags_short") or [])]
            # the Keel strategy is long-only, so size_mult is the long multiplier; both are kept for completeness
            lst.append({"coin": _s(c, 16), "flags_long": fl, "flags_short": fs, "size_mult": _f(v.get("size_mult_long")), "size_mult_long": _f(v.get("size_mult_long")),
                        "size_mult_short": _f(v.get("size_mult_short")), "n_flags": len(fl) + len(fs), "time": _s(v.get("time"), 32)})
        lst.sort(key=lambda x: (-x["n_flags"], x["coin"]))
        risk = {"status": _s(r.get("status"), 16), "generated": _s(r.get("updated"), 32), "ts": risk_ts, "ok": _i(r.get("ok"), None), "failed": _i(r.get("failed"), None),
                "last_attempt": _s(r.get("last_attempt"), 32) or None, "coins": lst}
    except FileNotFoundError: errs["risk"] = "data/hl_risk.json ausente"
    except Exception as e: errs["risk"] = _err(e)
    try:
        rows = _csv_tail(_p(root, "data", "hl_context.csv"), 64_000); ctx = [{_s(k, 24): _s(v, 64) for k, v in r.items()} for r in rows[-10:][::-1]]
    except FileNotFoundError: errs["context"] = "data/hl_context.csv ausente"
    except Exception as e: errs["context"] = _err(e)
    if paper is None and evidence is None and risk is None and not ctx:
        raise FileNotFoundError("hl_leg/hl_paper.json, hl_leg/evidence.json, data/hl_risk.json")
    h = _hdr("data/hl_risk.json", risk_ts, now, FRESH["hl_risk"])
    if errs: h["error"] = "; ".join(f"{k}: {v}" for k, v in errs.items())
    h.update(paper=paper, evidence=evidence, risk=risk, context_tail=ctx, errors=errs)
    return h


def _cex(root, now, ex_cfg):
    exs, stamps = {}, []
    for ex in CEX:
        src = f"status_{ex}.json"; ec = ex_cfg.get(ex) if isinstance(ex_cfg.get(ex), dict) else {}
        mode_cfg = _s(ec.get("mode", "paper"), 8) or "paper"
        try:
            st, mt = _load_json(_p(root, src))
            if not isinstance(st, dict): raise ValueError("no es un objeto")
            ts = _f(st.get("ts")) or mt; stamps.append(ts); h = _hdr(src, ts, now, FRESH["status"])
            reg = st.get("regime") if isinstance(st.get("regime"), dict) else {}
            h.update(mode=_s(st.get("mode") or mode_cfg, 8), equity=_f(st.get("equity")), cash=_f(st.get("cash")), day_pnl_pct=_f(st.get("day_pnl_pct")),
                     halted=bool(st.get("halted")), paused=bool(st.get("paused")), no_cash=bool(st.get("no_cash")),
                     positions=[{"sym": _s(p.get("sym"), 24), "side": _s(p.get("side"), 8), "entry": _f(p.get("entry")), "mark": _f(p.get("mark")), "pnl": _f(p.get("pnl")),
                                 "pnl_pct": _f(p.get("pnl_pct")), "age_min": _f(p.get("age_min")), "strategy": _s(p.get("strategy"), 32)}
                                for p in (st.get("positions") or []) if isinstance(p, dict)],
                     stats=st.get("stats") if isinstance(st.get("stats"), dict) else {}, regime={_s(k, 24): reg[k] for k in list(reg)[:8]},
                     fng=st.get("fng"), net_deposits=_f(st.get("net_deposits")), external_holdings=st.get("external_holdings") if isinstance(st.get("external_holdings"), dict) else {},
                     universe=_i(st.get("universe"), None))
        except FileNotFoundError: h = _na(src, "fichero ausente", FRESH["status"])
        except Exception as e: h = _na(src, _err(e), FRESH["status"])
        h.update(mode_cfg=mode_cfg, enabled=bool(ec.get("enabled", True)),
                 equity_curve=_safe(lambda: _equity_curve(_p(root, f"equity_{ex}.csv"), now, 200, f"equity_{ex}.csv", want_7d=False), f"equity_{ex}.csv", FRESH["equity"]))
        h["points_24h"] = h["equity_curve"]["points_24h"] if h["equity_curve"].get("available") else []   # contract: points_24h on the exchange itself
        tf = f"trades_{ex}_{mode_cfg}.csv"; _, _, tr = _trade_sections(_p(root, tf), tf, now)
        if tr.get("available"): tr["rows"] = tr["rows"][:15]
        h["trades"] = tr; exs[ex] = h
    top = _hdr("status_binance.json, status_coinbase.json", max(stamps) if stamps else None, now, FRESH["status"])
    top["available"] = any(e.get("available") for e in exs.values())
    if not top["available"]: top["error"] = "ningún status_<ex>.json legible"
    top["exchanges"] = exs
    return top


def _activity(root, now, ex_cfg):
    exs = list(ex_cfg) or ["solana", "binance", "coinbase"]
    items, srcs, errs = [], [], {}
    for ex in exs:
        try: lines, _ = _tail_lines(_p(root, f"bot_{ex}.log"))
        except FileNotFoundError: errs[ex] = "ausente"; continue
        except Exception as e: errs[ex] = _err(e); continue
        srcs.append(f"bot_{ex}.log")
        for l in lines[-400:]:
            if len(l) < 24 or not l[:4].isdigit(): continue
            k = next((k for k, r in ACT if r.search(l)), None)
            if not k: continue
            items.append({"t": l[:19], "ts": _iso_ts(l[:19]), "ex": ex, "kind": k, "msg": _clean(l[24:].split(" ", 1)[-1], 240)})
    if not srcs: raise FileNotFoundError("bot_<ex>.log")
    items.sort(key=lambda x: x["t"], reverse=True); items = items[:80]
    h = _hdr(", ".join(srcs), items[0]["ts"] if items and items[0]["ts"] else None, now, FRESH["log"])
    if errs: h["error"] = "; ".join(f"bot_{k}.log {v}" for k, v in errs.items())
    h.update(items=items, errors=errs)
    return h


def _director(root, now):
    """director_state.json (what the Director decided, with its evidence) + the last lines of director_log.jsonl."""
    src = "director_state.json"; st, mt = _load_json(_p(root, src))
    if not isinstance(st, dict): raise ValueError("director_state.json no es un objeto")
    h = _hdr(src, _f(st.get("ts")) or mt, now, FRESH["director"])
    ev = st.get("evidence") if isinstance(st.get("evidence"), dict) else {}
    sp = st.get("size_policy") if isinstance(st.get("size_policy"), dict) else {}
    ep = st.get("exit_profile") if isinstance(st.get("exit_profile"), dict) else {}
    plays_ev = ev.get("plays") if isinstance(ev.get("plays"), dict) else {}
    log_tail = []
    try:
        lines, _ = _tail_lines(_p(root, "director_log.jsonl"), 64_000)
        for l in lines[-6:][::-1]:
            try: r = json.loads(l)
            except Exception: continue
            if isinstance(r, dict): log_tail.append({"t": _f(r.get("t")), "shadow": bool(r.get("shadow")), "summary": _s(r.get("summary"), 240), "changes": [{"key": _s(c.get("key"), 32), "before": c.get("before"), "after": c.get("after")} for c in (r.get("changes") or []) if isinstance(c, dict)][:8]})
    except Exception: pass
    h.update(shadow=bool(st.get("shadow")), first_run=_f(st.get("first_run")), plays={_s(k, 16): _s(v, 8) for k, v in (st.get("plays") or {}).items()} if isinstance(st.get("plays"), dict) else {},
             plays_why={_s(k, 16): _s(v, 160) for k, v in (ev.get("plays_why") or {}).items()} if isinstance(ev.get("plays_why"), dict) else {},
             min_score_eff=_f(st.get("min_score_eff")), ev_min_eff=_f(st.get("ev_min_eff")), max_trades_day=_i(st.get("max_trades_day"), None),
             size_policy={"target_usd": _f(sp.get("target_usd")), "fixed_share": _f(sp.get("fixed_share")), "fixed_usd": _f(sp.get("fixed_usd")), "binding": _s(sp.get("binding"), 32), "why": _s(sp.get("why"), 200)},
             windows=[int(x) for x in (st.get("windows") or []) if isinstance(x, (int, float)) and 0 <= x < 24], exit_profile={"hard_stop_pct": _f(ep.get("hard_stop_pct")), "trail_pct": _f(ep.get("trail_pct")), "why": _s(ep.get("why"), 160)},
             evidence={"equity": _f(ev.get("equity")), "sol_usd": _f(ev.get("sol_usd")), "fixed_cost_usd": _f(ev.get("fixed_cost_usd")), "rent_lost_prob": _f(ev.get("rent_lost_prob")), "cost_pct": _f(ev.get("cost_pct")),
                       "dataset_rows": _i(ev.get("dataset_rows"), None), "score_floor_why": _s(ev.get("score_floor_why"), 160),
                       "plays": {_s(k, 16): {"n_eff": _f(v.get("n_eff")), "pf": _f(v.get("pf")), "exp_pct": _f(v.get("exp_pct")),
                                             "real_n": _i((v.get("real") or {}).get("n"), None), "real_pf": _f((v.get("real") or {}).get("pf_raw")), "real_exp": _f((v.get("real") or {}).get("exp_pct_raw")),
                                             "paper_n": _i((v.get("paper") or {}).get("n"), None), "paper_pf": _f((v.get("paper") or {}).get("pf_raw")), "paper_exp": _f((v.get("paper") or {}).get("exp_pct_raw"))}
                                 for k, v in plays_ev.items() if isinstance(v, dict)}},
             log=log_tail)
    # director v2: regime gate (closed values per regime dimension) + the regime evidence table; both passed through bounded
    rg = st.get("regime_gate") if isinstance(st.get("regime_gate"), dict) else None
    rt = ev.get("regime") if isinstance(ev.get("regime"), (dict, list)) else None
    h.update(version=_i(st.get("version"), None), regime_gate=_bounded(rg, 2, 12) if rg is not None else None,
             regime_gate_n=sum(1 for v in rg.values() if v not in (None, False, [], {}, "")) if rg else 0,
             regime_table=_bounded(rt, 3, 16) if rt is not None else None)
    return h


def _operator(root, now):
    """operator_state.json (operador.py: automatic hourly review -> findings, actions, summary) + the last alerts."""
    src = "operator_state.json"; st, mt = _load_json(_p(root, src))
    if not isinstance(st, dict): raise ValueError("operator_state.json no es un objeto")
    h = _hdr(src, _f(st.get("ts")) or mt, now, FRESH["operator"])
    F = [{"level": _s(f.get("level"), 8), "code": _s(f.get("code"), 40), "msg": _s(f.get("msg"), 200)} for f in (st.get("findings") or []) if isinstance(f, dict)][:20]
    A = [{"action": _s(a.get("action"), 32), "detail": _s(a.get("detail"), 200), "dry_run": bool(a.get("dry_run"))} for a in (st.get("actions") or []) if isinstance(a, dict)][:10]
    sm = st.get("summary") if isinstance(st.get("summary"), dict) else {}
    alerts = []
    try:
        lines, _ = _tail_lines(_p(root, "alerts.jsonl"), 64_000)
        for l in lines[-8:][::-1]:
            try: r = json.loads(l)
            except Exception: continue
            if isinstance(r, dict): alerts.append({"t": _f(r.get("t")), "level": _s(r.get("level"), 8), "code": _s(r.get("code"), 40), "msg": _s(r.get("msg"), 200)})
    except Exception: pass
    h.update(findings=F, actions=A, worst=("crit" if any(f["level"] == "crit" for f in F) else "warn" if any(f["level"] == "warn" for f in F) else "ok"),
             summary={_s(k, 16): (_s(v, 300) if not isinstance(v, (list, dict)) else v) for k, v in sm.items()}, last_daily=_s(st.get("last_daily"), 12), last_ata=_f(st.get("last_ata")),
             last_restart={_s(k, 16): _f(v) for k, v in (st.get("last_restart") or {}).items()} if isinstance(st.get("last_restart"), dict) else {}, alerts=alerts)
    return h


def _trend(root, now):
    """state/trend_status.json (trend_spot.py: paper trend play on liquid Solana tokens)"""
    src = "state/trend_status.json"; st, mt = _load_json(_p(root, "state", "trend_status.json"))
    if not isinstance(st, dict): raise ValueError("trend_status.json no es un objeto")
    h = _hdr(src, _f(st.get("ts")) or mt, now, FRESH["trend"])
    sig = st.get("signals") if isinstance(st.get("signals"), dict) else {}
    h.update(mode=_s(st.get("mode"), 8), budget_usd=_f(st.get("budget_usd")), equity=_f(st.get("equity")), cash=_f(st.get("cash")), closed=_i(st.get("closed"), None), pnl=_f(st.get("pnl")),
             last_eval_day=_s(st.get("last_eval_day"), 12), rule=_s(st.get("rule"), 120),
             positions=[{"sym": _s(q.get("sym"), 24), "mint_short": _short(q.get("mint")), "entry": _f(q.get("entry")), "mark": _f(q.get("mark")), "usd": _f(q.get("usd")), "pnl": _f(q.get("pnl")), "age_h": _f(q.get("age_h"))}
                        for q in (st.get("positions") or []) if isinstance(q, dict)],
             signals=sorted([{"sym": _s(v.get("sym"), 24), "mint_short": _short(m), "entry": bool(v.get("entry")), "st_green": bool(v.get("st_green")), "bb_pos": _f(v.get("bb_pos")), "atr_ratio": _f(v.get("atr_ratio")), "in_universe": bool(v.get("in_universe", True))}
                             for m, v in sig.items() if isinstance(v, dict)], key=lambda x: (not x["entry"], x["sym"]))[:12])
    return h


def _context(root, now):
    """data/context_now.json (context.py, hourly: SOL/BTC returns, news, market heat, breadth, HL bias, health, regime) plus the
    last 24 rows of data/context.jsonl (sparkline of sol.r1h; risk-off count over the 6 most recent hourly rows). Every field is
    passed through typed and None-safe: unknown stays null, enums outside their domain become null, bools stay strict."""
    src = "data/context_now.json"; c, mt = _load_json(_p(root, "data", "context_now.json"))
    if not isinstance(c, dict): raise ValueError("context_now.json no es un objeto")
    h = _hdr(src, _f(c.get("ts")) or mt, now, FRESH["context"])
    D = lambda k: c.get(k) if isinstance(c.get(k), dict) else {}
    sol, btc, nw, mk, br, hl, he, rg = (D(k) for k in ("sol", "btc", "news", "market", "breadth", "hl", "health", "regime"))
    R = lambda d: {k: _f(d.get(k)) for k in ("usd", "r1h", "r4h", "r24h", "rv24h")}
    h.update(code=_s(c.get("code"), 16), hour_utc=_i(c.get("hour_utc"), None), dow=_i(c.get("dow"), None), sol=R(sol),
             btc=dict(R(btc), regime=_enum(btc.get("regime"), BTC_REGIME), regime_age_s=_i(btc.get("regime_age_s"), None)),
             news={"risk_off": _bool(nw.get("risk_off")), "fng": _i(nw.get("fng"), None), "sentiment": _f(nw.get("sentiment")), "sources_ok": _i(nw.get("sources_ok"), None), "age_s": _i(nw.get("age_s"), None)},
             market={"new_pools_1h": _i(mk.get("new_pools_1h"), None), "graduations_1h": _i(mk.get("graduations_1h"), None), "agg_vol_h1_usd": _f(mk.get("agg_vol_h1_usd")),
                     "n_cands_1h": _i(mk.get("n_cands_1h"), None), "heat": _enum(mk.get("heat"), HEAT), "heat_ratio": _f(mk.get("heat_ratio"))},
             breadth={"n_entry": _i(br.get("n_entry"), None), "n_universe": _i(br.get("n_universe"), None), "share": _f(br.get("share")), "med_atr_ratio": _f(br.get("med_atr_ratio"))},
             hl={"sol_bias": _f(hl.get("sol_bias")), "btc_bias": _f(hl.get("btc_bias")), "stress": _s(hl.get("stress"), 24) or None},
             health={"insider_age_s": _i(he.get("insider_age_s"), None), "st_budget_used": _i(he.get("st_budget_used"), None), "st_budget_cap": _i(he.get("st_budget_cap"), None),
                     "x_buzz_age_s": _i(he.get("x_buzz_age_s"), None), "brain_active": _bool(he.get("brain_active")), "director_shadow": _bool(he.get("director_shadow"))},
             regime={"sol_trend": _enum(rg.get("sol_trend"), TREND), "btc_on": _bool(rg.get("btc_on")), "risk_off": _bool(rg.get("risk_off")), "heat": _enum(rg.get("heat"), HEAT)},
             stale=[_s(x, 32) for x in c["stale"] if isinstance(x, str)][:32] if isinstance(c.get("stale"), list) else [])
    hist, herr = [], None
    try:
        lines, _ = _tail_lines(_p(root, "data", "context.jsonl"), 128_000)
        for l in lines[-48:]:
            try: r = json.loads(l)
            except Exception: continue
            t = _f(r.get("ts")) if isinstance(r, dict) else None
            if t is None: continue
            rs, rn, rm = ((r.get(k) if isinstance(r.get(k), dict) else {}) for k in ("sol", "news", "market"))
            hist.append({"ts": t, "r1h": _f(rs.get("r1h")), "risk_off": _bool(rn.get("risk_off")), "heat": _enum(rm.get("heat"), HEAT), "new_pools_1h": _i(rm.get("new_pools_1h"), None)})
        hist.sort(key=lambda x: x["ts"]); hist = hist[-24:]
    except FileNotFoundError: herr = "data/context.jsonl ausente"
    except Exception as e: herr = _err(e)
    last6 = [x for x in hist[-6:] if now - x["ts"] <= 7 * 3600]   # the 6 most recent hourly rows, none older than 7 h (gaps are not bridged)
    h.update(history=hist, history_error=herr, riskoff_6h=sum(1 for x in last6 if x["risk_off"] is True) if last6 else None, riskoff_6h_n=len(last6))
    return h


# ---------------------------------------------------------------- entry point
def build_overview(root, now=None):
    """Everything the v2 panel shows, from files under `root` only. Never raises; see the module docstring."""
    now = float(time.time() if now is None else now); root = os.path.abspath(root)
    cfg, cfg_err = _config(root)
    ex_cfg = cfg.get("exchanges") if isinstance(cfg.get("exchanges"), dict) else {}
    sol_cfg = ex_cfg.get("solana") if isinstance(ex_cfg.get("solana"), dict) else {}
    out = {"meta": _safe(lambda: _meta(root, now, cfg_err, ex_cfg), "config.json + pgrep"),
           "health": _safe(lambda: _health(root, now, ex_cfg), "pgrep + supervisor.log", FRESH["supervisor"]),
           "solana": _safe(lambda: _solana(root, now, sol_cfg), "status_solana.json", FRESH["status"]),
           "insider": _safe(lambda: _insider(root, now), "insider_status.json", FRESH["insider"]),
           "copytrade": _safe(lambda: _copytrade(root, now), "state/copytrade_paper.json", FRESH["copytrade"]),
           "hl": _safe(lambda: _hl(root, now), "hl_leg/hl_paper.json, hl_leg/evidence.json, data/hl_risk.json", FRESH["hl_risk"]),
           "cex": _safe(lambda: _cex(root, now, ex_cfg), "status_binance.json, status_coinbase.json", FRESH["status"]),
           "activity": _safe(lambda: _activity(root, now, ex_cfg), "bot_<ex>.log", FRESH["log"]),
           "director": _safe(lambda: _director(root, now), "director_state.json", FRESH["director"]),
           "operator": _safe(lambda: _operator(root, now), "operator_state.json", FRESH["operator"]),
           "trend": _safe(lambda: _trend(root, now), "state/trend_status.json", FRESH["trend"]),
           "context": _safe(lambda: _context(root, now), "data/context_now.json", FRESH["context"])}
    out["meta"].setdefault("now", now)
    return _sanitize(out)


if __name__ == "__main__":   # quick manual check: python3 dash_data.py [root]
    import sys
    print(json.dumps(build_overview(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))), indent=1, ensure_ascii=False)[:20000])
