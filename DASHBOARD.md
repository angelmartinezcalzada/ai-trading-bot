# Panel v2 — contrato de datos y diseño (31-oct-2026)

Panel web en vivo, profesional, **solo con datos reales** de la máquina del bot. Se sirve desde el mismo `dashboard.py`
(puerto 8787, contraseña de `dashboard_password.txt`) en la ruta `/`; `/live` y `/panel` siguen existiendo.
Ningún número se inventa: cada bloque lleva la marca de tiempo del fichero del que sale y una bandera `fresh`; si el
fichero no existe o está obsoleto, el panel lo dice ("sin datos" / "obsoleto desde hh:mm") en vez de enseñar un valor.

Ficheros nuevos: `dash_data.py` (agregador puro, sin red), `dashboard_v2.html` (interfaz, un solo fichero, sin CDN),
`tests/test_dash_data.py` + `tests/dash_fixture.py` (fixture sintético, solo para tests y vista previa), `tools/preview_dashboard.py`.

## 1. `dash_data.py` — contrato

```python
build_overview(root: str, now: float | None = None) -> dict
```
Lee SOLO ficheros bajo `root` (la carpeta del bot). Nunca llama a la red ni a `live_sol`. Nunca lanza: un fichero ausente,
vacío o corrupto deja su sección con `available: false` y `error: "<motivo corto>"`. Lee colas de ficheros grandes con
`tail` por bytes (nunca el fichero entero de logs/CSV/jsonl grandes: tope 300 KB por lectura).

Todas las secciones comparten esta cabecera:

```json
{"available": true, "source": "status_solana.json", "ts": 1793400000.0, "age_s": 12.3, "fresh": true, "fresh_after_s": 120}
```
`ts` = marca del dato (campo `ts` del JSON o mtime del fichero); `fresh = age_s < fresh_after_s`.
Umbrales: status_* 120 s · equity csv 300 s · insider_status 900 s · copytrade 900 s · brain_state 3·3600 s · hl_risk 2·3600 s ·
candidates/log 900 s · supervisor.log 3600 s · context_now 2·3600 s · insider_rank 2·3600 s (`FRESH["context"]`, `FRESH["insider_rank"]`).

### Secciones (todas obligatorias en la respuesta, aunque sea `available: false`)

