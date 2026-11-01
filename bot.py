#!/usr/bin/env python3
"""Multi-exchange crypto bot. One process per exchange (own balance/state/logs). Paper default.
Strategies: momentum (multi-TF pump detection), trend_1h (EMA stack+ADX+Donchian), optional ML direction filter.
Usage: python3 bot.py --exchange binance [--minutes N] [--scan] [--live]"""
import os, sys, re, time, json, csv, logging, argparse, pickle, datetime as dt
import numpy as np, pandas as pd
import intel, swing, features as F
from exchanges import ADAPTERS
log = logging.getLogger("bot")

def ema(x, n): return x.ewm(span=n, adjust=False).mean()
rsi, atr = F.rsi, F.atr
def macd(c): m = ema(c,12)-ema(c,26); s = ema(m,9); return m, s, m-s
def vwap(df, n=60): tp = (df.h+df.l+df.c)/3; return (tp*df.v).rolling(n).sum()/df.v.rolling(n).sum()

def load_model():
    try: return pickle.load(open("model.pkl", "rb"))
    except Exception: return None

def analyze(m, sym, cfg):
    """Momentum + pro layer (regime, S/R, MTF, RS vs BTC, order book). Returns dict with signal/strategy."""
    d1, d5, d15 = m.klines(sym, "1m", 200), m.klines(sym, "5m", 120), m.klines(sym, "15m", 100)
    c1, c5, c15 = d1.c, d5.c, d15.c; price = c1.iloc[-1]
    a = {"price": price, "atr": atr(d1).iloc[-1]*2.2}
    a["chg5"] = (price/c1.iloc[-6]-1)*100; a["vol_ratio"] = d1.v.iloc[-3:].mean()/max(d1.v.iloc[-63:-3].mean(), 1e-12)
    a["rsi1"], a["rsi5"] = rsi(c1).iloc[-1], rsi(c5).iloc[-1]
    _, _, h1 = macd(c1); _, _, h5 = macd(c5)
    a["macd_up"] = h1.iloc[-1] > 0 and h1.iloc[-1] > h1.iloc[-2] and h5.iloc[-1] > h5.iloc[-2]
    a["trend5"] = c5.iloc[-1] > ema(c5,21).iloc[-1] > ema(c5,50).iloc[-1]; a["trend15_ok"] = c15.iloc[-1] > ema(c15,50).iloc[-1]
    a["above_vwap"] = price > vwap(d1).iloc[-1]; a["breakout"] = price > d1.h.iloc[-31:-1].max()
    d1h, d4h = m.klines(sym, "1h", 250), m.klines(sym, "4h", 60)
    a["tf1h_up"] = d1h.c.iloc[-1] > ema(d1h.c,21).iloc[-1]; a["tf4h_up"] = d4h.c.iloc[-1] > ema(d4h.c,21).iloc[-1]
    sup, res = intel.sr_levels(d15); a["support"] = max([x for x in sup if x < price], default=None); a["resistance"] = min([x for x in res if x > price], default=None)
    btc = m.klines(m.btc, "15m", 20).c if sym != m.btc else c15
    a["rs_btc"] = (c15.iloc[-1]/c15.iloc[-17])/(btc.iloc[-1]/btc.iloc[-17])-1
    a["mtf"] = sum([a["trend5"], a["trend15_ok"], a["tf1h_up"], a["tf4h_up"]])
    reg = cfg.get("_regime", {}).get("regime", "range"); a["regime"] = reg
    bbm, bbs = c5.rolling(20).mean().iloc[-1], c5.rolling(20).std().iloc[-1]
    room = (a["resistance"]/price-1)*100 if a["resistance"] else 99
    S = cfg["strategies"]; strat, side = None, 0
    if reg != "bear":
        mom = [a["chg5"] >= cfg["min_change_5m_pct"], a["vol_ratio"] >= cfg["vol_spike_mult"], a["macd_up"], a["above_vwap"],
               a["breakout"], a["rsi1"] < cfg["rsi_max"], a["mtf"] >= 3, a["rs_btc"] > 0]
        if S.get("momentum") and all(mom[:3]) and sum(mom) >= cfg.get("min_score", 7): strat, side = "momentum", 1
        elif S.get("pullback") and reg == "bull" and a["tf1h_up"] and a["tf4h_up"] and a["support"] and abs(price/a["support"]-1) < 0.006 \
                and 35 < a["rsi5"] < 50 and h1.iloc[-1] > h1.iloc[-2] and a["rs_btc"] > 0: strat, side = "pullback", 1
        elif S.get("mean_reversion") and reg == "range" and price < bbm-2*bbs and a["rsi5"] < 30 and h1.iloc[-1] > h1.iloc[-2] and a["tf4h_up"]:
            strat, side = "mean_reversion", 1
    if side and room < 0.4: strat, side = strat+"-blocked_resistance", 0
    a["strategy"], a["side"] = strat, side
    a["tp_mult"] = {"momentum": 1.0, "pullback": 1.3, "mean_reversion": 0.8}.get(strat, 1.0)
    a["feat1h"] = (d1h, btc)
    return a

