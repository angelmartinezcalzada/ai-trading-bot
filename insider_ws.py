#!/usr/bin/env python3
"""insider_ws: feed en tiempo real de las wallets insider seguidas, por WebSocket de Solana (logsSubscribe mentions=wallet).

Baja la detección de los 70-130 s del sondeo RPC a ~1-3 s. No decide nada: cada notificación (wallet, firma, hora) se añade a
insider_ws_queue.jsonl y insider.live() vacía esa cola en cada ciclo y analiza los swaps por el mismo camino de siempre
(pending_swaps / parse_swap: deduplicado por firma, commitment "confirmed"). El sondeo RPC sigue como red de seguridad cada 10
ciclos mientras el socket está sano, y cada ciclo si no lo está, así que no se pierde nada si el socket cae.
Wallets seguidas: las del ranking de fiabilidad (insider_rank.json, elite/good no bot, en el orden de rank['top']) cuando está
fresco; si no, elite y good de insider_wallets.json por puntuación (rank_eligible / pick_wallets, compartidas con insider.live).
Endpoint público por defecto (SOL_WS o SOL_RPC en el entorno para cambiarlo). Sin el paquete `websockets` el proceso sale sin error."""
import json, os, sys, time, asyncio, logging

log = logging.getLogger("insider_ws")
WS = os.environ.get("SOL_WS") or (os.environ.get("SOL_RPC", "https://api.mainnet-beta.solana.com").replace("https://", "wss://").replace("http://", "ws://"))
F_W, QUEUE, STATUS = "insider_wallets.json", "insider_ws_queue.jsonl", "insider_ws_status.json"
MAX_WALLETS, RELOAD_S, PING_S, HEALTHY_S = 100, 900, 30, 120


def _rel(RW, w):
    try: return float((RW.get(w) or {}).get("rel") or 0)
    except Exception: return 0.0


def is_rank(R):
    """a usable reliability-ranking doc (insider_rank.json contract): a dict with a wallets dict"""
    return isinstance(R, dict) and isinstance(R.get("wallets"), dict)


def rank_eligible(R, ws):
    """wallets to follow from the reliability ranking, in rank['top'] order and then the rest by rel: tier elite/good IN THE RANK DOC,
    not flagged bot, and present in insider_wallets.json (`ws`: mining's dev / farm-cluster / min-launch vetoes stay, the ranking only
    narrows the set, never widens it). 'watch', null tier, bot or unknown wallets are never followed, whatever insider_wallets.json says.
    [] when R is not a rank doc."""
    if not is_rank(R): return []
    RW = R["wallets"]; top = [w for w in (R.get("top") or []) if isinstance(w, str)]
    order = dict.fromkeys(top + sorted(RW, key=lambda w: -_rel(RW, w)))
    return [w for w in order if w in (ws or {}) and isinstance(RW.get(w), dict) and RW[w].get("tier") in ("elite", "good") and not RW[w].get("bot")]


def rank_load(root=".", now=None, max_age=7200):
    """fresh rank doc through insider_rank.load (optional module, another engineer's; resolved at call time so a late install or a
    test fake in sys.modules is seen) or None -> callers keep today's behaviour. A doc older than max_age is never trusted."""
    try: import insider_rank
    except ImportError: return None
    try: R = insider_rank.load(root=root)
    except Exception as e: log.warning("rank load %s", str(e)[:80]); return None
    try: fresh = (now or time.time()) - float(R.get("t") or 0) <= max_age if is_rank(R) else False
    except Exception: fresh = False
    return R if fresh else None


def pick_wallets(W, max_wallets=MAX_WALLETS, R=None):
    """with a rank doc R: rank_eligible order (elite/good in the rank, non-bot; an empty verdict is final). Otherwise elite first,
    then good, by mined score; capped (public endpoints limit the number of subscriptions)"""
    ws = (W or {}).get("wallets") or {}
    if is_rank(R): return rank_eligible(R, ws)[:max_wallets]
    ranked = sorted((w for w, o in ws.items() if isinstance(o, dict) and o.get("tier") in ("elite", "good")),
                    key=lambda w: ({"elite": 0, "good": 1}[ws[w]["tier"]], -float(ws[w].get("sc") or 0)))
    return ranked[:max_wallets]


def subscribe_msg(i, wallet):
    return {"jsonrpc": "2.0", "id": i, "method": "logsSubscribe", "params": [{"mentions": [wallet]}, {"commitment": "confirmed"}]}