| clave | fuente real | contenido |
|---|---|---|
| `meta` | reloj + `config.json` + `pgrep` | `now`, `host` (hostname), `exchanges` configurados con `mode`/`enabled`, `tunnel_url` (de `tunnel_url.txt` si existe), `stop_all` (`STOP` existe) |
| `health` | `pgrep -f "python3 bot.py --exchange <ex>"`, `STOP_<ex>`, `KILL_<ex>`, `control_<ex>.json`, `supervisor.log` | por exchange: `pids`, `health` ∈ {ok, arrancando, caído, parado} (misma regla que `/api/state`), `stopped`, `killed`, `paused`; `supervisor_tail` (12 líneas); `insider_pid`, `dashboard_pid` |
| `solana` | `status_solana.json` (escrito por `memebot.status()`) | `mode`, `equity`, `cash`, `day_pnl_pct`, `day_pnl_usd` (= equity − equity/(1+day_pnl_pct/100)), `halted`, `paused`, `wallet` {`addr_short` (4…4), `sol`, `usd`, `t`}, `live_min_sol`, `sol_usd` (regime.sol_usd), `universe`, `positions[]` (ver abajo), `stats` {`closed`, `win_rate`, `net_pnl`}, `pump_play` {`trades`,`pnl`,`wins`,`open`}, `signals` (últimas 10: t, sym, type, strategy, side), `movers` (top 10: sym, chg5), `smart_items` (top 10: sym, flags, held), `ai_pump` (top 6: sym, pump, exh) |
| `solana.positions[]` | `status_solana.json.positions` + `state_solana_<mode>.json.pos[mint]` | `sym`, `mint_short`, `mint`, `entry`, `mark`, `best` (state.pos.best), `cost`, `pnl`, `pnl_pct`, `age_min`, `score`, `strategy`, `partial`, `stop` (status.stop), `trail_level` = best·(1−trail_pct_cfg) si trailing activo, `trailing` (bool), `tp`, `pump` (play=="pump"), `sellfail` y `noroute` (state.pos; 0 si no están), `rent_usd`, `dist_stop_pct` = (mark/stop−1)·100, `dist_trail_pct` |
| `solana.equity_curve` | `equity_solana.csv` (`epoch,equity`) | `points_24h` (≤300 puntos `[ms, equity]`, submuestreo uniforme), `points_7d` (≤300), `first_24h`, `last`, `min_24h`, `max_24h`, `n_rows_read` |
| `solana.daily_pnl` | `trades_solana_<mode>.csv` + `trades_solana_live.csv` si mode==live (filas SELL, campo `pnl`) | últimos 14 días: `[{"day": "2026-10-31", "pnl": -1.2, "n": 7, "wins": 2}]` (día en hora local de la máquina), `total_14d` |
| `solana.kpi_30d` | mismas filas SELL, 30 días | `n`, `wins`, `win_rate`, `gross_win`, `gross_loss`, `profit_factor` (null si gross_loss==0), `avg_win`, `avg_loss`, `expectancy`, `fees` (suma `fee` de todas las filas 30 d), `best` {sym, pnl, time}, `worst` {sym, pnl, time} |
| `solana.trades` | `trades_solana_<mode>.csv` (últimas 60 filas, más recientes primero) | `time`, `sym`, `side`, `price`, `qty`, `fee`, `pnl`, `reason` (sin `tx=…`, ≤120 chars), `equity`, `is_real` (reason contiene "REAL") |
| `solana.scan` | `bot_solana.log` (cola 300 KB) | última línea `prefilter …` parseada: `ts`, `ok`, `total`, `eval`, `skipped_hardfail`, `rc_fetched`, `rc_needed`, `rc_past_budget`, `secs`; última línea `SCAN` (`ts`, texto ≤160); `age_s` desde la última; `last_buy_block` (última `LIVE buy … blocked:` ≤160 chars con ts) |
| `solana.funnel` | `candidates_solana.jsonl` (cola 300 KB, ≤500 filas más recientes) | `rows`, `passed`, `window_from`/`window_to` (ts primera/última), `by_fail` [{reason, n}] ordenado desc (razón = primer elemento de `fail`), `by_src` [{src, n}], `last_passed` (5 más recientes: ts, sym, score si existe) |
| `solana.brain` | `status_solana.json.brain.model` si fresco, si no `data/brain_state.json` | `active`, `updated`, `n_labelled`, `n`, `base`, `avg_win`, `avg_loss`, `oos` (dict tal cual), `decisions` (últimas 8 de status.brain.decisions si existen) |
| `solana.eval` | `eval_solana.json` | tal cual (dict) o `available:false` |
| `solana.limits` | `config.json.exchanges.solana` | solo lectura: `max_positions`, `stop_pct`, `trail_pct`, `trail_activate_pct`, `partial_tp_pct`, `daily_max_drawdown_pct`, `max_position_pct`, `risk_per_trade`, `min_score`, `brain_min_score`, `min_liquidity_usd`, `max_hold_hours`, `exit_mode`, `pump_play` |
| `insider` | `insider_status.json` | `tracked`, `cycle_s`, `live_ranked`, `counts`, `alerts` (últimas 10, más recientes primero: t, mint_short, elite, n, score), `conv` (top 5 por score: mint_short, score, n, elite), `feed` (últimos 20: t, kind, w_short, mint_short, sol, tier) |
| `copytrade` | `state/copytrade_paper.json` + `trades_solana_copy_paper.csv` | `mode:"paper"`, `closed`, `pnl`, `open` [{sym, e, t, liq, rug_n}], `recent` (20 filas: time, symbol, side, price, usd, pnl, reason), `wins`, `win_rate` (sobre filas no-BUY con pnl) |
| `hl` | `hl_leg/hl_paper.json`, `hl_leg/evidence.json`, `data/hl_risk.json`, `data/hl_context.csv` | `paper` {deployment_id, url, strategy_name, strategy_version, started, simulated_capital_usd, schedule, expectation, go_live_criteria[], replaces?}, `evidence` {oos: {sharpe, return_pct, max_dd_pct, profit_factor}, full: {sharpe, return_pct, max_dd_pct, quarters_positive}, honest_summary}, `risk` {status, generated/ts, coins: [{coin, flags_long[], flags_short[], size_mult}] ordenado por nº de banderas desc}, `context_tail` (10 líneas CSV más recientes, parseadas con la cabecera) |
| `cex` | `status_<ex>.json`, `equity_<ex>.csv`, `trades_<ex>_<mode>.csv` para `binance` y `coinbase` | por exchange: `mode`, `equity`, `cash`, `day_pnl_pct`, `halted`, `paused`, `no_cash`, `positions` (sym, side, entry, mark, pnl, pnl_pct, age_min, strategy), `stats`, `points_24h` (≤200), `trades` (últimas 15), `regime` (dict tal cual, ≤8 claves), `fng`, `net_deposits`, `external_holdings` |
| `activity` | `bot_<ex>.log` (cola 300 KB, ≤400 líneas por exchange) | hasta 80 eventos más recientes clasificados con los regex `ACT` de `dashboard.py` (scam/trade/risk/news/signal/skip/scan/error): `t`, `ex`, `kind`, `msg` (≤240 chars, sin `tx=…`) |

