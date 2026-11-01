#!/usr/bin/env python3
"""insider_ws: feed en tiempo real de las wallets insider seguidas, por WebSocket de Solana (logsSubscribe mentions=wallet).

Baja la detección de los 70-130 s del sondeo RPC a ~1-3 s. No decide nada: cada notificación (wallet, firma, hora) se añade a
insider_ws_queue.jsonl y insider.live() vacía esa cola en cada ciclo y analiza los swaps por el mismo camino de siempre
(pending_swaps / parse_swap: deduplicado por firma, commitment "confirmed"). El sondeo RPC sigue como red de seguridad cada 10
ciclos mientras el socket está sano, y cada ciclo si no lo está, así que no se pierde nada si el socket cae.
Endpoint público por defecto (SOL_WS o SOL_RPC en el entorno para cambiarlo). Sin el paquete `websockets` el proceso sale sin error."""
import json, os, sys, time, asyncio, logging

log = logging.getLogger("insider_ws")
WS = os.environ.get("SOL_WS") or (os.environ.get("SOL_RPC", "https://api.mainnet-beta.solana.com").replace("https://", "wss://").replace("http://", "ws://"))
F_W, QUEUE, STATUS = "insider_wallets.json", "insider_ws_queue.jsonl", "insider_ws_status.json"
MAX_WALLETS, RELOAD_S, PING_S, HEALTHY_S = 100, 900, 30, 120


def pick_wallets(W, max_wallets=MAX_WALLETS):
    """elite first, then good, by score; capped (public endpoints limit the number of subscriptions)"""
    ws = (W or {}).get("wallets") or {}
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


def healthy(path=STATUS, now=None, max_age=HEALTHY_S):
    """True when the socket process reported 'connected' less than max_age seconds ago"""
    try: s = json.load(open(path))
    except Exception: return False
    return s.get("state") == "connected" and (now or time.time()) - float(s.get("ts") or 0) < max_age


def _status(n_subs, n_events, state):
    try:
        json.dump({"ts": time.time(), "subs": n_subs, "events": n_events, "state": state, "ws": WS}, open(STATUS + ".tmp", "w")); os.replace(STATUS + ".tmp", STATUS)
    except Exception: pass


async def run(stop_file="STOP"):
    import websockets
    backoff = 2
    while not os.path.exists(stop_file):
        try: W = json.load(open(F_W))
        except Exception: W = {}
        wallets = pick_wallets(W)
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
            log.warning("ws %s: reconectando en %s s", str(e)[:120], backoff); _status(0, 0, f"error: {str(e)[:80]}")
            await asyncio.sleep(backoff); backoff = min(60, backoff * 2)
    _status(0, 0, "stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try: import websockets  # noqa: F401
    except ImportError: print("falta el paquete websockets (pip install websockets); el sondeo RPC de insider.py sigue funcionando", file=sys.stderr); sys.exit(0)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    asyncio.run(run())