def on_message(raw, pending, subs):
    """raw JSON text -> ('sub', id, sub_id) | ('event', wallet, signature) | None.
    pending: request id -> wallet (subscribe replies); subs: subscription id -> wallet. Both are mutated."""
    try: m = json.loads(raw)
    except Exception: return None
    if isinstance(m, dict) and "id" in m and "result" in m and m["id"] in pending:
        w = pending.pop(m["id"]); subs[m["result"]] = w; return ("sub", m["id"], m["result"])
    if isinstance(m, dict) and m.get("method") == "logsNotification":
        p = m.get("params") or {}; sub = p.get("subscription"); v = ((p.get("result") or {}).get("value") or {})
        if sub in subs and v.get("signature") and not v.get("err"): return ("event", subs[sub], v["signature"])
    return None


def enqueue(path, wallet, sig, t=None):
    with open(path, "a") as f: f.write(json.dumps({"t": t or time.time(), "w": wallet, "sig": sig}) + "\n")


def drain(path=QUEUE):
    """read AND truncate the queue -> {wallet: [signatures newest-first, deduped]} (consumed by insider.live each cycle)"""
    if not os.path.exists(path): return {}
    try:
        with open(path, "r+") as f: lines = f.readlines(); f.seek(0); f.truncate()
    except Exception: return {}
    out = {}
    for l in lines:
        try: r = json.loads(l)
        except Exception: continue
        if r.get("w") and r.get("sig"): out.setdefault(r["w"], []).append(r["sig"])
    return {w: list(dict.fromkeys(reversed(s))) for w, s in out.items()}


def health(path=STATUS, now=None, max_age=HEALTHY_S):
    """socket status for insider_status.json: {ok, state, ts, age_s, subs, events} or None when the socket process never reported.
    The endpoint URL is left out on purpose (it may carry an API key)."""
    try: s = json.load(open(path))
    except Exception: return None
    if not isinstance(s, dict): return None
    now = now or time.time()
    try: ts = float(s.get("ts") or 0)
    except Exception: ts = 0.0
    return {"ok": s.get("state") == "connected" and now - ts < max_age, "state": str(s.get("state") or "")[:40], "ts": ts, "age_s": round(now - ts, 1),
            "subs": s.get("subs"), "events": s.get("events")}


def healthy(path=STATUS, now=None, max_age=HEALTHY_S):
    """True when the socket process reported 'connected' less than max_age seconds ago"""
    return bool((health(path, now, max_age) or {}).get("ok"))


def _status(n_subs, n_events, state):
    try:
        from urllib.parse import urlsplit
        json.dump({"ts": time.time(), "subs": n_subs, "events": n_events, "state": state, "ws": urlsplit(WS).hostname}, open(STATUS + ".tmp", "w")); os.replace(STATUS + ".tmp", STATUS)   # host only: the URL may carry an API key
    except Exception: pass


async def run(stop_file="STOP"):
    import websockets
    backoff = 2
    while not os.path.exists(stop_file):
        try: W = json.load(open(F_W))
        except Exception: W = {}
        wallets = pick_wallets(W, R=rank_load())                 # reliability ranking when fresh, else the old ordering
        if not wallets: log.warning("sin wallets elite/good en %s: espero 60 s", F_W); _status(0, 0, "no_wallets"); await asyncio.sleep(60); continue
        try:
            async with websockets.connect(WS, ping_interval=PING_S, max_queue=512) as ws:
                pending, subs = {}, {}
                for i, w in enumerate(wallets, 1): pending[i] = w; await ws.send(json.dumps(subscribe_msg(i, w)))
                t0 = time.time(); n = 0; backoff = 2; last_status = 0
                _status(0, 0, "connected"); log.info("suscrito a %d wallets en %s", len(wallets), WS)
                while time.time() - t0 < RELOAD_S and not os.path.exists(stop_file):   # every RELOAD_S the wallet list is re-read and the socket re-opened
                    try: raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError: raw = None
                    r = on_message(raw, pending, subs) if raw else None
                    if r and r[0] == "event": enqueue(QUEUE, r[1], r[2]); n += 1
                    if time.time() - last_status > 20: _status(len(subs), n, "connected"); last_status = time.time()
        except Exception as e:
            log.warning("ws %s: reconectando en %s s", str(e)[:120], backoff); _status(0, 0, f"error: {type(e).__name__}")
            await asyncio.sleep(backoff); backoff = min(60, backoff * 2)
    _status(0, 0, "stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try: import websockets  # noqa: F401
    except ImportError: print("falta el paquete websockets (pip install websockets); el sondeo RPC de insider.py sigue funcionando", file=sys.stderr); sys.exit(0)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    asyncio.run(run())