| `context` | `data/context_now.json` (context.py, cada hora, atómico) + cola de `data/context.jsonl` (128 KB, ≤24 filas más recientes) | `code`, `hour_utc`, `dow` (0=lun), `sol` {usd, r1h, r4h, r24h, rv24h: % tal cual}, `btc` {usd, r1h, r4h, r24h, rv24h, regime ∈ {bull, bear, range}, regime_age_s}, `news` {risk_off (bool estricto), fng, sentiment, sources_ok, age_s}, `market` {new_pools_1h, graduations_1h, agg_vol_h1_usd, n_cands_1h, heat ∈ {hot, normal, cold}, heat_ratio}, `breadth` {n_entry, n_universe, share, med_atr_ratio}, `hl` {sol_bias, btc_bias, stress}, `health` {insider_age_s, st_budget_used, st_budget_cap, x_buzz_age_s, brain_active, director_shadow}, `regime` {sol_trend ∈ {up, down, flat}, btc_on, risk_off, heat}, `stale` [campos sin calcular]; `history` (≤24 filas de `context.jsonl` ordenadas por `ts`: {ts, r1h, risk_off, heat, new_pools_1h}; `[]` + `history_error` si falta el jsonl), `riskoff_6h` = nº de filas con `risk_off:true` entre las 6 más recientes de no más de 7 h (`null` sin filas), `riskoff_6h_n` = filas consideradas. Un bool que no sea JSON bool, un enum fuera de su dominio o un número no numérico → `null`, nunca un valor por defecto |
| `insider` (v4) | `insider_status.json` claves nuevas + `insider_rank.json` (insider_rank.py, en la carpeta del bot) | `rank_t`, `rank_tiers` {tier: n}, `tracked_by_tier` {tier: n}, `rotation_slice` (tal cual, acotado), `rpc_err_n`, `sells_n_by_mint` [{mint_short, n}] (8 mayores) y `sells_n_total` (`null` si la clave no existe); `rank` = cabecera propia (available/ts/age_s/fresh con `FRESH["insider_rank"]`) + `code`, `base_rate`, `half_life_d`, `n_launches`, `n_wallets`, `n_bots`, `tiers` {elite, good, watch} (del fichero; si falta, contados de `wallets`), `discovery` {t, n_candidates, n_added, note}; `wallets` = top 10 por `rel` desc (desempate por dirección): {addr_short (4…4, nunca la dirección entera), tier, rel, h, m, h_eff, m_eff, hr_post, part, bot (bool estricto), bot_why, early, days, med_dt, med_dslot, avg_sol, last_hit_t, last_seen_t, cluster, live_n, live_hit, live_mean, pnl_win_pct, pnl_realized, pnl_unrealized, pnl_n_tokens, why}. `insider_rank.json` ausente/corrupto → `rank.available:false` y `wallets: []`; la parte de status no se ve afectada |
| `solana.brain` (v3) | mismas fuentes | `model_choice`, `code_version`, `lambda`, `archive_n`, `folds_n`, `folds_pos` (folds con retorno OOS > 0), `folds_mean_ret`, `folds` (acotado), `models_hist_n`, `models_hist_flips` (cambios de modelo consecutivos en `oos.models_hist`), `models_hist_last`, `calibration` [{bin, n, p_avg, win_rate}] (≤10), `updated_ts` (epoch de `updated`), `code_mtime` (mtime de `brain.py`, `null` si no existe), `code_newer_s` = code_mtime − updated_ts. Un estado v2 deja todo esto en `null` |
| `director` (v2) | `director_state.json` | `version`, `regime_gate` (dict tal cual, acotado a 12 claves/12 elementos: valores de cada dimensión con los que el Director cierra las entradas; `null` si no es un dict), `regime_gate_n` (dimensiones con valor), `regime_table` (`evidence.regime`, dict o lista, acotado a 3 niveles; `null` si falta) |

