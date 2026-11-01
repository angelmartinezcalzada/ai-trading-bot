"""Hourly Hyperliquid context logger for the CFO review and the dashboard.

Reads Coinversa Pulse (if COINVERSA_API_KEY is set) for every coin in the Keel strategy universe and appends one row per
coin to data/hl_context.csv, plus a compact data/hl_risk.json {coin: {flags_long, flags_short, size_mult, ...}}.
It never trades and never blocks: without a key it writes nothing and exits 0.

Usage:  python3 -m hl_leg.hl_context --once        (one pass)
        python3 -m hl_leg.hl_context                (loop every HL_CONTEXT_SECONDS, default 3600)
"""
from __future__ import annotations
import csv, json, os, sys, time, logging
from .coinversa import CoinversaClient, context_row, risk_flags, size_multiplier
log = logging.getLogger("hl.context")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
UNIVERSE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategies", "universe.json")
FIELDS = ["time", "coin", "apex", "sharps", "crowd", "oi", "near_liq", "avg_leverage", "flags_long", "flags_short"]


def load_universe(path: str = UNIVERSE_FILE) -> list[str]:
    try:
        u = json.load(open(path))
        return list(u.get("symbols") or u) if isinstance(u, (dict, list)) else []
    except Exception as e:
        log.warning("universe file %s unreadable: %s", path, e); return ["BTC", "ETH", "SOL"]


def one_pass(client: CoinversaClient, coins: list[str], data_dir: str = DATA, now: float | None = None) -> dict:
    """Fetch context for every coin, append CSV rows, write hl_risk.json. Returns the risk dict (empty if disabled)."""
    if not client.enabled:
        log.info("COINVERSA_API_KEY not set: context logging disabled"); return {}
    os.makedirs(data_dir, exist_ok=True)
    csv_path, json_path = os.path.join(data_dir, "hl_context.csv"), os.path.join(data_dir, "hl_risk.json")
    new = not os.path.exists(csv_path)
    risk: dict = {}; ok = failed = 0
    with open(csv_path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new: w.writeheader()
        for coin in coins:
            bias, snap = client.cohort_bias(coin), client.risk_snapshot(coin)
            if bias is None and snap is None: failed += 1; continue
            ok += 1
            row = context_row(coin, bias, snap, ts=now)
            w.writerow(row)
            fl, fs = risk_flags("long", bias, snap), risk_flags("short", bias, snap)
            risk[coin] = {"flags_long": fl, "flags_short": fs, "size_mult_long": size_multiplier(fl),
                          "size_mult_short": size_multiplier(fs), "apex": row["apex"], "crowd": row["crowd"], "time": row["time"]}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() if now is None else now))
    try: prev = json.load(open(json_path))
    except Exception: prev = {}
    if ok == 0:   # every call failed (wrong key / wrong REST paths / outage): keep the last good snapshot and say so, never a fresh-looking empty file
        out = {**prev, "status": "degraded", "last_attempt": stamp, "ok": 0, "failed": failed, "coins": prev.get("coins", {})}
        if "updated" not in out: out["updated"] = None
    else:
        out = {"updated": stamp, "status": "ok" if failed == 0 else "partial", "ok": ok, "failed": failed, "coins": risk}
    tmp = json_path + ".tmp"
    json.dump(out, open(tmp, "w"), indent=1); os.replace(tmp, json_path)
    if ok == 0: log.warning("hl_context: 0/%d coins answered (status degraded); check COINVERSA_API_KEY / endpoints", failed)
    return risk


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = CoinversaClient()
    coins = load_universe()
    if "--once" in argv:
        r = one_pass(client, coins); print(json.dumps(r, indent=1)); return 0
    period = int(os.environ.get("HL_CONTEXT_SECONDS", "3600")); stop_file = os.path.join(HERE, "STOP")
    while not os.path.exists(stop_file):   # the supervisor's STOP file ends this loop too
        try: one_pass(client, coins)
        except Exception as e: log.warning("context pass failed: %s", e)
        for _ in range(max(1, period // 30)):
            if os.path.exists(stop_file): break
            time.sleep(30)
    log.info("hl_context: STOP present, exiting"); return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
