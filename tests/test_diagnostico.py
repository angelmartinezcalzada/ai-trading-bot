"""tools/diagnostico.py: read-only one-screen diagnosis. Offline; never opens solana_wallet.json; never prints keys.env values."""
import builtins, csv, importlib.util, json, os, time
import pytest

spec = importlib.util.spec_from_file_location("diagnostico", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "diagnostico.py"))
dg = importlib.util.module_from_spec(spec); spec.loader.exec_module(dg)
NOW = time.mktime((2026, 11, 2, 12, 0, 0, 0, 0, -1))
def lt(sec_ago): return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - sec_ago)) + ",123"
def iso(sec_ago): return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - sec_ago))
PROCS_OK = ["1 python3 bot.py --exchange solana --live", "2 python3 bot.py --exchange binance", "3 python3 bot.py --exchange coinbase", "4 python3 dashboard.py",
            "5 python3 insider.py daemon", "6 python3 insider_ws.py", "7 python3 trend_spot.py --loop", "8 /bin/bash ./run_forever.sh", "9 /bin/bash ./run_forever.sh", "13 /bin/bash tools/keepalive.sh"]


def log_lines(extra=()):
    L = [f"{lt(3600 * 30)} INFO [solana] SCAN 400 mints, 100 pairs, 50 >= liq, 7 passed all filters"]          # outside the 24 h window
    for i in range(10): L.append(f"{lt(3600 * 20 - i * 60)} INFO [solana] SCAN 420 mints, 125 pairs, 61 >= liq, 1 passed all filters")
    L += [f"{lt(3600 * 19)} INFO [solana] ALT gate FOO skipped: Solana Tracker verdict neutral/missing",
          f"{lt(3600 * 19)} INFO [solana] ALT gate FOO skipped: Solana Tracker verdict neutral/missing",
          f"{lt(3600 * 18)} INFO [solana] ALT gate BAR skipped: score 41.0 < 45",
          f"{lt(3600 * 18)} INFO [solana] ST check BAZ verdict=veto veto=['st_snipers'] bonus=0",
          f"{lt(3600 * 18)} WARNING [solana] LIVE buy QUX blocked (gate=alt): real round-trip 2.10% > 1.50%",
          f"{lt(3600 * 17)} INFO [solana] ZED: director: hora 3 fuera de ventana",
          f"{lt(3600 * 17)} ERROR ws error HTTPSConnectionPool(host='mainnet.helius-rpc.com', port=443): Max retries url: /?api-key=SUPERSECRETKEY123 tx 5hyaGtz4G2wGbgCpJiAurz8on9vWDUevVFXoS1jPcAEymFBfta7BERcEGN3o5QJCpn5b4e8BwCbSJdFyQV6pVmJ7"]
    L += list(extra); L.append(f"{lt(60)} INFO [solana] equity=96.40 cash=96.40 open=[] SOL=170.00")
    return L