`solana.positions[].dist_*` y `trail_level` se calculan solo con campos presentes; si falta `best` o `stop`, el campo es `null`.
Los `mint`/`w` completos solo aparecen en `solana.positions[].mint` (necesario para la acción `close`); el resto se acorta 4…4.
`trades_solana_<mode>.csv` con `mode` leído del `config.json` real (`exchanges.solana.mode`); cuando `mode=="paper"`, la sección
`solana` lleva además `real_trades_24h` = nº de filas de `trades_solana_live.csv` en las últimas 24 h (para que un panel en papel
nunca oculte que hubo actividad real).

### Fixture (`tests/dash_fixture.py`)
`make_fixture(dir, now)` escribe en `dir` un juego **sintético y claramente etiquetado** (símbolos `FIX1…`, direcciones `Fixture…`):
`config.json` (mínimo: `exchanges` solana paper + binance paper + coinbase live, campos de límites), `status_solana.json`
(2 posiciones, 1 con trailing activo, wallet, brain.model, stats, pump_play, signals, movers), `state_solana_paper.json`
(pos con best/sellfail/noroute/rent_usd), `equity_solana.csv` (8 días cada 30 s → ~23.000 filas; probar el tail), `trades_solana_paper.csv`
(40 filas en 20 días con BUY/SELL, pnl ±, reasons con `tx=abc`), `trades_solana_live.csv` (3 filas REAL en las últimas 24 h),
`candidates_solana.jsonl` (120 filas: fail liq/rugcheck_unavailable/hardfail_recent/lp_unlocked/pass), `bot_solana.log`
(líneas `SCAN`, `prefilter 60/120 -> eval 40 (5 skipped: hard-vetoed <3600s ago), rugcheck fetched 38/40 (2 past budget) in 97s`,
`LIVE buy FIX1 blocked: EV 0.5% < 3x real round-trip 0.3%`, `TRADE`, `KILL SWITCH`, `ERROR`), `insider_status.json`, `state/copytrade_paper.json`
+ `trades_solana_copy_paper.csv`, `data/brain_state.json`, `eval_solana.json`, `hl_leg/hl_paper.json`, `hl_leg/evidence.json`, `data/hl_risk.json`,
`data/hl_context.csv`, `status_binance.json`, `equity_binance.csv`, `trades_binance_paper.csv`, `status_coinbase.json`, `supervisor.log`,
`control_solana.json`, `dashboard_password.txt` (= "fixture"). Devuelve el dict con los valores esperados que los tests comprueban.
Un segundo helper `make_empty(dir)` crea solo `config.json` para probar el camino "sin datos".

