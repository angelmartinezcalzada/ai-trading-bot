"""Builds canvas_data.json (compact snapshot for the 'Panel del bot de trading' Page) from status/trade files."""
import json, csv, time, datetime as dt, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
cfg = json.load(open("config.json")); out = {"generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "venues": []}
start = {"binance": 1000, "coinbase": 1000, "solana": 1000}
for ex in ("binance", "coinbase", "solana"):
    try: st = json.load(open(f"status_{ex}.json"))
    except Exception: continue
    mode = st.get("mode") or cfg["exchanges"][ex].get("mode", "paper"); tr = []     # actual running mode (solana switches to live by wallet balance)
    try: tr = list(csv.DictReader(open(f"trades_{ex}_{mode}.csv")))[-10:][::-1]
    except Exception: pass
    eq = round(st.get("equity", 0), 2); s0 = cfg["exchanges"][ex].get("starting_equity", start[ex]) + (st.get("net_deposits") or 0)
    base = "start"
    if ex == "solana" and mode == "live":
        try: s0 = json.load(open("state_solana_live.json"))["day_start"]; base = "day_start_live"
        except Exception: s0 = eq
    reg = st.get("regime") or {}; br = (st.get("brain") or {}).get("model") or {}; ctx = (st.get("brain") or {}).get("ctx") or {}
    out["venues"].append({"ex": ex, "mode": mode, "real": mode == "live", "pnl_base": base, "base_equity": round(s0, 2), "day_pnl_pct": round(st.get("day_pnl_pct") or 0, 2), "wallet": st.get("wallet") if ex == "solana" else None, "equity": eq, "pnl": round(eq-s0, 2), "pnl_pct": round((eq/s0-1)*100, 2), "cash": round(st.get("cash", 0), 2),
        "updated": dt.datetime.fromtimestamp(st.get("ts", 0)).strftime("%H:%M:%S"), "regime": reg.get("regime"),
        "positions": [{"sym": p["sym"], "strat": p.get("strategy"), "cost": round(p.get("cost", 0), 2), "pnl": round(p.get("pnl", 0), 2), "pnl_pct": round(p.get("pnl_pct", 0), 2), "pump": p.get("pump"), "exh": p.get("exh"), "lv": {k: v for k, v in (p.get("lv") or {}).items() if k in ("atr_pct","vol_mult","stop_pct","tp_pct","trail_w","act_pct","sup","res")} or None, "stop": p.get("stop"), "tp": p.get("tp")} for p in st.get("positions", [])],
        "trades": [{"t": t["time"][5:16].replace("T", " "), "sym": t["symbol"], "side": t["side"], "pnl": float(t["pnl"]), "reason": t["reason"].split(" ")[0][:28]} for t in tr],
        "ai_pump": [{k: x[k] for k in ("sym", "pump", "exh", "sig_pump", "sig_exh", "held")} for x in st.get("ai_pump", [])][:10], "closed": (st.get("stats") or {}).get("closed_trades") or (st.get("stats") or {}).get("closed"),
        "brain": {"active": br.get("active"), "n": br.get("n_labelled"), "playbook": (ctx.get("playbook") or {}).get("name"), "heat": ctx.get("heat"),
                  "narr": ctx.get("narratives", [])[:6], "oos": (br.get("oos") or {}).get("note") or br.get("oos")} if br else None})
try:
    ns = json.load(open("news_state.json"))
    out["news"] = {"risk_off": ns["risk_off"], "fng": ns.get("fng"), "sentiment": ns.get("sentiment"), "sources_ok": list(ns.get("sources_ok", {})),
                   "top": [{"t": dt.datetime.fromtimestamp(n["ts"]).strftime("%H:%M"), "src": n["src"], "title": n["title"], "imp": n["imp"], "sent": n["sent"], "coins": n["coins"], "url": n["url"]} for n in ns.get("top", [])[:8]]}
except Exception: out["news"] = None
json.dump(out, open("canvas_data.json", "w"), indent=1); print(json.dumps(out))