def make(tmp, mode="live", halted=False, trades=True, key=True, wallet=True, kill=False, log_extra=(), budget=None):
    d = str(tmp)
    open(os.path.join(d, "bot_solana.log"), "w").write("\n".join(log_lines(log_extra)) + "\n")
    json.dump({"exchange": "solana", "mode": mode, "ts": NOW - 12, "equity": 96.4, "cash": 96.4, "day_pnl_pct": -0.31, "halted": halted, "positions": [],
               "wallet": {"addr": "GJ4dRV1XPkUiJ5ieZNfFemFNgYWxJDA3YBpT6hPrcp8A", "sol": 0.5667, "usd": 96.4, "t": NOW - 30}}, open(os.path.join(d, "status_solana.json"), "w"))
    json.dump({"cash": 96.4, "day_start": 96.7, "halted": halted, "pos": {}}, open(os.path.join(d, "state_solana_live.json"), "w"))
    if trades:
        with open(os.path.join(d, "trades_solana_live.csv"), "w", newline="") as f:
            w = csv.writer(f); w.writerow("time,exchange,symbol,side,price,qty,fee,pnl,reason,equity".split(","))
            w.writerow([iso(3600 * 48), "solana", "OLD", "SELL", 1, 1, 0, "-1.0000", "meme:stop REAL tx=X", 50])
            w.writerow([iso(3600 * 5), "solana", "NEW", "BUY", 1, 1, 0, "0.0000", "meme REAL tx=Y", 96])
            w.writerow([iso(3600 * 4), "solana", "NEW", "SELL", 1, 1, 0, "0.1200", "meme:trail REAL tx=Z", 96.1])
    if key: open(os.path.join(d, "keys.env"), "w").write("SOLANATRACKER_API_KEY=SECRETVALUE42\nBINANCE_API_KEY=\n")
    if wallet: open(os.path.join(d, "solana_wallet.json"), "w").write("[1,2,3]")
    if kill: open(os.path.join(d, "KILL_solana"), "w").write("")
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    json.dump(budget or {"day": time.strftime("%Y-%m-%d", time.localtime(NOW)), "n": 120, "nd": 30, "ni": 10}, open(os.path.join(d, "data", "st_budget.json"), "w"))
    return d


def run(d, procs=PROCS_OK, hours=24):
    real_open = builtins.open
    def guard(p, *a, **k):
        assert not str(p).endswith("solana_wallet.json"), "the diagnosis must never open the wallet file"
        return real_open(p, *a, **k)
    builtins.open = guard
    try: D = dg.gather(d, hours, now=NOW, procs=procs); return D, dg.report(D)
    finally: builtins.open = real_open


def test_live_and_trading(tmp_path):
    D, out = run(make(tmp_path))
    assert "✅ En REAL y operando: 1 compras y 1 ventas en 24 h, PnL realizado +0,12 $." in out
    assert D["log"]["scans"] == 10 and D["log"]["passed"] == 10 and D["log"]["alt_st"] == 2 and D["log"]["alt_score"] == 1                 # the 30 h old scan is outside
    assert D["log"]["blocked"]["coste ida y vuelta"] == 1 and D["log"]["director"]["hora N fuera de ventana"] == 1 and D["log"]["st"]["veto"] == 1
    assert D["trades"]["buys_all"] == 1 and D["trades"]["sells_all"] == 2 and D["trades"]["pnl_all"] == pytest.approx(-0.88)
    assert "solana ✓" in out and "supervisor ✓" in out and "GJ4d…cp8A" in out and "hoy 120/300" in out and "modo REAL" in out


def test_never_prints_secrets_full_addresses_or_signatures(tmp_path):
    _, out = run(make(tmp_path))
    assert "SECRETVALUE42" not in out and "SUPERSECRETKEY123" not in out and "GJ4dRV1XPkUiJ5ieZNfFemFNgYWxJDA3YBpT6hPrcp8A" not in out
    assert "5hyaGtz4G2wGbgCpJiAurz8on9vWDUevVFXoS1jPcAEymFBfta7BERcEGN3o5QJCpn5b4e8BwCbSJdFyQV6pVmJ7" not in out and "api-key=***" in out and "5hya…VmJ7" in out


def test_live_no_buys_reason_missing_key_then_budget(tmp_path):
    d = make(tmp_path, trades=False, key=False)
    D, out = run(d)
    assert "En REAL, 0 compras en 24 h. Motivo principal: falta la clave de Solana Tracker en keys.env" in out and "clave NO" in out
    open(os.path.join(d, "keys.env"), "w").write("SOLANATRACKER_API_KEY=abc\n")
    json.dump({"day": time.strftime("%Y-%m-%d", time.localtime(NOW)), "n": 300}, open(os.path.join(d, "data", "st_budget.json"), "w"))
    D, out = run(d)
    assert "Solana Tracker sin veredicto en 2 candidatos aptos (cupo diario agotado)" in out