### Tests (`tests/test_dash_data.py`, pytest, sin red)
- Todas las secciones presentes en ambos fixtures; en el vacío `available:false` y ningún `KeyError`.
- Frescura: `now` desplazado +1 h hace `fresh:false` en status/insider y `true` en brain.
- `daily_pnl` suma solo filas SELL por día; `kpi_30d.profit_factor` = gross_win/gross_loss del fixture; `fees` correcto.
- `equity_curve.points_24h` ≤ 300 puntos, primero y último correctos; lee ~23.000 filas por tail sin cargar todo (tiempo < 0,5 s).
- `funnel.by_fail` ordenado, `passed` correcto; `scan` parsea la línea `prefilter` (ok=60,total=120,eval=40,rc_fetched=38,rc_needed=40,past_budget=2,secs=97).
- `positions[0].trail_level == best*(1-trail_pct)` cuando `trailing`; `dist_stop_pct` correcto; `sellfail/noroute` leídos del state.
- `activity` clasifica `KILL SWITCH` → risk, `SCAM block` → scam, `Traceback` → error; quita `tx=…`.
- `hl.risk.coins` ordenado por banderas; `copytrade.win_rate` correcto; `real_trades_24h == 3` con mode paper.
- `/api/overview` con el cliente de Flask: 401 sin sesión; 200 con sesión y `meta.now` presente (fixture copiado a `tmp_path`, `dashboard.py` importado con `cwd` ahí: usar `importlib` tras `os.chdir`).
- Módulos v3 (helpers sintéticos en `tests/test_dash_data.py`: `ctx_now`, `write_context`, `rank_json`/`write_rank`, `brain_v3`, `DIRECTOR_V2`): `context` presente/obsoleto/ausente/corrupto, tipos estrictos (bool "yes" → null, heat "lava" → null), histórico de 24 filas y ventana `riskoff_6h` (filas > 7 h no cuentan, jsonl ausente → `null`); `insider.wallets` top 10 ordenado, direcciones solo 4…4, `rank` obsoleto/ausente/corrupto sin tocar el status; campos brain v3 y `code_newer_s`; `regime_gate`/`regime_table` acotados; umbrales nuevos y presencia de las secciones en `dashboard_v2.html`.

### Operador (`operador.py`) sobre estas secciones
- Hallazgos nuevos: `context_stale` (**warn**: `context` ausente/ilegible o `fresh:false`, es decir ≥ 2 h; alerta deduplicada 6 h como todas), `news_riskoff_6h` (info: `riskoff_6h == riskoff_6h_n >= 6`, riesgo-off sostenido 6 filas horarias; no se evalúa con contexto obsoleto), `market_dead` (info: `market.new_pools_1h == 0` y `heat == "cold"`), `insider_rank_stale` (info: `insider.rank` ausente o ≥ 2 h), `brain_state_older_than_code` (info: sin `code_version`, o `code_newer_s` > 1 día). Los `info` nunca alertan.
- `review()` devuelve en `summary["market"]` la línea `market_line(ov["context"])`: `SOL 24 h +3.2 % (up) · BTC 24 h -1.0 % (on, range) · F&G 42 · riesgo-off no · calor normal (×1.10) · lanzamientos/h 35, graduaciones 4 · amplitud 12/80 (15 %)`; campo ausente → `?`, fichero ausente → `sin contexto (…)`, obsoleto → prefijo `obsoleto (x.x h):`, `stale` → sufijo `sin calcular: …`. `entry_text` la escribe como `- Mercado:` (entre Escaneo y Director) y el informe diario añade `- Mercado (contexto horario de context.py): …` con el recuento `riskoff_6h`. La tarjeta Operador muestra la clave `market` como "mercado".

## 2. `dashboard_v2.html` — diseño

Un único fichero, HTML+CSS+JS, **sin dependencias externas** (la máquina puede no tener salida a CDN y el panel se sirve por túnel).
`fetch('/api/overview')` cada 5 s; a 401 redirige a `/login`; si una petición falla se mantiene el render anterior a opacidad 0,6
con el aviso "sin conexión desde hh:mm:ss" (nunca pantalla en blanco ni parpadeo de esqueleto). Acciones por `POST /api/action`
con cabecera `X-CSRF` = valor inyectado en `{{csrf}}` (como hace `/panel`).

