"""Coinbase LIVE execution layer: real balances, preview, min sizes, confirmed fills, reconciliation, kill switch."""
import time, logging, os
log = logging.getLogger("live_cb")
STABLE = ("USD", "USDC")

def tsym(bot, sym):   # account has USDC, not USD -> route X-USD to X-USDC when USD cash is smaller
    base, q = sym.split("-")
    # EU account: no USD account exists ("account is not available" on X-USD orders) -> always X-USDC unless a USD account exists with more cash
    if q == "USD" and ("USD" not in bot.bal or bot.bal.get("USDC", (0, 0))[0] > bot.bal.get("USD", (0, 0))[0]): return f"{base}-USDC"
    return sym

def sync(bot):
    try: bot.bal = bot.m.live_balances()
    except Exception as e: log.warning("[coinbase LIVE] balance sync failed %s", e); return
    cash = sum(bot.bal.get(c, (0, 0))[0] for c in STABLE)
    quiet = not bot.pending and time.time()-getattr(bot, "order_t", 0) > 180 and getattr(bot, "sync_t", 0) > 0
    if quiet:   # external outflows (user conversions/sends): not trading losses -> lower the baseline, track as negative deposit
        out = 0.0
        if getattr(bot, "last_cash", None) is not None and cash < bot.last_cash-0.05: out += bot.last_cash-cash
        for sym, p in bot.pos.items():
            have = sum(bot.bal.get(sym.split("-")[0], (0, 0)))
            if have < p["qty"]*0.999:
                k = have/p["qty"] if p["qty"] else 0; out += (p["qty"]-have)*p.get("mark", p["entry"]); p["cost"] *= k; p["qty"] = have
        if out > 0.05: withdrawal(bot, out)
    bot.cash = cash; bot.last_cash = cash
    managed = {k.split("-")[0] for k in bot.pos}
    bot.ext = {c: v[0]+v[1] for c, v in bot.bal.items() if c not in STABLE and c not in managed}
    bot.sync_t = time.time()

def init(bot):
    bot.bal, bot.ext, bot.sync_t = {}, {}, 0
    try: bot.fee_t, bot.fee_m = bot.m.live_fee_rates()
    except Exception as e: log.warning("fee tier read failed %s (using config)", e)
    sync(bot)
    for sym, p in list(bot.pos.items()):   # reconcile restored state with the exchange
        have = sum(bot.bal.get(sym.split("-")[0], (0, 0)))
        if have > 0 and have < p["qty"]:     # partial external outflow: keep the position at the real qty (sync() books the outflow)
            pass
        elif have < p["qty"]*0.95:
            log.warning("[coinbase LIVE] RECONCILE drop %s: state qty=%.8g exchange=%.8g", sym, p["qty"], have); bot.pos.pop(sym)
        elif have < p["qty"]: p["qty"] = have
    fresh = not os.path.exists(bot.state_file)
    bot.pending = {}; sync(bot); new = adopt(bot)
    if fresh or bot.day_start < 1: bot.day_start = bot.equity({})
    else: deposit(bot, new)
    bot.save()
    log.warning("[coinbase LIVE] fees taker=%.3f%% maker=%.3f%% cash(USD+USDC)=%.4f managed=%s external(not traded)=%s",
                bot.fee_t*100, bot.fee_m*100, bot.cash, list(bot.pos), {k: round(v, 4) for k, v in bot.ext.items()})
    if bot.cash < bot.cfg.get("min_order_quote", 1): log.warning("[coinbase LIVE] NO CASH: %.4f USD/USDC available - entries will be skipped until funded", bot.cash)

