# PLAYBOOK: operating the multi-exchange trading bot

## Layout
| File | Role |
|---|---|
| `bot.py` | Engine: one process per exchange, with its own balance, state and logs |
| `exchanges.py` | Exchange adapters (`Binance`, `Coinbase`), registered in `ADAPTERS` |
| `intel.py` | Market regime from BTC, support/resistance, volume profile, order-book imbalance, news/Fear & Greed/Binance announcements |
| `features.py` | Shared 1h features + trend signal (used by the live bot and the backtests) |
| `backtest.py` | 5m momentum backtest (in-sample/out-of-sample) |
| `backtest_wf.py` | 1h walk-forward: trend, ML, ensemble; long/short; taker vs maker fees. Writes `bt_results.json` |
| `train_model.py` | Optional ML model, saved to `model.pkl` (ML is OFF: walk-forward AUC was 0.497) |
| `config.json` | All parameters. Per-exchange section under `exchanges.<name>` |
| `state_<ex>_<mode>.json` | Saved cash, positions, cooldowns and trades (survives restarts) |
| `trades_<ex>_<mode>.csv` | Every fill |
| `bot_<ex>.log`, `stdout_<ex>.log`, `supervisor.log` | Logs |

## Daily operation
- Start the 24/7 service: `cd /workspace/ai-trading-bot && nohup setsid ./run_forever.sh >/dev/null 2>&1 &`
- Status: `./status.sh` (processes, universe size, equity, last scan, error count, last trades)
- Stop: `./stop.sh`
- Snapshot of current signals: `python3 bot.py --exchange binance --scan`
- Follow live: `tail -f bot_binance.log | grep -E "TRADE|REGIME|KILL|equity="`
- P&L: `python3 -c "import pandas as p;d=p.read_csv('trades_binance_paper.csv');print(d[d.side.isin(['SELL','COVER'])].pnl.describe())"`

## Analyze / retune
1. `python3 backtest_wf.py 240 30`: 240 days, top 30 pairs, walk-forward. Read `bt_results.json`.
2. `python3 backtest.py 60 30`: 5m momentum grid, in-sample vs out-of-sample.
3. Only change `config.json` for settings that hold up out-of-sample (net > 0 and profit factor > 1.1 on the unseen part). Restart: `./stop.sh && nohup setsid ./run_forever.sh &`.
- Switch strategies on/off with `strategies.{momentum,trend_1h,pullback,mean_reversion,ml_filter}`. Scale each with `strategy_size`.

## Modes
- Paper (default): `exchanges.<ex>.mode = "paper"`.
- Live: set `exchanges.<ex>.mode="live"` and export the keys, then run `LIVE_CONFIRM=YES python3 bot.py --exchange <ex> --live`.
  - Binance keys: `BINANCE_API_KEY`, `BINANCE_API_SECRET`. Enable trading only, disable withdrawals.
  - Coinbase keys: `COINBASE_API_KEY` (CDP key name `organizations/.../apiKeys/...`), `COINBASE_API_SECRET` (EC private key PEM).
  - Not yet tested against a real account. Live fill reconciliation is minimal. Test with the minimum size first.
- Orders: `entry_order: "maker"` places post-only limit entries (LIMIT_MAKER / post_only), cancelled after `maker_timeout_s`. `"taker"` uses market orders.
- `bnb_fee_discount: true` applies a ×0.75 fee factor (you need BNB in the account and "Use BNB for fees" on).
- Short selling: `allow_short: true` simulates shorts in paper only. Live shorting needs a futures/margin adapter (not built yet).

## Adding an exchange
1. In `exchanges.py`, subclass `Exchange`. Set `name`, `quote`, `btc` and implement:
   - `universe(min_vol)`, `books()` (one bulk call), `book(sym)`, `klines(sym, tf, n)` (closed candles, columns t,o,h,l,c,v,tb), `depth(sym, n)`;
   - `live_order(sym, side, qty, quote_amt, limit_px, maker)`, `live_order_status`, `live_cancel`.
2. Register it: `ADAPTERS["kraken"] = Kraken`.
3. Add `exchanges.kraken` to `config.json`: mode, enabled, min_quote_volume_24h, fee_taker_pct, fee_maker_pct.
4. Test with `python3 bot.py --exchange kraken --scan`, then restart the service. It gets its own state, CSV and log automatically.

## Pata Hyperliquid (Keel + Coinversa) — añadida el 31-oct-2026
| Qué | Dónde | Cuándo |
|---|---|---|
| Estrategia elegida y evidencia | `hl_leg/README.md`, `hl_leg/evidence.json` | al cambiar cualquier parámetro |
| Paper run en Keel | `hl_leg/hl_paper.json` → https://app.usekeel.io/paper/dep_01m69ygrjews0qmgq2sraj8rdr (estrategia causal; la anterior dep_01m69j62… está parada) | **visitar al menos cada 4 semanas** (se pausa sola a los 28 días sin visita); revisar fills vs backtest en la revisión diaria |
| Contexto Coinversa (riesgo) | `data/hl_risk.json`, `data/hl_context.csv` (`python3 -m hl_leg.hl_context --once`) | revisión horaria: banderas `crowd_with_us`, `apex_against`, `liq_cluster`, `high_leverage` por moneda |
| Panel | `/api/hl` | cada 15 min como el resto |
| Pasar a real | criterios en `hl_leg/hl_paper.json` (≥21 días / ≥20 evaluaciones con paridad ±50 pb, ≥150 $ en Hyperliquid, apalancamiento 1x) | decisión manual de Àngel en la web de Keel |

Claves nuevas en `config.json` (`exchanges.solana`, todas con valor por defecto en el código): `rc_timeout_s` 8, `rc_fail_cache_s` 180, `rc_scan_budget_s` 150 (RugCheck),
`hardfail_skip_s` 3600 (no re-evaluar un mint con veto determinista durante 1 h), `writeoff_sellfail` 5 / `writeoff_min_s` 900 / `writeoff_max_liq_usd` 1000 (write-off de posiciones muertas en real).
Variables de entorno nuevas: `COINVERSA_API_KEY` (opcional; sin ella el logger de contexto no hace nada), `COINVERSA_BASE_URL`, `COINVERSA_ENDPOINTS_JSON`.

### 1-nov: Director, rent de ATAs y panel v2
| Qué | Dónde | Regla |
|---|---|---|
| Panel v2 | `/` (login de siempre); `/live` y `/v1` siguen | cada tarjeta lleva hora y bandera de frescura; "sin datos" nunca se sustituye por un número |
| Rent de ATAs | `python3 tools/close_atas.py` (dry run) → `--yes` con OK de Àngel | solo cuentas con saldo 0; el memebot cierra sola la cuenta tras cada venta completa (`ata_autoclose`) |
| Director | `director_state.json`, `director_log.jsonl`, `python3 director.py --report` | sombra 24 h, luego manda solo endureciendo; `director_enabled: false` lo deja en sombra; estado obsoleto > 3 h = config base |
| Cerebro v2 | `brain_state.json` → `model_choice`, `calibration`, `oos.models` | la logística solo se despliega si gana OOS en retorno y Brier; `brain_ev_min` lo fija el Director |
Claves nuevas: `ata_autoclose` true · `brain_ev_min` 0.01 · `director_enabled` true.