Tema oscuro profesional con tokens del sistema de dataviz (dark): página `#0d0d0d`, tarjeta `#1a1a19`, tinta `#f0efec` /
secundaria `#c3c2b7` / apagada `#898781`, rejilla `#2c2c2a`, borde `rgba(255,255,255,.10)`; serie única azul `#3987e5`;
polaridad (ganancia/pérdida) = par divergente azul `#3987e5` / rojo `#e66767` con punto medio gris `#383835`; estado = good
`#0ca30c`, warning `#fab219`, serious `#ec835a`, critical `#d03b3b` **siempre con icono + texto**, nunca solo color.
Tipografía `system-ui`; números grandes proporcionales, `tabular-nums` solo en tablas y ejes. Gutter 16 px en móvil, sin scroll horizontal.

### Estructura (orden de arriba abajo; en ≥1024 px rejilla de 12 columnas, en móvil una columna)
1. **Barra superior**: "Bot de trading · en directo", punto verde pulsante si `solana.fresh`, "actualizado hh:mm:ss", chips de salud
   por proceso (solana/binance/coinbase/insider/dashboard: ok/arrancando/caído/parado con icono), chip `STOP`/`KILL` si procede, enlace túnel.
2. **Fila de KPI (6 tiles)**: Patrimonio Solana (equity, modo REAL/PAPEL como etiqueta, y debajo "wallet 0.xx SOL ≈ y $" con su `t`),
   Hoy (day_pnl_usd y %, color por polaridad con ▲/▼), Posiciones abiertas (n / max_positions, PnL latente suma), 30 días
   (PF, win rate, n), Último escaneo (edad, segundos, "rugcheck 38/40"), Riesgo (estado: `halted`→"⛔ KILL/HALT", `paused`→"⏸ pausa",
   si no "✅ operando"; y "stop diario −x %"). Cada tile muestra "sin datos" u "obsoleto" cuando `available:false` o `fresh:false`.
2b. **Contexto de mercado** (tarjeta `#context`, de `context`): tiles compactos (`.tiles`, rejilla auto-fill ≥140 px: 2 columnas en móvil) SOL 24 h (1 h / 4 h / precio), tendencia SOL (▲/▼/→ + volatilidad 24 h), BTC on/off (régimen y su edad, 24 h), miedo y codicia (edad de las noticias, fuentes), riesgo-off (⛔/✅, sentimiento, `riskoff_6h/riskoff_6h_n`), calor (🔥/●/❄, ratio, volumen 1 h), lanzamientos/h (graduaciones, candidatos), amplitud (n_entry/n_universe en %, ATR mediana); línea pequeña con sesgo HL, salud (insider, presupuesto ST, X, cerebro, Director), chip ⚠ `sin calcular: …` si `stale` no está vacío, y una **sparkline de 24 puntos de `history[].r1h`** (línea azul con base cero, 160×36 px) solo cuando hay ≥2 puntos; si no, se omite. Cabecera: hora UTC, día de la semana y hora del dato. Sin fichero: "sin data/context_now.json".
3. **Fila principal**: izquierda (8 col) **curva de patrimonio** (SVG, línea 2 px azul, área 8 % de opacidad, eje y recesivo con 3-4 ticks,
   eje x con horas; selector 24 h / 7 d como fila de filtro ENCIMA del gráfico; crosshair + tooltip con hora y valor; botón "tabla" que
   muestra las últimas 20 filas); derecha (4 col) **PnL diario 14 días** (barras finas, 4 px de radio en el extremo, hueco 2 px, azul/rojo
   por signo, etiqueta directa solo en la mejor y la peor; tooltip por barra; vista tabla).
4. **Posiciones abiertas** (tabla): sym, edad, entrada, marca, PnL $ y %, distancia al stop y al trailing (barra de progreso fina
   entre stop y máximo), score, banderas (½TP, PUMP, trailing, `sellfail` n, `noroute` n), botón "Cerrar" (confirm). Vacío: "Sin posiciones — todo en efectivo".
5. **Escaneo y embudo**: tarjeta con la última línea `prefilter` (ok/total/eval, rugcheck x/y, past budget, segundos, edad) y barras
   horizontales ordinales por motivo de veto (`by_fail`, azul rampa ordinal 250→550 por rango) + `passed`; "último bloqueo de compra real" con ts.