def open_pos(bot, sym, size, A, strat, stop_mult, tp_mult, hold, note, trail_on, trail):
    if os.path.exists("KILL_coinbase") or bot.halted: return
    sync(bot)
    if sym in bot.pos: return
    if bot.cash*0.99 < size: fund(bot, size*1.02, {})
    size = min(size, bot.cash*0.99); ts = tsym(bot, sym); bot.order_t = time.time()
    try: f = bot.m.live_product(ts)
    except Exception as e: log.warning("product %s fail %s", ts, e); return
    if size < max(f["quote_min"], bot.cfg.get("min_order_quote", 1)):
        log.info("[coinbase LIVE] skip %s %s: size %.4f < min %.2f (cash %.4f)", strat, ts, size, f["quote_min"], bot.cash); return
    try:
        pv = bot.m.live_preview(ts, "BUY", quote_amt=size)
        if pv.get("errs"): log.warning("[coinbase LIVE] preview reject %s %s", ts, pv["errs"]); return
        r = bot.m.live_market(ts, "BUY", quote_amt=size)
    except Exception as e: log.exception("[coinbase LIVE] buy %s failed %s", ts, e); return
    if r.get("filled_qty", 0) <= 0: log.warning("[coinbase LIVE] buy %s not filled %s", ts, r); sync(bot); return
    px, q, fee = r["avg_px"], r["filled_qty"], r["fee"]; cost = r["quote"]+fee
    bot.pos[sym] = {"side": 1, "entry": px, "qty": q, "cost": cost, "atr": A, "best": px, "t": time.time(), "strategy": strat, "stop": px-stop_mult*A,
                    "tp": px+tp_mult*A, "hold": hold, "trail_on": trail_on, "trail": trail, "order_id": r["order_id"], "tsym": ts, "live": True}
    sync(bot); bot.record(sym, "BUY", px, q, fee, 0, f"{strat} {note} LIVE {r['status']}", bot.equity({})); bot.save()

def close(bot, sym, reason, px):
    p = bot.pos[sym]; ts = tsym(bot, sym); p["tsym"] = ts
    if time.time() < p.get("retry_t", 0): return
    sync(bot)
    qty = min(p["qty"], bot.bal.get(sym.split("-")[0], (0, 0))[0]); bot.order_t = time.time()
    try: r = bot.m.live_market(ts, "SELL", qty=qty)
    except Exception as e:
        bot.sell_fail = getattr(bot, "sell_fail", 0)+1; p["retry_t"] = time.time()+300; p["exit_blocked"] = f"{reason}: {e}"[:200]
        log.error("[coinbase LIVE] sell %s (%s) failed %s body=%s (position kept)", ts, reason, e, getattr(getattr(e, "response", None), "text", "")[:300]); return
    if r.get("filled_qty", 0) <= 0: log.warning("[coinbase LIVE] sell %s not filled %s (kept)", ts, r); return
    bot.pos.pop(sym); x, fee = r["avg_px"], r["fee"]
    pnl = r["quote"]-fee - p["cost"]*r["filled_qty"]/p["qty"]
    if r["filled_qty"] < p["qty"]*0.99: p["qty"] -= r["filled_qty"]; p["cost"] *= p["qty"]/(p["qty"]+r["filled_qty"]); bot.pos[sym] = p
    bot.cool[sym] = time.time()+bot.cfg["cooldown_minutes"]*60; sync(bot)
    bot.record(sym, "SELL", x, r["filled_qty"], fee, pnl, f"{p['strategy']}:{reason} LIVE", bot.equity(px)); bot.save()

def guard(bot, px, eq):
    """kill switch file + max daily loss (pct from config and optional absolute USD)"""
    refresh_levels(bot)
    if time.time()-bot.sync_t > 60:
        sync(bot)
        if not bot.halted: deposit(bot, adopt(bot))
    lim = bot.cfg.get("max_daily_loss_usd"); loss = bot.day_start-eq
    if os.path.exists("KILL_coinbase") or (lim and loss >= lim):
        if not bot.halted: log.warning("[coinbase LIVE] KILL SWITCH (file=%s loss=%.2f) closing managed positions", os.path.exists("KILL_coinbase"), loss)
        bot.halted = True
        for sym in list(bot.pos): close(bot, sym, "kill_switch", px)

ADOPT = dict(stop_mult=7.5, tp_mult=10, trail_on=5, trail=4, hold_min=7*24*60)   # atr=2% px: stop -15%, TP +20%, trail 8% from +10%, 7d time exit -> USDC

def adopt(bot):
    """Owner decision: every non-dust coin in the account is a tradable position managed by the normal exit logic."""
    new = []
    for c, amt in list(bot.ext.items()):
        sym = f"{c}-USD"
        try:
            f = bot.m.live_product(sym); b, a = bot.m.book(sym); px = (b+a)/2
        except Exception: continue
        if amt < f["base_min"] or amt*px < max(f["quote_min"], 1.0): continue   # dust
        A = px*0.02
        bot.pos[sym] = {"side": 1, "entry": px, "qty": amt, "cost": amt*px, "atr": A, "best": px, "t": time.time(), "strategy": "adopted",
                        "stop": px-ADOPT["stop_mult"]*A, "tp": px+ADOPT["tp_mult"]*A, "hold": ADOPT["hold_min"], "trail_on": ADOPT["trail_on"],
                        "trail": ADOPT["trail"], "tsym": tsym(bot, sym), "live": True}
        log.warning("[coinbase LIVE] ADOPT %s qty=%.6g @%.6g value=%.2f", sym, amt, px, amt*px); new.append((sym, amt*px))
        apply_levels(bot, sym)
    sync(bot); return new

