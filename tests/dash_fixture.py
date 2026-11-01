"""Synthetic, clearly labelled fixture for the v2 panel (tests/test_dash_data.py and tools/preview_dashboard.py).

Everything here is invented ON PURPOSE and says so: symbols FIX*, mints/wallets 'Fixture…', password 'fixture'.
Nothing comes from a real wallet, a real trade or a real API. The file layout and the field names mirror exactly what
memebot.py / bot.py / insider.py / copytrade_paper.py / hl_leg write on the bot machine, so dash_data.py reads the
fixture through the same code path as production. make_fixture() returns the expected values the tests check.
"""
import os, json, csv, math, time, datetime as dt

MINT1 = "FixtureMint1" + "1" * 32
MINT2 = "FixtureMint2" + "2" * 32
MINTC = "FixtureMintCopy" + "3" * 29
WALLET = "FixtureWallet" + "A" * 31
SOL_LIMITS = {"mode": "paper", "starting_equity": 1000, "position_pct": 0.05, "max_positions": 8, "stop_pct": 0.1, "trail_activate_pct": 0.2,
              "trail_pct": 0.1, "max_hold_hours": 3, "daily_max_drawdown_pct": 0.05, "min_liquidity_usd": 50000, "min_score": 45,
              "brain_min_score": 45, "risk_per_trade": 0.005, "max_position_pct": 0.1, "partial_tp_pct": 0.25, "runner_trail_pct": 0.12,
              "exit_mode": "trail", "trail_pct_tt": 12, "hard_stop_pct": 6, "size_pct": 8, "pump_play": False, "live_min_sol": 0.05,
              "scan_seconds": 45, "slippage_bps": 300, "max_stop_pct": 0.15, "reentry_cooldown_hours": 0.25}
CONFIG = {"starting_equity": 1000.0, "risk_per_trade_pct": 0.1, "max_positions": 4, "daily_max_drawdown_pct": 0.05, "cooldown_minutes": 15,
          "atr_stop_mult": 2.5, "take_profit_atr_mult": 3.0, "max_spread_pct": 0.15, "deep_scan_top": 12,
          "strategies": {"momentum": False, "breakout_4h": True, "xs_rotation_4h": True},
          "exchanges": {"solana": SOL_LIMITS,
                        "binance": {"mode": "paper", "enabled": True, "max_trade_loss_pct": 0.03, "daily_max_drawdown_pct": 0.05},
                        "coinbase": {"mode": "live", "enabled": True, "max_trade_loss_pct": 0.03, "min_order_quote": 1, "starting_equity": 10.06}}}
SELL_PNLS = [1.5, -0.8, 2.0, -1.2, 0.9, -0.5, 3.1, -2.2, 1.1, -0.4] * 2      # 20 SELL rows, 10 wins
COPY_PNLS = [0.3, -0.16, 0.3, 0.3, -0.16, 0.3]                                 # 6 closes, 4 wins


def _iso(t): return dt.datetime.fromtimestamp(t).isoformat(timespec="seconds")     # local time, like the bot
def _log(t, level, msg): return f"{dt.datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S')},000 {level} {msg}"
def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f: f.write(text)
def _j(path, obj): _w(path, json.dumps(obj, indent=1, default=str))
def _csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)


def make_empty(d):
    """Only config.json: the 'sin datos' path (every data section must come back available=False, no KeyError)."""
    os.makedirs(d, exist_ok=True); _j(os.path.join(d, "config.json"), CONFIG)