def trend_check(m, sym, btc1h):
    """1h trend-following signal on last CLOSED bar: +1/-1/0, plus ATR(1h) and features row."""
    d = m.klines(sym, "1h", 300)
    if len(d) < 220: return 0, None, None
    b = btc1h.set_index("t").c.reindex(d.t).ffill().values if btc1h is not None else None
    f = F.build(d, pd.Series(b, index=d.index) if b is not None else None)
    return int(F.trend_signal(f).iloc[-1]), float(f.atr.iloc[-1]), f.iloc[[-1]]

class Bot:
    def __init__(s, cfg, ex, live=False):
        s.cfg = {**cfg, **cfg["exchanges"][ex]}; s.ex = ex; s.m = ADAPTERS[ex](s.cfg); s.live = live
        tag = f"{ex}_{'live' if live else 'paper'}"
        s.csv, s.state_file = f"trades_{tag}.csv", f"state_{tag}.json"
        s.cash = s.cfg["starting_equity"]; s.pos = {}; s.cool = {}; s.trades = []; s.pending = {}
        s.day = dt.date.today(); s.day_start = s.cash; s.deposits = []; s.halted = False; s.hist = []; s.reg = {}; s.reg_t = 0; s.trend_t = 0
        s.sent = intel.Sentiment(); s.model = load_model()
        s.signals, s.movers, s.paused, s.eq_t = [], [], False, 0
        s.cfg_path = cfg.get("_path", "config.json"); s.cfg_mtime = os.path.getmtime(s.cfg_path)
        if not os.path.exists(s.csv):
            with open(s.csv, "w", newline="") as f: csv.writer(f).writerow("time exchange symbol side price qty fee pnl reason equity".split())
        s.load(); s.universe()
        s.ext = {}
        tk, mk = s.cfg["fee_taker_pct"], s.cfg["fee_maker_pct"]
        if s.cfg.get("bnb_fee_discount"): tk, mk = tk*0.75, mk*0.75
        s.fee_t, s.fee_m = tk/100, mk/100
        if live: import live_cb; live_cb.init(s)
        log.info("[%s] fees taker=%.4f%% maker=%.4f%% order_mode=%s short=%s", ex, s.fee_t*100, s.fee_m*100, s.cfg["entry_order"], s.cfg.get("allow_short"))
    # ---------- state ----------
    def load(s):
        if os.path.exists(s.state_file):
            st = json.load(open(s.state_file))
            s.cash, s.pos, s.cool, s.trades = st["cash"], st["pos"], st["cool"], st["trades"]
            s.day, s.day_start, s.halted = dt.date.fromisoformat(st["day"]), st["day_start"], st["halted"]
            s.deposits = st.get("deposits", [])
            for p in s.pos.values():
                p.setdefault("side", 1); p.setdefault("best", p.get("high", p["entry"]))
                for k, v in (("trail_on", s.cfg["trail_activate_atr"]), ("trail", s.cfg["trail_atr_mult"]), ("hold", s.cfg["max_hold_minutes"]), ("strategy", "momentum")): p.setdefault(k, v)
            log.info("[%s] STATE restored cash=%.2f open=%s closed=%d", s.ex, s.cash, list(s.pos), len(s.trades))
    def save(s):
        st = {"cash": s.cash, "pos": s.pos, "cool": s.cool, "trades": s.trades, "day": s.day.isoformat(), "day_start": s.day_start, "halted": s.halted, "deposits": getattr(s, "deposits", [])}
        json.dump(st, open(s.state_file+".tmp", "w"), default=float); os.replace(s.state_file+".tmp", s.state_file)
    def universe(s):
        s.symbols = s.m.universe(s.cfg["min_quote_volume_24h"]); s.uni_t = time.time()
        log.info("[%s] UNIVERSE %d pairs (top: %s)", s.ex, len(s.symbols), ", ".join(s.symbols[:12]))
    def equity(s, px):
        return s.cash + sum(p["cost"] + p["side"]*p["qty"]*(px.get(k, p.get("mark", p["entry"]))-p["entry"]) for k, p in s.pos.items())
    def record(s, sym, side, px, qty, fee, pnl, reason, eq):
        row = [dt.datetime.now().isoformat(timespec="seconds"), s.ex, sym, side, f"{px:.6g}", f"{qty:.6g}", f"{fee:.4f}", f"{pnl:.4f}", reason, f"{eq:.2f}"]
        with open(s.csv, "a", newline="") as f: csv.writer(f).writerow(row)
        if side in ("SELL", "COVER"): s.trades.append(pnl)
        log.info("TRADE %s", " | ".join(row))
    # ---------- execution ----------
    def open_pos(s, sym, side, size, bid, ask, A, strat, stop_mult, tp_mult, hold_min, note, trail_on, trail):
        if side == -1 and not s.cfg.get("allow_short"): return
        maker = s.cfg["entry_order"] == "maker"
        if s.live:
            if side == -1: log.warning("live short not enabled in this build (needs futures/margin adapter)"); return
            import live_cb; return live_cb.open_pos(s, sym, size, A, strat, stop_mult, tp_mult, hold_min, note, trail_on, trail)
        if maker:   # post-only at best bid/ask; fill only if market trades through within timeout
            s.pending[sym] = dict(side=side, size=size, limit=bid if side == 1 else ask, t=time.time(), A=A, strat=strat, stop_mult=stop_mult,
                                  tp_mult=tp_mult, hold=hold_min, note=note, trail_on=trail_on, trail=trail)
            s.cash -= size; log.info("[%s] MAKER order %s %s @%.6g size=%.2f (%s)", s.ex, "BUY" if side == 1 else "SHORT", sym, s.pending[sym]["limit"], size, note)
        else:
            px = ask*(1+s.cfg["slippage_pct"]/100) if side == 1 else bid*(1-s.cfg["slippage_pct"]/100)
            s.cash -= size; s._fill(sym, side, size, px, s.fee_t, A, strat, stop_mult, tp_mult, hold_min, note, trail_on, trail)
    def _fill(s, sym, side, size, px, fee_rate, A, strat, stop_mult, tp_mult, hold_min, note, trail_on, trail):
        fee = size*fee_rate; qty = (size-fee)/px
        s.pos[sym] = {"side": side, "entry": px, "qty": qty, "cost": size, "atr": A, "best": px, "t": time.time(), "strategy": strat,
                      "stop": px - side*stop_mult*A, "tp": px + side*tp_mult*A, "hold": hold_min, "trail_on": trail_on, "trail": trail}
        s.record(sym, "BUY" if side == 1 else "SHORT", px, qty, fee, 0, f"{strat} {note}", s.equity({}))
    def check_pending(s, px):
        for sym, o in list(s.pending.items()):
            last = px.get(sym)
            hit = last is not None and ((o["side"] == 1 and last < o["limit"]) or (o["side"] == -1 and last > o["limit"]))
            if hit:
                del s.pending[sym]
                s._fill(sym, o["side"], o["size"], o["limit"], s.fee_m, o["A"], o["strat"], o["stop_mult"], o["tp_mult"], o["hold"], o["note"]+" maker", o["trail_on"], o["trail"])
            elif time.time()-o["t"] > s.cfg["maker_timeout_s"]:
                del s.pending[sym]; s.cash += o["size"]; log.info("[%s] maker order %s expired unfilled", s.ex, sym)
    def close(s, sym, bid, ask, reason, px):
        if s.live: import live_cb; return live_cb.close(s, sym, reason, px)
        p = s.pos.pop(sym); side = p["side"]
        x = bid*(1-s.cfg["slippage_pct"]/100) if side == 1 else ask*(1+s.cfg["slippage_pct"]/100)
        gross = p["qty"]*x; fee = gross*s.fee_t
        pnl = side*p["qty"]*(x-p["entry"]) - fee - (p["cost"]-p["qty"]*p["entry"])
        s.cash += p["cost"] + pnl; s.cool[sym] = time.time()+s.cfg["cooldown_minutes"]*60
        s.record(sym, "SELL" if side == 1 else "COVER", x, p["qty"], fee, pnl, f"{p['strategy']}:{reason}", s.equity(px))
    def manage(s, px):
        for sym in list(s.pos):
            p = s.pos[sym]
            try: bid, ask = s.m.book(sym)
            except Exception: continue
            if bid <= 0 or ask <= 0 or (ask-bid)/ask > s.cfg.get("max_exit_spread_pct", 2.0)/100:
                log.warning("[%s] %s bad book bid=%s ask=%s -> exit checks skipped this cycle", s.ex, sym, bid, ask); continue
            mark = bid if p["side"] == 1 else ask; d = p["side"]; p["mark"] = (bid+ask)/2
            hit = d*(mark-p["stop"]) <= 0 or -d*p["qty"]*(mark-p["entry"]) > s.equity(px)*s.cfg.get("max_trade_loss_pct", 0.03)
            if s.live:   # live: an exit trigger must persist on 2 consecutive checks (filters bad ticks)
                p["hits"] = p.get("hits", 0)+1 if hit else 0
                if hit and p["hits"] < 2: log.info("[%s] %s exit trigger seen once (mark=%.6g stop=%.6g), confirming next cycle", s.ex, sym, mark, p["stop"]); continue
            p["best"] = max(p["best"], mark) if d == 1 else min(p["best"], mark)
            if d*(p["best"]-p["entry"]) >= p["trail_on"]*p["atr"]:
                nst = p["best"] - d*p["trail"]*p["atr"]; p["stop"] = max(p["stop"], nst) if d == 1 else min(p["stop"], nst); p["trailing"] = True
            if -d*p["qty"]*(mark-p["entry"]) > s.equity(px)*s.cfg.get("max_trade_loss_pct", 0.03): s.close(sym, bid, ask, "max_trade_loss", px)
            elif d*(mark-p["stop"]) <= 0: s.close(sym, bid, ask, "trail" if p.get("trailing") else "stop", px)
            elif d*(mark-p["tp"]) >= 0: s.close(sym, bid, ask, "take_profit", px)
            elif time.time()-p["t"] > p["hold"]*60: s.close(sym, bid, ask, "time_exit", px)
    # ---------- sizing (ensemble) ----------
    def size_for(s, sym, px, strat, prob=None):
        c = s.cfg; base = s.m.base_of(sym)
        if base in s.sent.delist: log.info("%s skip: delisting", sym); return 0, ""
        cs = s.sent.coin(base)
        if cs <= -2: log.info("%s skip: negative news %.1f", sym, cs); return 0, ""
        mult = s.sent.market_mult()*(1+0.1*cs)*(1.2 if base in s.sent.listings else 1)*(0.7 if s.reg.get("btc_vol_pct", 0) > 1.5 else 1)
        if prob is not None: mult *= 0.5 + prob          # ML probability tilts size (0.5..1.5x)
        mult *= c["strategy_size"].get(strat, 1.0)
        size = min(s.equity(px)*c["risk_per_trade_pct"]*max(0.3, min(1.5, mult)), s.cash*0.99)
        return (size if size >= c["min_order_quote"] else 0), f"{s.reg.get('regime')} news{cs:+.0f} fng{s.sent.fng} x{mult:.2f}" + (f" p{prob:.2f}" if prob is not None else "")
    def ml_prob(s, frow):
        if s.model is None or frow is None: return None
        try: return float(s.model.predict_proba(frow[F.FEATS])[0, 1])
        except Exception: return None
    # ---------- main step ----------
    def reload_cfg(s):
        try:
            mt = os.path.getmtime(s.cfg_path)
            if mt != s.cfg_mtime:
                cfg = json.load(open(s.cfg_path)); s.cfg_mtime = mt
                keep = {k: v for k, v in s.cfg.items() if k.startswith("_")}
                s.cfg = {**cfg, **cfg["exchanges"][s.ex], **keep}
                tk, mk = s.cfg["fee_taker_pct"], s.cfg["fee_maker_pct"]
                if s.cfg.get("bnb_fee_discount"): tk, mk = tk*0.75, mk*0.75
                s.fee_t, s.fee_m = tk/100, mk/100; log.info("[%s] config reloaded", s.ex)
        except Exception as e: log.warning("config reload failed %s", e)
    def control(s, px):
        f = f"control_{s.ex}.json"
        try: ctl = json.load(open(f)) if os.path.exists(f) else {}
        except Exception: ctl = {}
        s.paused = bool(ctl.get("pause"))
        if ctl.get("close"):
            for sym in ctl["close"]:
                if sym in s.pos:
                    b, a = s.m.book(sym); s.close(sym, b, a, "manual_close", px)
                elif sym in s.pending: o = s.pending.pop(sym); s.cash += o["size"]; log.info("[%s] pending %s cancelled manually", s.ex, sym)
            ctl["close"] = []; json.dump(ctl, open(f + ".tmp", "w")); os.replace(f + ".tmp", f)
    def write_status(s, px, eq, dd):
        pos = []
        for k, p in s.pos.items():
            mark = px.get(k, p.get("mark", p["entry"])); pnl = p["side"]*p["qty"]*(mark-p["entry"]) - (p["cost"]-p["qty"]*p["entry"])
            pos.append({"sym": k, "side": "LONG" if p["side"] == 1 else "SHORT", "strategy": p.get("strategy"), "entry": p["entry"], "mark": mark,
                        "qty": p["qty"], "cost": p["cost"], "pnl": pnl, "pnl_pct": pnl/p["cost"]*100, "stop": p["stop"], "tp": p["tp"],
                        "age_min": (time.time()-p["t"])/60, "trailing": bool(p.get("trailing")), "lv": p.get("lv"), "exit_blocked": p.get("exit_blocked")})
        t = np.array(s.trades)
        st = {"exchange": s.ex, "mode": "live" if s.live else "paper", "ts": time.time(), "equity": eq, "cash": s.cash, "day_pnl_pct": dd*100,
              "halted": s.halted, "paused": s.paused, "external_holdings": getattr(s, "ext", {}), "deposits": getattr(s, "deposits", []), "net_deposits": round(sum(d["usd"] for d in getattr(s, "deposits", [])), 2), "no_cash": bool(s.live and s.cash < s.cfg.get("min_order_quote", 1)), "regime": {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in s.reg.items()},
              "fng": s.sent.fng, "headlines": s.sent.heads[:15], "delist": sorted(s.sent.delist), "listings": sorted(s.sent.listings),
              "universe": len(s.symbols), "positions": pos, "pending": [{"sym": k, **{kk: o[kk] for kk in ("side", "size", "limit", "strat")}} for k, o in s.pending.items()],
              "signals": s.signals[-60:], "movers": s.movers,
              "stats": {"closed": len(t), "win_rate": float((t > 0).mean()*100) if len(t) else None, "net_pnl": float(t.sum()) if len(t) else 0.0}}
        json.dump(st, open(f"status_{s.ex}.json.tmp", "w"), default=float); os.replace(f"status_{s.ex}.json.tmp", f"status_{s.ex}.json")
        if time.time()-s.eq_t >= 30:
            s.eq_t = time.time()
            with open(f"equity_{s.ex}.csv", "a") as f: f.write(f"{int(time.time())},{eq:.4f}\n")
    def step(s):
        s.reload_cfg(); c = s.cfg
        if dt.date.today() != s.day: s.day, s.halted = dt.date.today(), False; s.day_start = s.equity({})
        if time.time()-s.uni_t > c["universe_refresh_minutes"]*60: s.universe()
        books = s.m.books(); px = {k: (b+a)/2 for k, (b, a) in books.items() if a > 0}
        now = time.time(); s.hist.append((now, px)); s.hist = [h for h in s.hist if now-h[0] <= 900]
        ref = next((h[1] for h in s.hist if now-h[0] <= 300), px)
        s.control(px); s.check_pending(px); s.manage(px)
        eq = s.equity(px)
        if s.live: import live_cb; live_cb.guard(s, px, eq); eq = s.equity(px)
        dd = eq/s.day_start-1 if s.day_start >= 1 else 0.0
        if dd <= -c["daily_max_drawdown_pct"] and not s.halted:
            s.halted = True; log.warning("[%s] KILL SWITCH dd=%.2f%%", s.ex, dd*100)
            for sym in [k for k, p in s.pos.items() if p.get("strategy") not in ("breakout_4h", "xs_rotation_4h")]: b, a = s.m.book(sym); s.close(sym, b, a, "kill_switch", px)
        try:
            if now-s.reg_t > 300:
                s.reg = intel.regime(s.m); s.reg_t = now; c["_regime"] = s.reg; log.info("[%s] REGIME %s", s.ex, s.reg)
        except Exception as e: log.warning("regime fail %s", e)
        s.sent.refresh()
        log.info("[%s] equity=%.2f cash=%.2f open=%s pending=%s dayPnL=%.2f%% regime=%s", s.ex, eq, s.cash, list(s.pos), list(s.pending), dd*100, s.reg.get("regime"))
        if not (s.halted or s.paused):
            try: swing.run(s, px)
            except Exception as e: log.exception("swing error %s", e)
        s.write_status(px, eq, dd)
        if s.halted or s.paused: return
        busy = lambda: len(s.pos)+len(s.pending) >= c["max_positions"]
        # --- 1h trend-following scan (once per hour after candle close) ---
        if c["strategies"].get("trend_1h") and now-s.trend_t > 3600 and dt.datetime.now().minute >= 1:
            s.trend_t = now - (now % 3600) + 60
            try: btc1h = s.m.klines(s.m.btc, "1h", 300)
            except Exception: btc1h = None
            n = 0
            for sym in s.symbols[:c["trend_universe_top"]]:
                if busy(): break
                if sym in s.pos or sym in s.pending or s.cool.get(sym, 0) > now: continue
                try: sig, A, frow = trend_check(s.m, sym, btc1h)
                except Exception as e: log.debug("trend %s %s", sym, e); continue
                n += 1
                s.signals.append({"t": dt.datetime.now().strftime("%H:%M:%S"), "sym": sym, "type": "trend_1h-scan", "strategy": "trend_1h" if sig else "-", "side": sig,
                                  "chg5": None, "vol": round(float(frow.volr.iloc[0]), 2) if frow is not None else None, "rsi": round(float(frow.rsi.iloc[0]), 1) if frow is not None else None,
                                  "mtf": None, "rs": round(float(frow.rs24.iloc[0])*100, 2) if frow is not None else None})
                if sig == 0 or (sig == 1 and s.reg.get("regime") == "bear") or (sig == -1 and s.reg.get("regime") == "bull"): continue
                p = s.ml_prob(frow)
                if c["strategies"].get("ml_filter") and p is not None and ((sig == 1 and p < c["ml_min_prob"]) or (sig == -1 and p > 1-c["ml_min_prob"])): continue
                size, note = s.size_for(sym, px, "trend_1h", p)
                if size <= 0: continue
                b, a = s.m.book(sym)
                s.open_pos(sym, sig, size, b, a, A, "trend_1h", c["trend_stop_atr"], c["trend_tp_atr"], c["trend_hold_minutes"], note, 1.0, c["trend_trail_atr"])
            log.info("[%s] trend_1h scan checked %d pairs", s.ex, n)
        if s.reg.get("regime") == "bear" and not c.get("allow_short"): return
        # --- momentum / pullback / mean-reversion on top short-term movers ---
        mom = {k: px[k]/ref[k]-1 for k in s.symbols if k in px and k in ref}
        movers = sorted(mom, key=lambda k: -mom[k])[:c["deep_scan_top"]]
        s.movers = [{"sym": k, "chg5": round(mom[k]*100, 3)} for k in movers[:12]]
        log.info("[%s] scanned %d pairs; top 5m: %s", s.ex, len(mom), ", ".join(f"{k}{mom[k]*100:+.2f}%" for k in movers[:6]))
        for sym in movers:
            if os.path.exists(f"STOP_{s.ex}") or os.path.exists("STOP"): break
            s.control(px)
            if s.paused or busy(): break
            if sym in s.pos or sym in s.pending or s.cool.get(sym, 0) > now: continue
            try:
                b, a = s.m.book(sym); spread = (a-b)/a*100
                if spread > c["max_spread_pct"]: continue
                an = analyze(s.m, sym, c)
            except Exception as e: log.warning("%s analysis failed: %s", sym, e); continue
            s.signals.append({"t": dt.datetime.now().strftime("%H:%M:%S"), "sym": sym, "type": "momentum-scan", "strategy": an["strategy"] or "-", "side": an["side"],
                              "chg5": round(an["chg5"], 2), "vol": round(an["vol_ratio"], 2), "rsi": round(float(an["rsi1"]), 1), "mtf": an["mtf"], "rs": round(an["rs_btc"]*100, 2)})
            s.write_status(px, s.equity(px), s.equity(px)/s.day_start-1)
            if not an["side"]: continue
            if intel.book_imbalance_lv(*s.m.depth(sym)) < -0.35: log.info("%s blocked by order book", sym); continue
            size, note = s.size_for(sym, px, an["strategy"])
            if size <= 0: continue
            s.open_pos(sym, an["side"], size, b, a, an["atr"], an["strategy"], c["atr_stop_mult"], c["take_profit_atr_mult"]*an["tp_mult"],
                       c["max_hold_minutes"], f"{note} mtf{an['mtf']} chg5={an['chg5']:.2f}% vol={an['vol_ratio']:.1f}x spr={spread:.3f}%",
                       c["trail_activate_atr"], c["trail_atr_mult"])
    def summary(s):
        t = np.array(s.trades)
        out = {"exchange": s.ex, "closed_trades": len(t), "win_rate": float((t > 0).mean()) if len(t) else None,
               "net_pnl": float(t.sum()) if len(t) else 0.0, "open": list(s.pos), "cash": round(s.cash, 2)}
        json.dump(out, open(f"summary_{s.ex}.json", "w"), indent=2); log.info("SUMMARY %s", out); return out
    def run(s, minutes=None):
        end = time.time()+minutes*60 if minutes else None
        try:
            while (not end or time.time() < end) and not os.path.exists(f"STOP_{s.ex}") and not os.path.exists("STOP"):
                try: s.step(); s.save()
                except Exception as e: log.exception("step error: %s", e)
                for _ in range(int(s.cfg["poll_seconds"])):
                    if os.path.exists(f"STOP_{s.ex}") or os.path.exists("STOP"): break
                    time.sleep(1)
        except KeyboardInterrupt: pass
        s.save(); s.summary()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--config", default="config.json"); ap.add_argument("--exchange", default="binance")
    ap.add_argument("--minutes", type=float); ap.add_argument("--live", action="store_true"); ap.add_argument("--scan", action="store_true"); ap.add_argument("-v", action="store_true")
    a = ap.parse_args(); cfg = json.load(open(a.config)); cfg["_path"] = a.config
    try:   # one bot per exchange per machine: a duplicate (two supervisors, a stray launch) would trade the same wallet twice
        import subprocess
        others = [int(x) for x in subprocess.run(["pgrep", "-f", f"python3 bot.py --exchange {a.exchange}( |$)"], capture_output=True, text=True, timeout=3).stdout.split() if x.isdigit() and int(x) != os.getpid()]
        if others: sys.exit(f"otro bot.py --exchange {a.exchange} ya corre (pid {others[0]}); este se cierra")
    except SystemExit: raise
    except Exception: pass
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(f"bot_{a.exchange}.log")])
    if a.exchange == "solana":
        import memebot; memebot.main(cfg, a.live and cfg["exchanges"]["solana"].get("mode") == "live"); sys.exit()
    live = a.live and cfg["exchanges"][a.exchange].get("mode") == "live"
    keys = {"binance": "BINANCE_API_KEY", "coinbase": "COINBASE_API_KEY"}
    if a.live and not (live and os.environ.get("LIVE_CONFIRM") == "YES" and (os.environ.get(keys.get(a.exchange, "X")) or (a.exchange == "solana" and os.path.exists("solana_wallet.json")))):   # Solana signs with solana_wallet.json, not an env var
        sys.exit(f"Live refused: need exchanges.{a.exchange}.mode=live, API key env vars and LIVE_CONFIRM=YES")
    b = Bot(cfg, a.exchange, live)
    if a.scan:
        for sym in b.symbols[:15]:
            try: an = analyze(b.m, sym, b.cfg); print(f"{sym:14} {an['strategy']} side={an['side']} chg5={an['chg5']:+.2f}% vol={an['vol_ratio']:.1f}x mtf={an['mtf']} rs={an['rs_btc']*100:+.1f}%")
            except Exception as e: print(sym, "err", e)
        sys.exit()
    log.warning("[%s] MODE: %s", a.exchange, "LIVE" if live else "PAPER")
    b.run(a.minutes)