6. **Operaciones recientes** (feed, 60): fecha, sym, COMPRA/VENTA, precio, PnL con signo y polaridad, motivo; badge REAL cuando `is_real`.
7. **Fila de inteligencia (3 tarjetas)**: Insiders (tracked, ciclo, top conv, últimos alerts, y la **tabla de wallets** de `insider.wallets`:
   wallet 4…4 + badge `bot` (title = bot_why) + clúster, nivel (élite/buena/vigilada con color + texto), fiab. = rel·100 %, ✓/✗ = h/m, part. = part·100 %,
   vivo = live_n · live_hit · live_mean, PnL = pnl_win_pct %; encabezado con badge de `rank` (sin datos/obsoleto), recuento de tiers, puntuadas, bots y
   lanzamientos; pie con `rank_t`, `rpc_err_n`, `rotation_slice`, `tracked_by_tier`, `sells_n_total`; tabla dentro de `.scroll` para móvil),
   Copytrade papel (cerrados, PnL, win rate, abiertas), Cerebro (activo/sombra, n_labelled, actualizado, OOS policy: brain vs baseline avg ret,
   decisiones recientes, y los campos v3: modelo `model_choice` + `code_version` (badge ⚠ "sin code_version" si falta) + λ + archivo, folds n/positivos/media,
   `models_hist_n` reajustes y `models_hist_flips` cambios, badge ⚠ si `code_newer_s` > 1 día, calibración por cubos).
8. **Hyperliquid (Keel)**: id del paper run (enlace), estrategia, capital simulado, iniciado, `expectation` tal cual, evidencia
   OOS/ventana completa (texto, no gráfico), estado de riesgo Coinversa (`status` con icono) y monedas con banderas.
8b. **Director** (v2): además de tamaño/umbrales/salida/horas, fila "régimen" con `regime_gate` (cada dimensión y sus valores cerrados, `why` en gris;
   "sin puerta de régimen (estado vN)" si no existe) y, bajo la tabla de jugadas, `regime_table` renderizada con `genericTable` (dict de dicts, un nivel más
   permitido, o lista de dicts → tabla escapada de ≤24 filas × ≤6 columnas; cualquier otro valor como texto).
9. **CEX**: una tarjeta por exchange (modo, equity, hoy, posiciones, salud, mini-sparkline 24 h SVG 2 px).
10. **Actividad**: lista de eventos con filtro por tipo (chips: todo/trade/risk/scam/error/scan/signal/skip/news), 80 líneas.
11. **Controles** (sección plegada por defecto): por exchange: Pausar/Reanudar entradas, Parar/Arrancar proceso, KILL (requiere
    escribir KILL en un prompt) / Desactivar kill. Mismas acciones y mismos mensajes que `/api/action`; sin edición de límites
    (se muestran solo lectura en `solana.limits`).
12. Pie: "Datos del propio bot (ficheros de estado); ningún valor se calcula fuera de la máquina. Umbrales de frescura: …".

Accesibilidad: cada gráfico tiene título, vista tabla y `aria-label`; colores de estado siempre con icono+texto; foco visible;
`prefers-reduced-motion` desactiva el pulso. Sin `Date.now()` en el render de datos: todas las horas vienen del servidor (`meta.now`, `ts`).

## 3. Integración en `dashboard.py`
- `from dash_data import build_overview`; ruta `GET /api/overview` → `jsonify(build_overview(D))` (bajo el guard de sesión).
- Ruta `/` → `dashboard_v2.html` con `{{csrf}}` sustituido (igual que `/panel`); `/v1` → el antiguo redirect a `/live`.
- `tools/preview_dashboard.py <dir>`: crea el fixture en `<dir>`, copia `dashboard.py`, `dash_data.py`, `dashboard_v2.html`, `live_view.py`
  y arranca Flask en 127.0.0.1:8790 con `cwd=<dir>`; se usa para la captura con Playwright (login con "fixture", capturas a 1280 y 390 px).