def test_halted_and_kill_file(tmp_path):
    _, out = run(make(tmp_path, halted=True, trades=False))
    assert "⛔ En REAL pero sin compras: saltó el stop diario del 5 %" in out and "stop diario SALTADO" in out
    _, out = run(make(tmp_path, kill=True, trades=False))
    assert "fichero KILL_solana presente" in out


def test_paper_reasons_and_not_running(tmp_path):
    _, out = run(make(tmp_path, mode="paper", wallet=False))
    assert "Solana en PAPEL (no mueve dinero real): no hay solana_wallet.json." in out
    _, out = run(make(tmp_path, mode="paper"), procs=[l for l in PROCS_OK if "solana" not in l])
    assert "✖ El bot de Solana NO está corriendo" in out and "el wallet aún no se ha leído o tiene menos de 0,05 SOL" in out
    _, out = run(make(tmp_path), procs=PROCS_OK + ["10 python3 bot.py --exchange solana --live"])
    assert "Hay 2 copias del bot de Solana" in out


def test_gaps_flag_a_sleeping_pc(tmp_path):
    _, out = run(make(tmp_path, log_extra=[f"{lt(3600 * 3)} INFO [solana] SCAN 1 mints, 1 pairs, 1 >= liq, 0 passed all filters"]))
    assert "⚠ El bot estuvo sin actividad" in out and "huecos > 20 min" in out


def test_main_reason_without_candidates_and_without_scans(tmp_path):
    d = make(tmp_path, trades=False)
    D = dg.gather(d, 24, now=NOW, procs=PROCS_OK)
    D["log"].update(alt_st=0, alt_score=0, passed=0); D["log"]["blocked"].clear(); D["log"]["director"].clear()
    assert dg.main_reason(D).startswith("ningún token pasó todos los filtros en 10 escaneos")
    D["log"]["scans"] = 0; assert "no hay escaneos" in dg.main_reason(D)


def test_missing_files_never_raise(tmp_path):
    D, out = run(str(tmp_path), procs=[])
    assert "Solana sin estado: el bot no ha arrancado todavía (no hay status_solana.json); además falta solana_wallet.json" in out and "PAPEL" not in out.split("Procesos")[0]
    assert "sin libro real" in out and "Contexto: sin data/context_now.json" in out and "Director: sin estado" in out and "Cerebro: sin estado" in out
    D, out = run(str(tmp_path), procs=None)                                                   # pgrep unavailable: no crash, procs unknown
    assert "no se pudo consultar" in out or "Procesos:" in out


def test_clean_and_num():
    assert dg.num(1234.5) == "1.234,50" and dg.sgn(-0.4) == "-0,4" and dg.sgn(None) == "?" and dg.ago(30) == "30 s" and dg.ago(7300) == "2,0 h"
    assert dg.clean("wss://x.io/ws?api-key=ABC token=DEF") == "wss://x.io/… token=***"


def test_process_patterns_ignore_wrapper_shells():
    wrap = ["11 /bin/bash -c cd x && python3 bot.py --exchange solana --live && python3 dashboard.py", "12 bash -c pkill -f run_forever.sh"]
    c = dg.count_procs(PROCS_OK + wrap)
    assert c["solana"] == 1 and c["panel"] == 1 and c["supervisor"] == 2
    assert dg.count_procs(["5 /usr/bin/python3.12 bot.py --exchange solana"])["solana"] == 1