def make_fixture(d, now):
    """Write the whole synthetic file set under `d` as of epoch `now`; return the values the tests expect."""
    os.makedirs(d, exist_ok=True); P = lambda *a: os.path.join(d, *a); now = float(now); today = dt.date.fromtimestamp(now)
    # operative trailing distance: exit_mode "trail" trails trail_pct_tt (percent) from the peak, the bracket modes use trail_pct
    trail_op = SOL_LIMITS["trail_pct_tt"] / 100 if SOL_LIMITS.get("exit_mode") == "trail" else SOL_LIMITS["trail_pct"]
    exp = {"now": now, "password": "fixture", "trail_pct": trail_op}
    _j(P("config.json"), CONFIG)
    _w(P("dashboard_password.txt"), "fixture\n")
    _w(P("tunnel_url.txt"), "https://fixture-tunnel.invalid\n")
    _j(P("control_solana.json"), {"pause": False, "close": []})
    # ---- status_solana.json (memebot.status()) + state_solana_paper.json (memebot.save())
    equity, day_pct = 1012.5, 1.25
    pos = [{"sym": "FIX1", "side": "LONG", "strategy": "meme s61", "entry": 0.0010, "mark": 0.0013, "stop": 0.00098 * 0.9, "trailing": True, "tp": 0.00098 * 1.25,
            "lv": None, "pump": 41, "exh": 12, "cost": 80.0, "pnl": 24.0, "pnl_pct": 30.0, "age_min": 42.0, "mint": MINT1},
           {"sym": "FIX2", "side": "LONG", "strategy": "meme s52 ½TP", "entry": 0.5, "mark": 0.48, "stop": 0.45, "trailing": False, "tp": 0.625,
            "lv": None, "pump": None, "exh": None, "cost": 50.0, "pnl": -2.0, "pnl_pct": -4.0, "age_min": 130.0, "mint": MINT2}]
    brain_model = {"updated": _iso(now - 3600), "n_labelled": 715, "active": True, "base": 0.63, "avg_win": 0.15, "avg_loss": 0.08, "weights": {},
                   "oos": {"n_test": 215, "brain_trades": 124, "brain_avg_ret_%": 1.8, "baseline_trades": 21, "baseline_avg_ret_%": -4.2, "all_avg_ret_%": 1.28, "policy": "ev>0 and score>=45"}}
    decisions = [{"t": dt.datetime.fromtimestamp(now - 60 * i).strftime("%H:%M:%S"), "sym": f"FIXd{i}", "score": 50 + i, "p": 0.6, "ev_pct": 1.2 - 0.1 * i, "kelly_pct": 2.0,
                  "size": 40.0, "pass": i % 2 == 0, "fail": "OK" if i % 2 == 0 else "brain_ev<=0", "narr": "fixture"} for i in range(10)]
    status = {"exchange": "solana", "mode": "paper", "ts": now - 12, "equity": equity, "cash": 900.0, "day_pnl_pct": day_pct, "halted": False, "paused": False,
              "wallet": {"addr": WALLET, "sol": 0.42, "usd": 70.14, "t": now - 30}, "live_min_sol": 0.05,
              "pump_play": {"trades": 2, "pnl": 0.5, "wins": 1, "open": []}, "regime": {"regime": "memecoins", "sol_usd": 167.0}, "fng": None,
              "headlines": [], "delist": [], "listings": [], "universe": 120, "positions": pos, "pending": [],
              "signals": [{"t": dt.datetime.fromtimestamp(now - 30 * i).strftime("%H:%M:%S"), "sym": f"FIXs{i}", "type": "meme-scan", "strategy": "meme" if i % 3 == 0 else "-",
                           "side": 1 if i % 3 == 0 else 0, "chg5": 2.5, "vol": 0.3, "rsi": 55 + i, "mtf": "OK" if i % 3 == 0 else "liq", "rs": 1.0} for i in range(12)][::-1],
              "movers": [{"sym": f"FIXm{i}", "chg5": 90 - 5 * i} for i in range(12)],
              "smart": {"wallets": 10, "items": [{"ts": now - 60, "mint": f"FixtureSmart{i}", "sym": f"FIXw{i}", "held": i == 0, "flags": ["smart_buyers"] if i % 2 else []} for i in range(12)]},
              "ai_pump": [{"sym": f"FIXp{i}", "pump": 80 - 10 * i, "exh": 10 + 5 * i, "sig_pump": i == 0, "sig_exh": False, "held": False, "pump_parts": {}, "exh_parts": {}, "age_s": 30} for i in range(8)],
              "eval": None, "brain": {"model": brain_model, "ctx": {}, "decisions": decisions},
              "stats": {"closed_trades": 12, "closed": 12, "win_rate": 0.5, "net_pnl": 3.2}}
    _j(P("status_solana.json"), status)
    state_pos = {MINT1: {"sym": "FIX1", "raw": 80000000, "dec": 6, "entry": 0.0010, "best": 0.0014, "cost": 80.0, "t": now - 42 * 60, "score": 61, "partial": False,
                         "mark0": 0.00098, "mark": 0.0013, "stop_pct": 0.1, "sellfail": 0, "noroute": 0},
                 MINT2: {"sym": "FIX2", "raw": 100000000, "dec": 6, "entry": 0.5, "best": 0.52, "cost": 50.0, "t": now - 130 * 60, "score": 52, "partial": True,
                         "mark0": 0.5, "mark": 0.48, "stop_pct": 0.1, "sellfail": 2, "noroute": 1, "rent_usd": 0.34, "fail_last": now - 300}}
    _j(P("state_solana_paper.json"), {"cash": 900.0, "pos": state_pos, "trades": [1.0, -0.5], "seen": {}, "day": today.isoformat(), "day_start": 1000.0, "halted": False, "dead": []})
    exp["day_pnl_usd"] = round(equity - equity / (1 + day_pct / 100), 4)
    exp["pos0"] = {"sym": "FIX1", "best": 0.0014, "mark": 0.0013, "stop": 0.00098 * 0.9, "trail_level": 0.0014 * (1 - trail_op),
                   "dist_stop_pct": round((0.0013 / (0.00098 * 0.9) - 1) * 100, 2)}
    exp["pos1"] = {"sym": "FIX2", "sellfail": 2, "noroute": 1, "rent_usd": 0.34, "partial": True, "best": 0.52}
    # ---- equity_solana.csv: 8 days every 30 s (~23,000 rows) -> the reader must tail, not load
    n = 8 * 86400 // 30 + 1; t_end = int(now)
    rows = [(t_end - 30 * (n - 1 - i), round(1000 + 20 * math.sin(i / 400) + i * 0.0005, 4)) for i in range(n)]
    _w(P("equity_solana.csv"), "".join(f"{t},{v:.4f}\n" for t, v in rows))
    w24 = [(t, v) for t, v in rows if t >= now - 86400]
    exp["equity"] = {"n_rows_total": n, "first_24h": w24[0][1], "last": rows[-1][1], "min_24h": min(v for _, v in w24), "max_24h": max(v for _, v in w24), "last_ts": rows[-1][0]}
    # ---- trades_solana_paper.csv: 20 BUY/SELL pairs over 20 days, reasons with tx=…
    hdr = "time,exchange,symbol,side,price,qty,fee,pnl,reason,equity".split(",")
    trows, eq = [], 1000.0
    for k in range(20):
        dback = 19 - k; tb, ts_ = now - dback * 86400 - 7200, now - dback * 86400 - 3600; sym = f"FIX{k % 5 + 1}"; pnl = SELL_PNLS[k]
        trows.append([_iso(tb), "solana", sym, "BUY", "0.00123", "40650.4", "0.0500", "0.0000", f"meme score=61.0 liq=120000 top10=12% lp=100% rt=1.2% tx=FixtureSig{k}", f"{eq:.2f}"])
        eq += pnl
        trows.append([_iso(ts_), "solana", sym, "SELL", "0.00130", "40650.4", "0.0500", f"{pnl:.4f}", f"{'trail' if pnl > 0 else 'stop'} tx=FixtureSig{k}x", f"{eq:.2f}"])
    _csv(P("trades_solana_paper.csv"), hdr, trows)
    days = [(today - dt.timedelta(days=k)).isoformat() for k in range(13, -1, -1)]
    daily = {dd: {"pnl": 0.0, "n": 0, "wins": 0} for dd in days}
    for r in trows:
        if r[3] == "SELL" and r[0][:10] in daily:
            a = daily[r[0][:10]]; p = float(r[7]); a["pnl"] += p; a["n"] += 1; a["wins"] += p > 0
    exp["daily_pnl"] = {dd: dict(a, pnl=round(a["pnl"], 4)) for dd, a in daily.items()}
    exp["total_14d"] = round(sum(a["pnl"] for a in daily.values()), 4)
    gw, gl = sum(p for p in SELL_PNLS if p > 0), -sum(p for p in SELL_PNLS if p < 0)
    exp["kpi"] = {"n": 20, "wins": 10, "gross_win": round(gw, 4), "gross_loss": round(gl, 4), "profit_factor": round(gw / gl, 4), "fees": round(40 * 0.05, 4),
                  "best_pnl": max(SELL_PNLS), "worst_pnl": min(SELL_PNLS)}
    # ---- trades_solana_live.csv: 3 REAL rows in the last 24 h (+1 older one that must not count)
    real = lambda t, sym, side, pnl, why: [_iso(t), "solana", sym, side, "0.0284", "35.2", "0.0481", f"{pnl:.4f}", f"{why} REAL tx=FixtureSigReal slip=120bps", "53.36"]
    _csv(P("trades_solana_live.csv"), hdr, [real(now - 3 * 86400, "FIXr0", "SELL", -0.3, "stop"), real(now - 20000, "FIXr1", "BUY", 0, "meme score=55 liq=200000"),
                                            real(now - 15000, "FIXr1", "SELL", 0.42, "trail"), real(now - 3000, "FIXr2", "BUY", 0, "meme score=58 liq=150000")])
    exp["real_trades_24h"] = 3
    # ---- candidates_solana.jsonl: 120 rows (fail liq / rugcheck_unavailable / hardfail_recent / lp_unlocked / pass)
    srcs = ["gecko_new_pools", "dex_profiles", "jup_trend5m", "insider"]; fails = {0: ["liq"], 1: ["liq"], 2: ["rugcheck_unavailable"], 3: ["hardfail_recent"], 4: ["lp_unlocked", "top10"]}
    lines = []
    for i in range(120):
        rec = {"ts": _iso(now - (119 - i) * 30), "mint": f"FixtureCand{i:03d}" + "c" * 29, "sym": f"FIXc{i}", "src": srcs[i % 4], "dex": "pumpswap", "price": "0.001",
               "pair": "FixturePair", "liq": 10000 + 1000 * i, "mcap": 500000, "pass": i % 6 == 5, "fail": fails.get(i % 6, [])}
        if rec["pass"]: rec["score"] = 50 + i % 30
        lines.append(json.dumps(rec))
    _w(P("candidates_solana.jsonl"), "\n".join(lines) + "\n")
    exp["funnel"] = {"rows": 120, "passed": 20, "by_fail": [("liq", 40), ("hardfail_recent", 20), ("lp_unlocked", 20), ("rugcheck_unavailable", 20)], "last_passed_sym": "FIXc119"}
    # ---- bot_solana.log (logging format '%(asctime)s %(levelname)s %(message)s')
    PRE = "[solana] prefilter 60/120 -> eval 40 (5 skipped: hard-vetoed <3600s ago), rugcheck fetched 38/40 (2 past budget) in 97s"
    log = [_log(now - 3600 + 20 * i, "INFO", f"[solana] heartbeat fixture {i}") for i in range(60)]
    log += [_log(now - 900, "INFO", "[solana] SCAN 410 mints, 120 pairs, 60 >= liq, 3 passed all filters"), _log(now - 800, "INFO", PRE),
            _log(now - 700, "WARNING", "[solana] LIVE buy FIX1 blocked: EV 0.5% < 3x real round-trip 0.3%"),
            _log(now - 600, "INFO", f"TRADE {_iso(now - 600)} | solana | FIX1 | BUY | 0.001 | 80000 | 0.0500 | 0.0000 | meme score=61 REAL tx=FixtureSig123 slip=120bps | 1000.00"),
            _log(now - 500, "INFO", "[solana] SCAM block FIX3: mint_auth,lp_unlocked45"), _log(now - 400, "WARNING", "[solana] KILL SWITCH"),
            _log(now - 300, "WARNING", "[solana] ai_loop: Traceback (most recent call last) ValueError fixture"),
            _log(now - 250, "INFO", "[solana] buy FIX4 aborted: no quote"),
            _log(now - 200, "INFO", "[solana] SCAN 420 mints, 125 pairs, 61 >= liq, 2 passed all filters"), _log(now - 100, "INFO", PRE),
            _log(now - 60, "INFO", "[solana] REGIME {'regime': 'memecoins'}")]
    _w(P("bot_solana.log"), "\n".join(log) + "\n")
    exp["scan"] = {"ok": 60, "total": 120, "eval": 40, "skipped_hardfail": 5, "rc_fetched": 38, "rc_needed": 40, "rc_past_budget": 2, "secs": 97, "prefilter_ts": now - 100, "last_scan_ts": now - 200}
    _w(P("bot_binance.log"), "\n".join([_log(now - 500, "INFO", "[binance] REGIME {'regime': 'bull'}"), _log(now - 400, "INFO", "TRADE fixture FIXUSDT SELL pnl=-0.1 tx=FixtureSigB")]) + "\n")
    # ---- insider_status.json
    conv_scores = [9, 3, 7, 1, 5, 2]
    conv = {f"FixtureConv{i}" + "v" * 30: {"score": s, "n": 2 + i % 3, "elite": i % 4} for i, s in enumerate(conv_scores)}
    _j(P("insider_status.json"), {"ts": now - 100, "v": 3, "tracked": 150, "cycle_s": 42.5, "live_ranked": 37, "conv": conv,
                                  "alerts": [{"t": now - 300 * (11 - i), "mint": f"FixtureAlert{i:02d}" + "a" * 30, "px": 0.01, "score": 4 + i, "n": 2, "elite": i % 5} for i in range(12)],
                                  "buys": [], "sells": [], "sells_by_mint": {}, "tokens": {}, "tok_valid": None,
                                  "feed": [{"t": now - 20 * (24 - i), "kind": "smart_buy" if i % 3 else "cluster_buy", "w": WALLET, "tier": "elite" if i % 2 else "good",
                                            "mint": f"FixtureFeed{i:02d}" + "f" * 30, "sol": 1.5 + i, "lag_s": 3} for i in range(25)],
                                  "counts": {"smart_buy": 16, "cluster_buy": 9}})
    exp["insider"] = {"tracked": 150, "alerts_n": 10, "first_alert_elite": 11 % 5, "top_conv_score": 9, "conv_n": 5, "feed_n": 20}
    # ---- copytrade paper: state + csv
    _j(P("state", "copytrade_paper.json"), {"pos": {MINTC: {"sym": "FIXC1", "e": 0.01, "t": now - 600, "pair": "FixturePairC", "liq": 120000, "rug_n": 1}}, "seen": [], "closed": 6, "pnl": round(sum(COPY_PNLS), 4)})
    crow = []
    for i, p in enumerate(COPY_PNLS):
        crow.append([_iso(now - 7200 * (6 - i) - 900), f"FIXC{i}", "BUY", "0.0100", "2.0", "0", "elite=4 liq=110000", f"FixtureMintCopy{i}"])
        crow.append([_iso(now - 7200 * (6 - i)), f"FIXC{i}", "SELL", "0.0115" if p > 0 else "0.0092", "2.0", f"{p:.4f}", "tp" if p > 0 else "sl", f"FixtureMintCopy{i}"])
    crow.append([_iso(now - 600), "FIXC1", "BUY", "0.0100", "2.0", "0", "elite=5 liq=120000", MINTC])
    _csv(P("trades_solana_copy_paper.csv"), ["time", "symbol", "side", "price", "usd", "pnl", "reason", "mint"], crow)
    exp["copytrade"] = {"closed": 6, "wins": 4, "win_rate": round(4 / 6, 4), "open_n": 1}
    # ---- brain / eval
    _j(P("data", "brain_state.json"), dict(brain_model, n=715))
    _j(P("eval_solana.json"), {"generado": _iso(now - 600), "ventana_h": 72, "tokens": 10, "replay_cacheados": 3,
                               "grupos": {"PASS (comprado/elegible)": {"candidatos": 4, "precio_ahora": {"n": 4, "media_%": -3.1, "mediana_%": -2.0, "win_%": 50},
                                                                        "replay_estrategia": {"n": 4, "media_%": 1.2, "mediana_%": 0.8, "win_%": 50}}}})
    # ---- Hyperliquid leg (Keel paper run, evidence, Coinversa risk context)
    _j(P("hl_leg", "hl_paper.json"), {"deployment_id": "dep_fixture0001", "url": "https://fixture.invalid/paper/dep_fixture0001", "strategy_id": "str_fixture",
                                      "strategy_name": "FIXTURE supertrend+bollinger causal top-15", "strategy_version": 1, "started": "2026-10-31T21:41:00Z",
                                      "replaces": {"deployment_id": "dep_fixture0000", "stopped": "2026-10-31T21:40:00Z", "why": "fixture: hindsight universe"},
                                      "simulated_capital_usd": 1000, "schedule": "daily at 11:59 UTC", "auto_pause": "after 28 days",
                                      "expectation": "fixture: OOS Sharpe 1.15 / +43.5% / max DD -30%; a paper drawdown of -30% is inside the tested range.",
                                      "go_live_criteria": [">= 21 days and >= 20 evaluations of paper", ">= 150 USD on the account"], "first_evaluation": "pending"})
    _j(P("hl_leg", "evidence.json"), {"generated": "fixture", "honest_summary": "Fixture: a measured, small, executable edge in paper; nothing more.",
                                      "windows": {"in_sample": "2024-08-15 .. 2026-03-31", "out_of_sample": "2026-04-01 .. 2026-10-30", "full": "2024-08-15 .. 2026-10-30"},
                                      "selected": {"strategy_id": "str_fixture", "runs": {"out_of_sample": {"id": "btr_fixture_oos", "sharpe": 1.15, "return_pct": 43.5, "max_dd_pct": -30.1, "profit_factor": 1.31, "win_rate_pct": 47.5},
                                                                                            "full": {"id": "btr_fixture_full", "sharpe": 0.76, "return_pct": 91.2, "max_dd_pct": -58.2, "profit_factor": 1.18, "quarters_positive": "6 of 10"}}}})
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - 1800))
    _j(P("data", "hl_risk.json"), {"updated": stamp, "status": "ok", "ok": 3, "failed": 0,
                                   "coins": {"BTC": {"flags_long": [], "flags_short": [], "size_mult_long": 1.0, "size_mult_short": 1.0, "apex": 0.1, "crowd": -0.2, "time": stamp},
                                             "SOL": {"flags_long": ["high_leverage"], "flags_short": [], "size_mult_long": 0.7, "size_mult_short": 1.0, "apex": 0.3, "crowd": 0.1, "time": stamp},
                                             "ETH": {"flags_long": ["apex_against", "liq_cluster"], "flags_short": ["crowd_with_us"], "size_mult_long": 0.5, "size_mult_short": 0.7, "apex": -0.4, "crowd": 0.5, "time": stamp}}})
    _csv(P("data", "hl_context.csv"), ["time", "coin", "apex", "sharps", "crowd", "oi", "near_liq", "avg_leverage", "flags_long", "flags_short"],
         [[time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - 3600 * (12 - i))), ["BTC", "ETH", "SOL"][i % 3], 0.1 * i, 0.0, -0.1, 1e9, 2e7, 12.5, "", "crowd_with_us" if i % 3 == 1 else ""] for i in range(12)])
    exp["hl_risk_order"] = ["ETH", "SOL", "BTC"]
    # ---- CEX: binance (fresh, paper) + coinbase (stale, live)
    _j(P("status_binance.json"), {"exchange": "binance", "mode": "paper", "ts": now - 20, "equity": 998.1, "cash": 900.0, "day_pnl_pct": -0.19, "halted": False, "paused": False,
                                  "external_holdings": {}, "deposits": [], "net_deposits": 0.0, "no_cash": False, "regime": {"regime": "bull", "btc_trend": 1, "vol": 0.02},
                                  "fng": 55, "headlines": [], "delist": [], "listings": [], "universe": 40,
                                  "positions": [{"sym": "FIXUSDT", "side": "LONG", "strategy": "breakout_4h", "entry": 1.0, "mark": 1.02, "qty": 50, "cost": 50.0, "pnl": 1.0, "pnl_pct": 2.0,
                                                 "stop": 0.95, "tp": 1.2, "age_min": 300.0, "trailing": False, "lv": None, "exit_blocked": None}],
                                  "pending": [], "signals": [], "movers": [], "stats": {"closed": 5, "win_rate": 40.0, "net_pnl": -0.9}})
    _w(P("equity_binance.csv"), "".join(f"{t_end - 60 * (1440 - i)},{998 + math.sin(i / 100):.4f}\n" for i in range(1441)))
    _csv(P("trades_binance_paper.csv"), hdr, [[_iso(now - 3600 * (5 - i)), "binance", "FIXUSDT", "SELL", "1.01", "49.5", "0.0450", f"{(-0.1 if i % 2 else 0.2):.4f}", "breakout_4h:trail", "998.10"] for i in range(5)])
    _j(P("status_coinbase.json"), {"exchange": "coinbase", "mode": "live", "ts": now - 5000, "equity": 10.06, "cash": 10.06, "day_pnl_pct": 0.0, "halted": False, "paused": False,
                                   "external_holdings": {}, "deposits": [], "net_deposits": 0.0, "no_cash": True, "regime": {}, "fng": None, "headlines": [], "delist": [], "listings": [],
                                   "universe": 0, "positions": [], "pending": [], "signals": [], "movers": [], "stats": {"closed": 0, "win_rate": None, "net_pnl": 0.0}})
    # ---- supervisor.log
    _w(P("supervisor.log"), "".join(f"{dt.datetime.fromtimestamp(now - 600 * (15 - i)).isoformat(timespec='seconds')}+00:00 [{['solana', 'binance', 'dashboard', 'insider'][i % 4]}] start mode=paper\n" for i in range(15)))
    # mtime-based sections (brain file, copytrade state, hl_risk, eval, supervisor) must read as written at `now`
    for dp, _, fs in os.walk(d):
        for fn in fs:
            try: os.utime(os.path.join(dp, fn), (now, now))
            except OSError: pass
    # director (director.py): state + log, shadow mode
    dstate = {"ts": now - 600, "first_run": now - 7200, "shadow": True, "version": 1, "plays": {"scanner": "on", "insider_elite": "on", "pump": "off"},
              "min_score_eff": 45, "ev_min_eff": 0.0156, "windows": [h for h in range(24) if h not in (3, 4)], "max_trades_day": 10,
              "size_policy": {"target_usd": 3.84, "fixed_share": 0.0052, "fixed_usd": 0.02, "binding": "size_pct", "why": "fixture: posición máxima 3,84 $"},
              "exit_profile": {"hard_stop_pct": 6.0, "trail_pct": 12.0, "why": "fixture: perfil de config"},
              "evidence": {"equity": 48.0, "sol_usd": 96.0, "fixed_cost_usd": 0.02, "rent_lost_prob": 0.1, "cost_pct": 1.02, "dataset_rows": 715, "score_floor_why": "config",
                           "plays": {"scanner": {"n_eff": 2, "pf": 1.1, "exp_pct": 0.5, "real": {"n": 2, "pf_raw": 1.63, "exp_pct_raw": 3.0}, "paper": {"n": 0, "pf_raw": None, "exp_pct_raw": None}},
                                     "pump": {"n_eff": 60, "pf": 0.35, "exp_pct": -1.7, "real": {"n": 60, "pf_raw": 0.33, "exp_pct_raw": -1.8}, "paper": {"n": 0, "pf_raw": None, "exp_pct_raw": None}}},
                           "plays_why": {"pump": "n_eff=60 PF=0.35: pump apagado también en papel"}}}
    json.dump(dstate, open(os.path.join(d, "director_state.json"), "w", encoding="utf-8"))
    open(os.path.join(d, "director_log.jsonl"), "w", encoding="utf-8").write(json.dumps({"t": now - 600, "shadow": True, "changes": [{"key": "plays", "before": None, "after": dstate["plays"]}], "summary": "fixture summary"}) + "\n")
    exp["director"] = {"shadow": True, "target_usd": 3.84, "windows_n": 22, "pump": "off"}
    json.dump({"ts": now - 1200, "findings": [{"level": "warn", "code": "errors_1h", "msg": "1 error en logs"}, {"level": "info", "code": "director_shadow", "msg": "Director en sombra"}],
               "actions": [{"action": "rotate_logs", "detail": "bot_solana.log: 60 MB → 5 MB", "dry_run": False}], "summary": {"legs": ["Solana papel 1012,50 $"], "scan": "60/120"},
               "last_daily": "2026-10-31", "last_ata": now - 7200, "last_restart": {}}, open(os.path.join(d, "operator_state.json"), "w", encoding="utf-8"))
    open(os.path.join(d, "alerts.jsonl"), "w", encoding="utf-8").write(json.dumps({"t": now - 1200, "level": "warn", "code": "errors_1h", "msg": "1 error en logs"}) + "\n")
    exp["operator"] = {"worst": "warn", "n_findings": 2}
    os.makedirs(os.path.join(d, "state"), exist_ok=True)
    json.dump({"ts": now - 300, "mode": "paper", "budget_usd": 1000.0, "equity": 1012.0, "cash": 340.0, "closed": 3, "pnl": 12.0, "last_eval_day": "2026-10-31",
               "positions": [{"sym": "FIXJ", "mint": "Fixture" + "j" * 36, "entry": 1.0, "mark": 1.05, "usd": 330.0, "pnl": 16.5, "age_h": 30.0}],
               "signals": {"Fixture" + "j" * 36: {"sym": "FIXJ", "entry": True, "st_green": True, "bb_pos": 0.7, "atr_ratio": 1.1, "in_universe": True}, "Fixture" + "k" * 36: {"sym": "FIXK", "entry": False, "st_green": False, "bb_pos": 0.3, "atr_ratio": 0.9, "in_universe": True}},
               "rule": "fixture rule"}, open(os.path.join(d, "state", "trend_status.json"), "w", encoding="utf-8"))
    exp["trend"] = {"pnl": 12.0, "n_pos": 1}
    return exp