def withdrawal(bot, usd, note="external outflow"):
    bot.deposits.append({"t": time.time(), "sym": "OUT", "usd": -round(usd, 2), "note": note}); bot.day_start = max(0.0, bot.day_start-usd)
    log.warning("[coinbase LIVE] WITHDRAWAL/external outflow -%.2f USD (%s) -> day_start=%.2f net_deposits=%.2f", usd, note, bot.day_start, sum(d["usd"] for d in bot.deposits)); bot.save()

def deposit(bot, new):
    """external coins arriving = deposits, not profit: raise baseline + track separately"""
    for sym, v in new:
        bot.deposits.append({"t": time.time(), "sym": sym, "usd": round(v, 2)}); bot.day_start += v
        log.warning("[coinbase LIVE] DEPOSIT detected %s +%.2f USD -> day_start=%.2f net_deposits=%.2f", sym, v, bot.day_start, sum(d["usd"] for d in bot.deposits))
    if new: bot.save()

def fund(bot, need, px):
    """sell adopted coins (weakest first) only when a real signal needs cash"""
    ad = sorted([k for k, p in bot.pos.items() if p["strategy"] == "adopted"], key=lambda k: px.get(k, bot.pos[k]["entry"])/bot.pos[k]["entry"])
    for k in ad:
        if bot.cash >= need: break
        close(bot, k, "fund_signal", px)

def cb_levels(bot, sym, base_px):
    """per-coin exits from the coin's own 6h data: ATR vol-scaling (as Solana volscale) + structure (Donchian support/resistance)"""
    import numpy as np
    d = bot.m.klines(sym, "4h", 200)            # Coinbase SIX_HOUR bars (~50 days)
    tr = np.maximum(d.h-d.l, np.maximum(abs(d.h-d.c.shift()), abs(d.l-d.c.shift())))
    atrp_s = (tr.rolling(14).mean()/d.c).dropna(); atrp = float(atrp_s.iloc[-1]); med = float(atrp_s.median())
    mult = float(np.clip((atrp/med)**0.75, 0.7, 1.5))
    sup = float(d.l.tail(40).min()); res = float(d.h.tail(120).max())
    s_struct = 1-sup*0.99/base_px; s_vol = 3*atrp*mult
    stop = s_struct if 2*atrp <= s_struct <= 5*atrp else s_vol
    stop = float(np.clip(stop, 0.06, 0.35))
    fee = 2*bot.fee_t
    tp = res/base_px-1 if res/base_px-1 >= 1.5*stop else 2*stop
    tp = float(np.clip(tp, 1.5*stop+fee, 0.8))
    trail_w = float(np.clip(2.5*atrp*mult, 0.04, 0.25)); act = max(stop, trail_w+fee)
    return dict(mode="volscale", atr_pct=round(atrp*100, 2), vol_mult=round(mult, 2), sup=sup, res=res, poc=None,
                stop_pct=round(stop, 4), tp_pct=round(tp, 4), trail_w=round(trail_w, 4), act_pct=round(act, 4), t=time.time())

def apply_levels(bot, sym):
    p = bot.pos[sym]
    try: lv = cb_levels(bot, sym, p["entry"])
    except Exception as e: log.warning("levels %s fail %s", sym, e); return
    e = p["entry"]; a = e*lv["atr_pct"]/100
    p.update(lv=lv, atr=a, tp=e*(1+lv["tp_pct"]), trail_on=lv["act_pct"]*e/a, trail=lv["trail_w"]*e/a, hold=1e9)
    nst = e*(1-lv["stop_pct"]); p["stop"] = max(p["stop"], nst) if p.get("trailing") else nst
    log.warning("[coinbase LIVE] LEVELS %s atr=%.2f%% volx=%.2f stop=-%.1f%% tp=+%.1f%% trail=%.1f%%@+%.1f%% sup=%.6g res=%.6g", sym, lv["atr_pct"], lv["vol_mult"],
                lv["stop_pct"]*100, lv["tp_pct"]*100, lv["trail_w"]*100, lv["act_pct"]*100, lv["sup"], lv["res"])

def refresh_levels(bot):
    for k, p in bot.pos.items():
        if p.get("strategy") == "adopted" and time.time()-(p.get("lv") or {}).get("t", 0) > 6*3600: apply_levels(bot, k)