def test_crash_loop_and_missing_autostart_are_explained(tmp_path, monkeypatch):
    d = make(tmp_path, trades=False)
    iso_tz = lambda sec: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - sec)) + time.strftime("%z", time.localtime(NOW - sec))[:3] + ":" + time.strftime("%z", time.localtime(NOW - sec))[3:]
    open(os.path.join(d, "supervisor.log"), "w").write("".join(f"{iso_tz(600 - 60 * i)} [solana] start mode=live\n{iso_tz(590 - 60 * i)} [solana] exited code 1\n" for i in range(4))
                                                      + f"{iso_tz(90000)} [solana] exited code 1\n")       # outside the window
    open(os.path.join(d, "stdout_solana.log"), "w").write(f"{lt(600)} INFO [solana] EXIT MODE trail\nTraceback (most recent call last):\n  File \"bot.py\", line 3\nModuleNotFoundError: No module named 'foo'\n")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    D, out = run(d, procs=[l for l in PROCS_OK if "solana" not in l and "run_forever" not in l])
    assert D["sup"]["starts"] == 4 and D["sup"]["bad_exits"] == 4 and D["sup"]["last_code"] == 1
    assert "✖ El bot de Solana se cae al arrancar: el supervisor lo relanzó 4 veces (último código 1); último error: ModuleNotFoundError: No module named 'foo'." in out
    assert "⚠ Sin arranque automático" in out and "Arranque automático: NO" in out
    vbs = os.path.join(d, "TradingBot.vbs"); open(vbs, "w").write("x"); open(os.path.join(d, ".autostart"), "w").write(vbs + "\n")
    _, out = run(d, procs=PROCS_OK)
    assert "Arranque automático: sí" in out and "Sin arranque automático" not in out


def test_watchdog_missing_with_autostart_is_flagged(tmp_path, monkeypatch):
    d = make(tmp_path); vbs = os.path.join(d, "TradingBot.lnk"); open(vbs, "w").write("x"); open(os.path.join(d, ".autostart"), "w").write(vbs + "\n")
    _, out = run(d, procs=[l for l in PROCS_OK if "keepalive" not in l])
    assert "⚠ El vigilante oculto no corre" in out and "vigilante ✖" in out
    _, out = run(d, procs=PROCS_OK)
    assert "vigilante ✓" in out and "El vigilante oculto no corre" not in out


def test_recent_start_is_not_reported_as_hung(tmp_path):
    d = make(tmp_path)
    st = json.load(open(os.path.join(d, "status_solana.json"))); st["ts"] = NOW - 3600 * 18; json.dump(st, open(os.path.join(d, "status_solana.json"), "w"))
    D = dg.gather(d, 24, now=NOW, procs=PROCS_OK); D["sol_age"] = 120
    assert any("está haciendo su primer escaneo" in x for x in dg.verdict(D)) and not any("posible cuelgue" in x for x in dg.verdict(D))
    D["sol_age"] = 5000; assert any("posible cuelgue" in x for x in dg.verdict(D))


def test_dns_failure_is_the_first_thing_reported(tmp_path, monkeypatch):
    d = make(tmp_path)
    monkeypatch.setattr(dg, "dns_check", lambda *a, **k: ["github.com", "api.dexscreener.com"])
    D = dg.gather(d, 24, now=NOW, procs=PROCS_OK, net=True); out = dg.report(D)
    assert "✖ Ubuntu no resuelve 2 de 7 direcciones de internet (github.com, api.dexscreener.com…)" in out and "Red (DNS): FALLA en github.com, api.dexscreener.com" in out
    D = dg.gather(d, 24, now=NOW, procs=PROCS_OK); assert D["dns_bad"] == [] and "Red (DNS): ok" in dg.report(D)     # tests stay offline by default


def test_dns_check_reports_unresolvable_names_without_blocking():
    t0 = time.time(); bad = dg.dns_check(("nonexistent-host-for-test.invalid",), timeout=3.0)
    assert bad == ["nonexistent-host-for-test.invalid"] and time.time() - t0 < 4.0


def test_duplicates_are_reported_on_wsl_without_autostart(tmp_path, monkeypatch):
    """02-nov regression: under WSL without autostart the duplicate-bot warning was swallowed by a misplaced elif"""
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    _, out = run(make(tmp_path), procs=PROCS_OK + ["10 python3 bot.py --exchange solana --live"])
    assert "Hay 2 copias del bot de Solana" in out and "Sin arranque automático" in out
