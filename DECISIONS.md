## 2026-10-30 07:56 CET — revisión horaria (director financiero)
- Salud: binance, coinbase y solana vivos (paper). Logs frescos. Errores binance son antiguos (KeyError trail_on, 29-oct 19:52). Solana/coinbase reiniciados varias veces 06:32–07:43 (exit 0, despliegues de código).
- Equity: Binance 998.80 (sin posiciones, régimen bear, filtro BTC>50d OFF), Coinbase 1000.00 (idem), Solana 975.64 (cash 607, abiertas JOB, REMUS, DESSA, USDF, HEXN).
- Solana: 7 salidas cerradas desde 06:32, PnL realizado −24.8 USD (stops −5.0, −8.8, −4.8, −8.6; Foxii partial TP +9.1 y luego "breakeven" −10.2 por desplome ~−40% en ~1 min, el stop se saltó por gap; HYPERCHAN trail +3.5).
- eval_solana (72h replay): PASS media −4.0% win 18% (n=11); rechazos score<60 −2.9%, top10 −2.6%. Muestra pequeña.
- Cambios: ninguno. Muestra <30 trades por bucket; no se ajusta. Código memebot.py modificado a las 07:42 (v3), dejar correr.
- Próxima vez: vigilar si stops/gaps siguen dominando; con >=30 cierres evaluar umbral de score y stop; revisar ejecución de breakeven tras partial TP.

## 2026-10-30 09:05 CET — revisión horaria (director financiero)
- Salud: binance, coinbase y solana vivos (paper), logs frescos, sin reinicios desde 07:43, sin tracebacks nuevos.
- Equity: Binance 998.80 y Coinbase 1000.00 (sin posiciones, régimen bear, filtro BTC>50d OFF). Solana 971.57 (cash 674.57; abiertas JOB, REMUS, USDF, SENSE).
- Solana desde 07:56: HEXN trail +4.74, DESSA stop −4.94, compra SENSE (score 48.7). Acumulado 9 cierres, PnL realizado −25.0 USD (2 trails/1 partial ganadores, 6 stops/breakeven perdedores).
- eval_solana 08:32 (72h): PASS replay media −3.0% win 36% (n=11); precio actual de PASS +5.8% → las salidas (stops) cortan más de lo que el token cae. Muestra pequeña.
- Cambios: ninguno (<30 cierres). Próxima vez: con >=30 cierres evaluar anchura de stop vs trail; vigilar gaps tras partial TP.

## 2026-10-30 09:10 (Madrid) — Memebot v3.1: exits más anchos + confirmación de momentum
Datos: 29 avistamientos tradeables (liq>=50k, solo fallos score/top10) con velas 1m reales (research/meme_paths.py), walk-forward 60/40 por tiempo (research/meme_opt.py).
- Trail: activación 12%->20%, trail 6%->10%. Mejora en train y test en todas las variantes (todas las puntuaciones: train -3.58%->-2.51/-1.80%, test -2.23%->+0.19/-0.14%). Los trails cortos cortaban ganadores (HEXN/HYPERCHAN) por ruido.
- Stop 6%->10% (max 15%): con score>=45 train -1.05%->+6.0%/op, test +7.1%->+21.6% (n pequeño: 6/2). Los stops al 6% saltaban en 1-20 min (HYPERCHAN, FLOAT, HEXN) por ruido + coste ida/vuelta ~2-3%.
- Riesgo total NO sube: position_pct 0.08->0.05 (pérdida a stop por operación ~0.48%->~0.50% del equity).
- require_momentum: entrar solo si m5>0 y h1>0. Todas las puntuaciones: -1.11% (n=29) -> +0.28% (n=12).
- min_score 45 se mantiene (score<45 tiene expectativa negativa).
Advertencia: muestra pequeña; revalidar con meme_opt.py cuando haya >100 avistamientos. Backups: memebot.py.bak_v3, config.json.bak_v3.
Pendiente: etiquetar candidatos evaluados a futuro como muestras del Cerebro.

## 2026-10-30 09:58 CET — revisión horaria (director financiero)
- Salud: los 3 procesos vivos (paper), logs frescos. Solana reiniciado 09:07 (despliegue v3.1 + Cerebro activo, exit 143). Errores binance siguen siendo los antiguos.
- Equity: Binance 998.80, Coinbase 1000.00 (sin posiciones, régimen bear, filtro BTC>50d OFF). Solana 973.79 (cash 727.95; abiertas REMUS, USDF, SENSE, UDTF, USDP).
- Solana desde 09:05: JOB stop −4.91; compras UDTF (score 28.5) y USDP (31.2) decididas por el Cerebro (activo desde 09:09, n=116, OOS 12 ops +4.58% vs base +3.93%), que ignora min_score. Realizado acumulado hoy ≈ −29.9 USD en 10 cierres.
- Cambios: ninguno (v3.1 y Cerebro llevan <1h; muestra insuficiente).
- Próxima vez: medir aparte las operaciones del Cerebro con score<45 (UDTF, USDP); si tras ~15-20 cierres van peor que score>=45, añadir suelo de score al Cerebro. Vigilar que tokens tipo stable/yield (UDTF, USDP) no dominen.

## 2026-10-30 10:20 (Madrid) — Noticias en tiempo real + comparativa de modelos
**news.py (nuevo)**: sondea cada 120 s RSS de CoinDesk, The Block, Decrypt, Cointelegraph; anuncios de Binance (listados/deslistados); Fear & Greed (alternative.me). CryptoPanic sin clave = 404; X/nitter = 410 (no disponibles). Clasificador por palabras clave -> importancia 1-3, sentimiento -1..1, monedas afectadas, macro sí/no. Guarda news.jsonl y news_state.json.
Uso en el bot:
- risk_off (noticia imp 3 negativa macro/exchange <2 h, o F&G <= 15): swing CEX no abre entradas; memebot umbral de score +10 y tamaño x0.5.
- Moneda con noticia negativa (imp>=2, 6 h) -> entrada bloqueada (news_negative). Positiva imp 3 (p.ej. listado) -> umbral -5.
- Hoy: hackeo de Binance de $6.3B -> risk_off activo.
Dashboard y canvas_data.json muestran las noticias importantes, F&G y el estado risk-off.

**Modelo (research/model_cmp.py)**: walk-forward con purga (train solo con muestras cuya salida termina antes del test), 52 muestras / 2.7 h, OOS n=13:
| modelo | AUC | Brier | ret mitad superior |
| Cerebro actual | 0.29 | 0.34 | -9.8% |
| Regresión logística | 0.30 | 0.54 | -7.0% |
| Gradient boosting | 0.40 | 0.32 | -2.8% |
| Score solo | 0.58 | – | +0.3% |
Ningún modelo aprendido supera al azar ni al score -> NO se despliega ML. Se queda score + Cerebro en modo sombra. Revalidar con >=300 muestras.
**Compras de bajo score del Cerebro** (UDTF 28.5, USDP 31.2): el score tiene la única señal OOS positiva -> brain_min_score=45 también cuando el Cerebro está activo. El filtro de stablecoins se amplía a símbolos con "USD" y precio 0.5-1.5.

## 2026-10-30 10:35 (Madrid) — Niveles por moneda (ATR / estructura / perfil de volumen): validados, NO desplegados
research/levels.py: niveles calculados por moneda con sus velas de 1m: ATR(30), soporte = max(mínimo swing 30 m, POC del perfil de volumen bajo la entrada), resistencia = máximo swing 60 m, stop = por debajo de la estructura y a >= k·ATR, TP1 = resistencia o entrada + k·ATR, trail = k·ATR actualizado en vivo, salida por decaimiento del momentum, entrada esperando pullback (límite a -k·ATR) o confirmación de ruptura.
Comparación walk-forward (research/levels_opt.py, volscale_opt.py), 115 muestras con velas 1m reales, 60/40 por tiempo, ambas con el mismo riesgo por operación (0.5% del equity, tamaño = riesgo / distancia al stop):
| versión | train (n=69) | test (n=46) |
| v3.1 actual | -9.0 pb/op | +0.8 pb/op |
| mejor dinámica, entrada a mercado (ks6 ktp15 ktr8) | -8.8 | -1.8 |
| mejor dinámica, ruptura confirmada | -4.1 (n=24) | -4.5 (n=30) |
| mejor dinámica, pullback | -7.6 (n=47) | -14.5 (n=21) |
| v3.1 escalada por la volatilidad de la moneda (ATR%/mediana)^0.75 en [0.7,1.5] | -4.1 | -0.4 |
Solo el 0.8% de las 256 configuraciones supera a v3.1 en el test -> la regla era desplegar solo si es >= v3.1 fuera de muestra: NO se cambian las salidas.
Desplegado en modo sombra: cada compra calcula y registra sus niveles (levels_solana.jsonl, motivo de la operación, columna Objetivo del panel). exit_mode="v31" en config; backup memebot.py.bak_v31.
Swing Binance/Coinbase: ya usa niveles por moneda (canal Donchian 120/40 de cada moneda); solo queda fijo el stop de desastre -35% (sin probar todavía).

## 2026-10-30 10:42 (Madrid) — DECISIÓN DEL PROPIETARIO: niveles de salida por moneda activados (exit_mode="volscale")
Àngel eligió activarlos aunque el test fuera de muestra fue algo peor que v3.1 (-0.4 vs +0.8 pb/op; en train -4.1 vs -9.0).
- Cada moneda: multiplicador = (ATR% 1m de esa moneda / mediana 1.328%)^0.75, limitado a [0.7, 1.5]. Stop 10%·m (+coste ida/vuelta, máx 1.5×), TP parcial 25%·m, trail 10%·m (runner 12%·m) que se activa en +20%·m.
- Tamaño por riesgo: riesgo 0.5% del equity / distancia al stop, máximo 8% del equity (risk_per_trade 0.005, max_position_pct 0.08). El riesgo total no sube.
- Las 4 posiciones abiertas recibieron niveles con sus propias velas de 1m: REMUS ATR 0.91% -> stop 10.0%, TP 18.9%, trail 7.5% desde +15.1%; USDF 1.38% -> 12.7% / 25.8% / 10.3% desde +20.6%; UDTF 0.68% y USDP 0.60% -> 7.6% / 17.5% / 7.0% desde +14.0%.
- Se registra en levels_solana.jsonl, en el motivo de cada compra y en el panel (columna Objetivo). Vuelta atrás: exit_mode="v31" en config.json (backup memebot.py.bak_v31b).

## 2026-10-30 11:00 (Madrid) — Módulo de anticipación de pumps IA (ai_pump.py): validado, todo en MODO SOMBRA
Datos: 49 pools de memecoins IA en Solana (búsqueda GeckoTerminal: ai, agent, gpt, neural, agi, bot, llm, aixbt, deepseek, grok, virtual...), 88.550 velas de 1m (33 pools con >=400 velas); walk-forward 60/40 por tiempo (research/pump_study.py, pump_study.json).
- Detector de pump (aceleración de volumen >=3x, compresión de volatilidad, ruptura, sin subida previa): train acierto 2.5% (base 0.3%, adelanto mediano 43 min); TEST acierto 0% vs base 3.8% -> no funciona.
- Detector de agotamiento/techo (clímax de volumen + extensión sobre ATR, divergencia RSI, momentum frenando): train 50% vs base 55%; test 35.9% vs base 39.8% -> no mejor que el azar.
- Expectativa por operación (riesgo 0.5%): momentum (similar al actual) test -22.7 pb; + salida por agotamiento -22.1; entrada pump -18.2 (train -4.6); pump+agotamiento -16.4; compra en retroceso (fib 38-62% que aguanta) train -42 / test -5.8.
- Ninguna parte supera la regla (mejor fuera de muestra y consistente en train) -> nada influye en las operaciones. ai_pump_mode="shadow".
- Señales de flujo (compradores, compra/venta, liquidez añadida, trending, noticias, narrativa IA caliente) no tienen histórico gratuito -> solo se registran en vivo (pump_solana.jsonl) para validarlas cuando haya datos.
- Panel: tarjeta "Memecoins IA" con puntuación de pump y de agotamiento; también por posición y en canvas_data.json. Backup memebot.py.bak_v32.

## 2026-10-30 10:58 (Madrid) — revisión horaria (director financiero)
- Salud: 3 procesos + panel vivos (paper), logs frescos (Solana 10:57). Reinicios de Solana 10:51/10:54/10:55 (exit 143) = despliegues del módulo ai_pump, no fallos; sin tracebacks nuevos. Errores binance: los 7 antiguos.
- Equity: Binance 998.80, Coinbase 1000.00 (planos; régimen bear, filtro BTC>50d OFF, risk_off por noticia del hackeo de Binance). Solana 968.90 (cash 782.38; abiertas REMUS, USDF, UDTF, USDP).
- Desde la revisión anterior: 1 cierre, SENSE stop −8.07. Hoy 11 cierres: 3 ganadores +17.41, 8 perdedores −55.43, neto −38.02 USD (PF ≈ 0.31). Escáner: 0 candidatos pasan filtros (risk_off sube umbral +10).
- Cambios: ninguno. Muestra (11) muy por debajo de 30; exit_mode="volscale" activado por Àngel a las 10:42 y ai_pump en sombra llevan <1 h.
- Próxima vez: cuando haya >=15 cierres con volscale, compararlos con v3.1; si PF sigue <0.8 con >=30 cierres, proponer pausar entradas meme. Vigilar UDTF/USDP (stable-like) que quedaron abiertas antes del filtro nuevo.

## 2026-10-30 11:25 (Madrid) — Coinbase LIVE solicitado por el propietario: BLOQUEADO por permisos de la clave
- Clave CDP (formato nuevo Ed25519): autenticación JWT OK (añadido soporte EdDSA en exchanges.py; backup exchanges.py.bak_live).
- key_permissions: can_view=true, can_trade=true, **can_transfer=true** -> por la regla de seguridad NO se activa live. Coinbase sigue en paper.
- Saldo real (portfolio DEFAULT): ~6.3 USD en total (OCEAN 44.8 ≈ 5.57 USD, GROVE 84.5 ≈ 0.63, ZETACHAIN 3.24 ≈ 0.12, ALEO 0.81 ≈ 0.02, USDC 0.002, más restos de polvo). 0 USD en efectivo.
- Para seguir: crear una clave nueva SIN permiso de transferencia/retirada (solo View + Trade) y depositar USD/USDC para operar.

## 2026-10-30 11:31 — Coinbase LIVE (owner's explicit decision)
- Owner: "conecta con coinbase y opera". New key verified: can_view=true, can_trade=true, can_transfer=false.
- coinbase mode=live (Binance and Solana stay paper). Same strategies, risk, BTC>SMA50 and news risk_off filters.
- live_cb.py: real balances (USD+USDC = cash), preview_order before each buy, min sizes/increments, real fee tier (taker 0.5%), fill confirmed via /orders/historical, reconciliation with balances on restart, KILL_coinbase file + daily_max_drawdown_pct (+ optional max_daily_loss_usd).
- Non-bot holdings (OCEAN, GROVE, ZETACHAIN, ALEO...) are reported as external and NEVER sold.
- At startup cash = 0.0023 USDC -> entries are skipped until funded.

## 2026-10-30 11:44 — Coinbase: all account assets are tradable (owner's explicit decision)
- Owner: "puedes usar todos los activos de la cuenta". live_cb.adopt(): every coin worth >= the exchange minimum (and >= $1) becomes a bot position ("adopted"), entry = current price, managed by the normal exit logic: stop -15%, TP +20%, trailing 8% from +10%, 7-day time exit -> USDC.
- Adopted coins are sold (weakest first) only when a real signal needs cash (fund()). No proactive liquidation, to avoid burning fees (0.5% taker) on tiny amounts.
- Adopted: OCEAN 44.81 (~$5.61) and SOL 0.0458 (~$4.44). Dust below $1 is not traded: GROVE, ZETACHAIN, ALEO, XCN.
- Real starting equity 10.06 (config coinbase.starting_equity); the paper equity curve was moved to equity_coinbase_paper.csv. coinbase.min_order_quote=1.
- Filters, preview_order, kill switch and the daily limit are unchanged.

## 2026-10-30 12:06 (Madrid) — revisión horaria (director financiero)
- Salud: 3 procesos + panel vivos (Binance/Solana paper, Coinbase live), logs frescos. Reinicio Solana 12:04 (exit 143) = despliegue de risk_audit (tope por posición + cierre de imitadores de stablecoin), no fallo. Sin tracebacks nuevos (binance: los 7 antiguos).
- Equity: Binance 998.80 (plano, régimen bear), Coinbase live 9.98 USD (adoptadas OCEAN, SOL; sin operaciones), Solana 886.8 (cash ~887 tras auditoría; desde 1000 al empezar).
- Desde la revisión anterior: USDF meme:stop −76.89 (−98.8%: colapso/rug entre dos comprobaciones; el stop no protegió). Auditoría 12:04 cerró UDTF +0.83 y USDP +0.17 (imitadores de stable) y recortó REMUS al tope (+0.36).
- Hoy Solana: 15 cierres, 6 ganadores +18.77, 9 perdedores −132.32, neto −113.55 USD (PF ≈ 0.14). Escáner: 0 candidatos pasan filtros.
- Cambios: ninguno por mi parte (n=15 < 30; risk_audit recién desplegado).
- Próxima vez: si PF < 0.8 con >= 30 cierres, proponer pausar entradas meme. Revisar por qué USDF pasó filtros (liq 79.6k, top10 0.77%, LP 100%) y si hace falta salida por caída brusca de liquidez del pool.

## 2026-10-30 12:05 — Coinbase: per-coin levels for adopted positions (owner: "Si")
- The fixed exits (-15/+20/8%/7d) are replaced by live_cb.cb_levels: 6h ATR14 x vol multiplier (ATR/its own median)^0.75 clipped to [0.7,1.5] (same as Solana volscale) + structure: 40-bar low (support), 120-bar high (resistance). Stop = support if it lies within 2-5 ATR, else 3 ATR x mult, clipped to 6-35%. TP = resistance if >= 1.5x stop, else 2x stop (+ fees). Trail = 2.5 ATR x mult starting from max(stop, trail+fees). No time exit. Recomputed every 6h; the stop never moves down once trailing.
- OCEAN: stop -10.4%, TP +30.3%, trail 7.1% from +10.4%. SOL: stop -6.0%, TP +27.6%, trail 7.2% from +8.2%.
- Not walk-forward validated (2 positions, no history). Owner decision.

## 2026-10-30 12:04 — Solana: USDF loss -76.89 (root cause + fix)
- USDF was bought at 07:17 with the old sizing (8% = 77.8 USD; risk sizing 0.5%/stop only arrived at ~10:50) and was a fake stablecoin (price 0.00096, organicScore 0). It was rugged in under 1 minute between checks (-98.8%; liquidity -98%): a gap, not a sizing bug in the current code.
- Fixes: max_gap_loss_pct=0.03 (position <= 3% of equity: even a full rug costs <= 3%); gap_stop log + creator blacklist; startup risk_audit (closed UDTF/USDP as impersonators, trimmed REMUS 80->27).
- Per-trade max-loss guard: Solana 1.5% of equity, CEX 3% (guard only; does not bind the -35% x 8% swing stop). Solana daily limit 12% -> 5% (CEX already 5%). The new limit fired today (day at -8.7% because of USDF) -> Solana paused until tomorrow; REMUS closed by the kill switch.

## 2026-10-30 12:10 — Solana: scam.py anti-scam filter
- Checks: Jupiter verified (whitelist), fake_stable, clone_ticker (verified symbol with a different mint), sell tax >3%, round-trip honeypot >6%, LP locked <90%, dev holds >5%, serial dev (>=20 mints), insiders >=5 (RugCheck graph), top holders >35%, organicScore <10 (wash), traders/tx <0.08, age <1h, mutable metadata, mint/freeze authority, RugCheck score >60, rugged, blacklisted creator (blacklist_creators.json, fed by gap/rug/liquidity_pull/dev_dump/max_trade_loss exits).
- Backtest (research/scam_bt.py, 11 closed tokens; data read today = look-ahead bias on dynamic metrics): loss avoided 89.78, profit forgone 1.36. USDF (fake_stable+wash), SENSE (concentrated 69%), FLOAT (insiders 17) caught; HYPERCHAN, DESSA, JOB, HEXN, Foxii not caught (normal losses). 9 of the last 15 passed candidates are flagged.

## 2026-10-30 12:33 — Solana resumed (owner's explicit decision: "sigue operando")
- Today's daily-limit pause cleared (it fired because of the pre-fix USDF rug). Daily baseline = 887.04 (the 5% limit counts from now). Scam filter, 3% cap, per-trade loss guard and paper mode unchanged.

## 2026-10-30 12:57 (Madrid) — revisión horaria (director financiero)
- Salud: 3 procesos + panel vivos, logs frescos. Reinicios 12:09/12:32/12:53/12:55 (exit 143) = despliegues, no caídas. Solana sin tracebacks.
- Coinbase live: intentos de venta de OCEAN-USD rechazados con 400 (12:12, 12:38–12:40), posición conservada; sin errores tras los reinicios de 12:53/12:55 (live_cb.py editado 12:55). OCEAN 0.1248 no estaba en stop (0.1121): revisar el motivo del cierre y la respuesta de Coinbase (posible mercado restringido de OCEAN).
- Equity: Binance 998.80 (plano, bear, sin señales), Coinbase 9.98 USD (OCEAN, SOL), Solana 887.04 (todo en cash; reanudado 12:33, 0–1 candidatos pasan filtros por escaneo, sin entradas).
- Cambios: ninguno (sin operaciones nuevas; muestra n=15 < 30).
- Próxima vez: vigilar primeras entradas con scam.py activo y el tope del 3%; confirmar que el 400 de OCEAN no se repite.

## 2026-10-30 — Solana smart-money / insider module (owner-approved, SHADOW)
- smart_money.py: public on-chain trades (GeckoTerminal) -> consistently profitable wallets (>=3 tokens, win rate >=60%, PnL >=$300), re-profiled every 2h -> smart_wallets.json.
- Every ~2 min, for held tokens and recent candidates: smart buyers and sellers, early-buyer selling, dev wallet selling, whale net flow (>= $3k) -> research/smart_shadow.jsonl, log "SMART (shadow)", and a dashboard card.
- SHADOW ONLY: it has no effect on entries or exits. It may be promoted only after research/smart_eval.py shows n>=40 with an edge of >2pp on 1h forward return versus no flag (or a >3pp drop avoided for exit flags), validated out of sample.
- Not implemented: exchange-wallet inflow/outflow tracking (needs a labeled CEX-address list and an RPC/indexer).

## 2026-10-30 13:17 — BTC deposit (owner: "he añadido 50 eu en bitcoin")
- API check (accounts + portfolio breakdown, Default portfolio only): NO BTC visible yet (total ~9.59 EUR: OCEAN, SOL, GROVE dust). Probably still pending or confirming on-chain.
- Added automatic deposit handling: any new non-dust coin is adopted with per-coin levels from its own 6h data (no fixed caps). Its USD value is logged as a deposit, raises day_start, is tracked in state.deposits / net_deposits, and is added to the dashboard P&L baseline (so it is not counted as profit).
- BTC policy: BTC is below its 50d SMA (swing regime OFF), so there are no swing entries and fund() will not sell BTC. It is HELD as an adopted position with per-coin exits. Converting it to USDC now would only pay 0.5% taker with nothing to buy.

## 2026-10-30 — INSIDER engine v2 (owner priority, public on-chain data only)
- insider.py:
  - Mines the first 100 swaps of Solana launches via the public RPC (getSignaturesForAddress on the mint + getTransaction).
  - Labels: winner = peak mcap >= $300k (10x+ from a pump launch), loser = peak < $30k.
  - Universe: our candidates log + GeckoTerminal trending/top/new + DexScreener.
  - Wallet scoring: Bayes hit rate on winners vs losers, entry earliness, consistency (distinct days), plus GeckoTerminal realized PnL/win rate.
  - Excluded: bots/MEV/snipers (slot 0-1 buys, presence in >50% of launches, sell-churn), dev/creator wallets, and funding clusters of more than 5 wallets (same funder = farm).
  - Tiers: elite / good / watch.
- Live: a daemon under the supervisor polls elite+good wallets' swaps about every 60 s. Convergence = tier-weighted distinct wallets (3/2/1) buying the same mint within 30 min; an alert fires at >=2 elite or score >=5. The 1h forward outcome is recorded.
- Cerebro: candidates carry rec.insider {conv, elite, sells}; brain.signals adds insider_conv / insider_elite / insider_sell, which the Brain learns like its other signals.
- Exit intel (held tokens): dev selling, early-buyer exit, whale dump, smart-wallet sells. LP pull and dev dump already exit via memebot.
- Promotion (paper only; Solana is paper):
  - convergence: walk-forward (research/insider_bt.py) n>=40 with conv>=3 and win rate >=1.5x base, OR live n>=40 with mean 1h >+2% and hit >50%.
  - exit: n>=40 and an avoided drop >3pp.
  - Until then SHADOW: logged/shown only. A promoted convergence adds up to +12 score; a promoted exit sells.
- First walk-forward (53 launches, 33 test): base win 76% (biased sample); conv>=1 7/7 winners; conv=0 69%. n is far below 40, so NOT promoted. The backtest re-runs automatically every 30 min as mining continues.
- Not done: CEX-deposit inflow tracking (no reliable free labelled list or indexer without keys). Helius/Birdeye/Solscan need API keys. 10x winners with >20k txs cannot be mined from the free RPC (skipped).

## 2026-10-30 14:02 (Madrid) — revisión horaria (director financiero)
- Salud: Binance/Solana paper, Coinbase live, panel e insider daemon vivos, logs frescos. Reinicios 13:33–13:58 = despliegues (exit 0/143), no caídas. Solana e insider sin tracebacks.
- Coinbase LIVE: equity 9.51 USD (día −5.35%). KILL SWITCH 13:52 (dd −5.64%) y max_trade_loss OCEAN 13:57 intentaron vender OCEAN y SOL: Coinbase rechazó con 400 "account is not available" (posiciones conservadas). trades_coinbase_live.csv vacío = ninguna orden live ha llegado a ejecutarse. Hipótesis a verificar: permisos de la API key/cuenta o portafolio, no código. Depósito BTC aún no visible.
- Equity: Binance 998.80 (bear, sin señales), Solana 887.04 (todo cash; 0 candidatos pasan filtros en los escaneos).
- Cambios: ninguno (sin operaciones nuevas en paper; n=15 < 30).
- Próxima vez: confirmar si las ventas live de Coinbase pueden ejecutarse (permisos de la key "trade"); vigilar primeras entradas Solana con scam.py.

## 2026-10-30 14:02 — Coinbase "account is not available" (root cause + fix)
- Cause: this is an EU account with no USD account (only EUR fiat + USDC). Adopted positions stored tsym=X-USD, so SELLs went to OCEAN-USD/SOL-USD, whose quote account does not exist -> 400 INVALID_ARGUMENT "account is not available". preview_order does not check the quote account, which is why previews passed. The payload itself is fine: base_size rounded to the increment (44.8), client_order_id is a uuid, and the key's portfolio = Default (the one holding the coins). Products are online with no restrictions.
- Fix: tsym() routes X-USD -> X-USDC whenever no USD account exists. close() recomputes the route every time. Previews of OCEAN-USDC / SOL-USDC SELL: no errors. No order was placed manually.

## 2026-10-30 14:20 — Solana memecoins: REAL mode with a dedicated hot wallet (owner: "Si")
- Wallet: solana_wallet.json (chmod 600, in .gitignore, never printed). Public address: 9c6MmGPnVCS418G1Z22jcYS3GyhRESNiDmL2EpuRWiwm. The bot only makes Jupiter swaps from/to SOL; there is no transfer code.
- live_sol.py: Jupiter lite-api quote -> /swap -> local sign (solders) -> simulateTransaction (sigVerify) -> send through a public RPC (mainnet-beta, publicnode fallback) -> confirm (75 s, rebroadcast).
  - Per-coin slippage = 100bps + 2e4*size/liquidity + 2x quoted impact (max 800bps; urgent exits 1500bps, raised on retries).
  - Sell-ability check before every buy: a token->SOL quote for the bought amount must exist and the round trip must be <= max_roundtrip_loss_pct.
- Auto switch: config stays mode=paper. memebot reads the wallet every 60 s. With >= live_min_sol (0.05) and no KILL_solana file it switches to REAL (state_solana_live.json / trades_solana_live.csv); paper state is saved separately.
  - Reconcile on restart and after every trade: cash = SOL minus a 0.02 SOL fee reserve; positions follow on-chain token balances (missing ones dropped, unknown ones >= $1 adopted).
- KILL_solana file: closes REAL positions and blocks buys. All scam.py / RugCheck / honeypot / news filters unchanged.
- Adaptive risk (adapt()): per trade, risk = base 0.5% x score factor (0.6–1.4) x regime (news risk-off 0.6, BTC bear 0.8, playbook mult) x 1/ATR vol_mult x insider (elite 1.4, conv 1.25, insider/dev/whale selling 0.5, smart buy +10%), clamped to 0.2–1%.
  - Stop = ATR stop scaled by insider and regime (4%–22.5%). Per-trade loss limit = 1.6x risk (0.4–3%), stored per position (mtl).
  - Only hard caps: 5% daily equity kill switch + max_gap_loss_pct 3% per position.
- Tiny-account caveat: with ~$50, the 3% position cap means trades of about $1.5. live_min_trade_usd=1. Network fees plus token-account rent (~0.002 SOL per new token) are large relative to that size.
- Dashboard: red "Solana REAL" card (address, Solscan link, SOL balance, REAL equity, positions, trades with tx links).
- Verified: compiles, a SOL->USDC Jupiter quote works, build+sign+simulate works (simulation correctly fails with an empty wallet, nothing sent), the dashboard API returns the wallet.
- Backups: *.bak_solive. Binance/Coinbase untouched.

## 2026-10-30 14:55 — Insider v3 real-time + canvas live fix + Coinbase accounting (owner: "sigue mejorando insiders ... tiempo real")
- Backups: *.bak_ins2.
- insider.py live() v3 (public on-chain + free APIs only):
  - Elite wallets polled every cycle, good wallets every 2nd cycle. One cycle takes ~85 s on the free public RPC (111 wallets + getTransaction parsing). Getting it down to seconds needs a websocket or a paid RPC.
  - Continuous re-rank: each smart buy is checked at 1h forward -> insider_wallet_live.json (n, hits); rank = mined score + 0.6*(live hit-0.5)*log1p(n).
  - Events feed:
    - smart_buy / smart_sell, with detection lag;
    - cluster_buy (>=2 smart wallets within 30 min);
    - GeckoTerminal new_pools every 60 s: new_pool (liq >= $5k), liq_add (>1.5x), liq_pull (<0.5x);
    - deep flow for the 8 hottest tokens, one every 20 s (DexScreener + GeckoTerminal trades via smart_money.signals): whale_accum / whale_dist (|net| >= $10k), dev_sell, early-buyer exits.
  - Per-token score (-15..15) = cluster score + 2*elite - 1.5*smart sells + whale net/5k (±4) - 4 if dev selling - 3 if early buyers exit.
  - Validation: every |score|>=3 snapshot (once per 30 min per token) is scored on its 1h forward return (research/insider_tok_signals.jsonl), never fitted on. tok_weight: 0 until n>=20 AND mean directional edge > 0; then weight = clip((hit-0.5)/0.2) * min(1, n/60).
- memebot: score += weight * clip(token score, -15, +12), plus the old promoted-convergence path. The adjustment only touches the score; every scam/RugCheck/honeypot/news filter still vetoes (f list unchanged). Adaptive sizing (adapt) already uses insider conv/elite/sells.
- Dashboard: "Insider en tiempo real" card (cycle time, OOS weight, n/hit, event counts, feed, per-token score table).
- Ops: the running supervisor (started ~08:20) predates its insider loop -> added insider_loop.sh (restart loop). Do NOT `pkill -f "insider.py daemon"` from inside a bash -c loop (it kills the loop itself).
- update_canvas.py: mode now comes from the status file (solana = live). Solana live P&L is measured against state_solana_live.json day_start, and its trades come from trades_solana_live.csv (paper trades no longer shown as real). Coinbase baseline = starting_equity + net_deposits.
- Coinbase finding (v2 transactions API, read-only):
  - 14:27 Àngel converted 4.97 USDC -> 0.050 SOL (valued $4.30, i.e. ~$0.67 convert spread);
  - 14:28 converted the BTC deposit -> 0.522 SOL ($44.80);
  - 14:30 sent 0.5824 SOL ($50.01) to the bot's Solana wallet.
  - Net external outflow -$5.21 that the bot had booked as a trading loss. That was an accounting error.
  - Fix:
    - booked a -5.21 withdrawal in deposits; day_start 10.05 -> 4.84; SOL position qty set to the real 0.03595;
    - live_cb.sync() now auto-detects external outflows when no order has run for 3 min (cash drop > $0.05 or managed coin qty drop) and lowers the baseline;
    - partial external qty drops no longer drop the position.
  - Real remaining loss today about -$1.4: OCEAN sale -$0.66 incl. fee, the ~$0.67 manual convert spread, and SOL drift. halted=True comes from the genuine 13:52 kill switch (-5.64% before the transfers). It resets at the day roll. Risk settings were not changed.

## 2026-10-30 15:05 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live, Solana REAL, panel, insider daemon y minado vivos; logs frescos. Reinicios 14:42–14:50 = despliegues, no caídas. Sin errores nuevos desde 13:57 (Coinbase) ni tracebacks en Solana.
- Equity: Binance 998.80 (bear, sin señales). Coinbase live 3.42 USD (solo SOL 0.036; −29% del día es sobre base 4.84 tras retirada externa, pérdida real ≈ −$1.4; halted hasta cambio de día). Solana REAL 53.33 USD en cash (0.582 SOL), 0 trades reales.
- Embudo Solana desde 12:00: 20.271 candidatos, 24 pasaron (último 14:14, antes del paso a REAL); desde las 14:31, 0 pasan. Rechazos: liq 77%, top10, rugcheck_danger, no_momentum, mint_authority.
- Cambios: ninguno (sin muestra; filtros anti-scam no se relajan sin evidencia).
- Próxima vez: si sigue 0 entradas REAL varias horas, medir would-have P&L de los rechazados por no_momentum/score para ver si el umbral es demasiado estricto.

## 2026-10-30 15:58 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live, Solana REAL, panel, insider daemon (loop) vivos; logs frescos. Sin reinicios ni errores nuevos desde 13:57.
- Operación real: Coinbase vendió SOL 0.03595 a 15:35 (max_trade_loss, −$0.12) ya enrutada a SOL-USDC sin error -> fix de ruta confirmado. Coinbase queda 100% cash 3.36 USD, halted hasta cambio de día.
- Equity: Binance 998.80 (bear, BTC cae a ~77k por hack Binance). Solana REAL 53.17 USD cash, 0 trades.
- Embudo Solana desde 14:31: 6.775 evaluaciones / 1.178 tokens, 0 pasan. Rechazos: liq 5128, top10 1047, rugcheck_danger 573, no_momentum 362, mint_authority 345. El cluster buy más fuerte (SAFU, 7 wallets) se rechazó por liquidez ($18k) — correcto.
- Cambios: ninguno (sin muestra; anti-scam no se relaja).
- Próxima vez: si a las ~18:00 sigue 0 entradas REAL, medir would-have P&L de rechazados por no_momentum/liq marginal.

## 2026-10-30 16:08 — Insider TOP priority (owner order) + manipulated-pump play
- Backups: insider.py/memebot.py.bak_prio, memebot.py/config.json.bak_pump.
- Owner order ("Insiders es prioridad ... empieza a usarlo"): the insider token score is active NOW, without waiting for validation.
  - tok_weight: fixed starting weight BASE_W=0.7.
  - Validation keeps running: with n>=20, a clearly negative edge (mean < -1% AND hit < 45%) cuts the weight to 0.2; a mildly negative one (edge < 0, hit < 50%) cuts it to 0.45. Logged as "[insider] WEIGHT ...".
- memebot: score += weight*3*clip(token score, ±15) (±31 of 100 points at 0.7).
  - Elite group buy (>=3 elite wallets in 30 min, no smart sells, weight>=0.45) = entry trigger. It applies only if every filter passed (scam, honeypot, RugCheck, min liquidity, momentum, news).
  - weight*token score <= -3 blocks the entry.
  - Insider tokens (score>=5 or elite>=3) are injected into the scan universe as src="insider".
- Mining: daemon now mines 12+12 launches every 20 min (was 40+40 every 6 h) and rebuilds tiers every 20 min. It runs under insider_loop.sh.
- Manipulated-pump play (config pump_*):
  - Candidates: tokens with a coordination setup (RugCheck insiders, top10 above max_top10 but <=45%, insider accumulation, >=2 whale buys, >=3 bot wallets) whose only failures are soft (top10 / score).
  - Hard requirements: no mint/freeze authority; LP locked >= min_lp_locked_pct; transfer fee 0; honeypot round trip <=4%; m5>0; no insider sells. scam.check still vetoes at buy time; min liquidity is unchanged.
  - Size: 0.3x the normal size (inside existing caps).
  - Exits: stop 6%, trail 5% from +4%, partial TP +15%, time stop 45 min, exit on the first insider sell / dev_selling / early_exit / whale_dump, exit on the ai_pump exhaustion signal.
  - Logged separately in trades_solana_pump.csv; P&L shown in status.pump_play.
- 5% daily stop, position caps and min liquidity unchanged.
- First result: 5 pump-play candidates (HI, HALVE, Dacity, USOE, GATO) passed every filter, but all were skipped because size was 0.0–0.2 USD < live_min_trade_usd 1. With ~$53 equity, risk-off halving and depth caps make the sizes too small. Not changed (caps untouched).

## 2026-10-30 16:15 — Solana LIVE: per-position cap 3%→10%, $1 floor (approved by Àngel)
- config solana: max_gap_loss_pct 0.03→0.10, max_position_pct 0.08→0.10. Backups *.bak_floor.
- memebot: for live, a size below live_min_trade_usd ($1) is raised to $1 when $1 ≤ 10% of equity, ≤ cash*0.98, ≤ depth cap (no floor when there's no route) and $1×max_stop ≤ the per-trade risk budget. Pump-play keeps 0.3x, floored at $1. The 5% daily stop and filters are unchanged.

## 2026-10-30 16:28 — Solana LIVE: dynamic profit protection (guard_loop)
- New thread marks live positions every 12 s (executable Jupiter quote). Net P&L includes the buy and estimated sell fees.
- Per-coin threshold = clip(1.5×ATR, 2%, 4%). If net ≥ threshold and there's a reversal (ai_pump exhaustion, insider/dev sell, smart flags, 5m volume < 40% of the 1h average, lower-high on the 12 s series) → full take. If it's volatile (ATR ≥ 2%, realized vol rising 1.5×, or rv ≥ 1%) → lock a floor at max(0.8%, net − max(thr, 2·rv)) and sell if net falls back to it. Spike (+6% in 1 min with net ≥ threshold) → 33% partial and a 0.8% lock.
- sell() is serialized with an RLock. Existing stops, caps, 5% daily stop and filters are unchanged. Backups *.bak_guard.

## 2026-10-30 16:33 — Solana LIVE: dynamic priority fee, real fees, $3-5 size, spike_exit (approved by Àngel)
- Measured fees of the earlier real txs: 5,836 / 305,000 / 31,584 lamports (the bot was booking a fixed ~$0.048 per side). live_sol.swap now uses a dynamic maxLamports = p75 of getRecentPrioritizationFees (Jupiter program) × 300k CU, clipped to 5k–100k lamports, level "medium". Real tx fees are now booked from getTransaction meta.fee. priority_fee_sol (estimate) 0.0005→0.00005.
- Live size: target $3 + $2×clip((score−min_score)/20 + insider tok/15×w, 0..1), bounded by the 10% cap, cash×0.98, depth cap and the risk budget (equity×mtl / max_stop). Pump-play also uses the target (min $3) instead of 0.3x, so fees don't eat it. The 5% daily stop and filters are unchanged.
- guard: spike_exit = jump ≥8% within 2 checks (~24 s) + 5m volume burst (≥2× the 1h average or ≥3% of liquidity) and net>0 → full sale.
- Backups *.bak_fee.
- Bug fix 16:35: USELESS (real buy 16:17) had been dropped from state by a reconcile with a partial RPC list → it went unmanaged. Now a drop happens only after 3 consecutive misses, plus a re-adopt of on-chain orphans every 5 min (≥$0.5, recovering entry/symbol from the REAL BUY in the CSV). USELESS re-adopted.

## 2026-10-30 16:58 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live, Solana REAL, panel, insider loop/daemon vivos; logs frescos (Solana 16:58). Sin errores/tracebacks nuevos (los de Binance son del 29/10, Coinbase sin nuevos desde 13:57). Único aviso: compra REAL LMAO! fallida 16:14 (Jupiter 0x1771 = slippage), sin coste.
- Equity: Binance 998.80 (bear). Coinbase live 3.36 USD cash, halted hasta cambio de día. Solana REAL 52.44 USD (cash 49.46 + 3 posiciones ~1 USD c/u: TROLL, CATE [pump-play], USELESS re-adoptada), día −2.7% sobre 53.89, casi todo deriva de SOL + fees, no pérdidas cerradas.
- Trades cerrados REAL Solana: 0 → sin muestra.
- Cambios: ninguno (cambios de 16:08–16:35 recién desplegados; dejar que acumulen muestra).
- Próxima vez: revisar primeras salidas reales (guard_loop/spike_exit/pump-play), fees reales vs P&L en posiciones de 1 USD, y tasa de fallos de swap por slippage.

## 2026-10-30 17:35 — Solana LIVE: more volume (Àngel: "more transaction volume")
- poll 15→8 s; max_positions 5→8 (10% cap per position unchanged); reentry_cooldown 6h→0.25h; max_hold 12h→3h; pump_max_hold 45→25 min.
- Universe: + Jupiter toptrending 5m/1h, toporganicscore 5m, toptraded 5m; + GeckoTerminal trending 6h (alternating); insider top 15→30.
- min_score NOT lowered: shadow data (candidates rejected only for score, return 30–60 min later) shows score 25–40 at −7% to −29% mean, 40–45 n=2 +0.6% → no evidence. Vetoes, 5% daily stop and caps unchanged. Backups *.bak_vol.

## 2026-10-30 18:02 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live, Solana REAL vivos; sin errores nuevos (Coinbase: últimos de 13:57). Aviso: tras ampliar universo (17:35) el ciclo de escaneo Solana tarda mucho (status_solana.json sin actualizar 17:43→18:01); guard_loop sí sigue marcando cada 12 s.
- Equity: Binance 998.80 (bear, sin operar). Coinbase live 3.36 USD, halted. Solana REAL 50.71 USD (cash 29.92, 7 abiertas), vs 53.89 al inicio del día.
- Cerrados REAL Solana: 10, neto ≈ −0.74 USD (peores: USELESS −0.37 sell_pressure, DESSA −0.28 max_trade_loss; mejor DOPE +0.05 protect_lock). Pump-play: 6 cerrados, −0.05.
- Cambios: ninguno (muestra <30).
- Próxima vez: duración del ciclo de escaneo (si >5 min, recortar fuentes), deriva hacia el stop diario del 5%, peso de fees en posiciones de 1–3 USD.

## 2026-10-30 18:20 — Solana: scan speed + daily stop persistence fix
- Profile (py-spy): RugCheck sequential + sleep 0.4 s/mint ≈55%, Jupiter quotes (inline marks/honeypot) ≈25%, plus endless sell retries on ghost positions (429 + sim 6024).
- Scan: cheap prefilter (liq ≥ min and vol h1 ≥ $2k from DexScreener), top 60 by volume (+ open positions/insider first), RugCheck in parallel (4 threads) with a 10-min cache; inline manage during the scan uses marks from the 12 s guard (no extra quotes). Cycle 18 min → ~45–60 s. Vetoes unchanged.
- BUG: the daily KILL SWITCH (−5%, 18:02) closed everything, but state was only saved at the end of the 18-min cycle; the 18:06 restart reloaded old positions and halted=False → it bought Fartcoin at 18:10 in violation of the daily stop. Fix: save() after every sell and on halt; reconcile every live step; at startup, if the CSV has kill_switch today → halted restored and positions closed (Fartcoin closed 18:14). Halted until the day change (00:00 Madrid).
- Backups memebot.py.bak_speed.

## 2026-10-30 18:33 — Solana: halt lifted by Àngel (18:02 stop = false trigger from bad quotes)
- halt_override.json (day 2026-10-30, applied): halted=False, day_start = current real equity; the startup re-halt (CSV kill_switch) is skipped today. The 18:02 stop is marked as superseded by the user.
- The 5% daily stop stays active from the new baseline, now using robust_equity: per-position median of (guard mark, DexScreener priceUsd, Jupiter price v3), ignoring 0/failed quotes (no data → no evaluation), and it requires 2 consecutive checks in breach. Backups *.bak_halt.

## 2026-10-30 19:00 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live, Solana REAL (reiniciado 18:33), panel, insider loop/daemon vivos; logs frescos. Sin tracebacks. Avisos: varios fallos de compra por Jupiter 429 (rate limit) 18:36–18:52; venta TROLL 18:14 con sim 6024/0x1788 (reintentada).
- Equity: Binance 998.80 (bear). Coinbase live 3.36 USD, halted. Solana REAL 49.97 USD, todo en cash, 0 abiertas (vs 53.89 inicio de día, −7.3%).
- Cerrados REAL Solana hoy: 21, 4 ganadoras, neto −1.18 USD (ganado +0.15, perdido −1.33; fees ~0.17). Por motivo: kill_switch 7 −0.40, sell_pressure −0.37, max_trade_loss −0.28, pump early_exit 3 −0.16, pump time 5 −0.04, protect_lock 2 +0.07.
- Cambios: ninguno (muestra <30 por bucket).
- Próxima vez: frecuencia de 429 de Jupiter tras el aumento de volumen (si sigue, bajar ritmo de quotes/añadir backoff), pump-play early_exit que vende en segundos con pérdida, llegar a 30 cierres.

## 2026-10-30 19:20 — Solana: Jupiter rate limiter + pump-play grace period
- jupr.py: central token bucket for ALL Jupiter calls (0.5 req/s, burst 3), priority exits(0) > buys(1) > pricing(2) (lower priority leaves a reserve), 429 → backoff with jitter + shared cooldown, 5 s cache for pricing quotes, counters in jup_stats.json. Guard prices via DexScreener (1 batched call) minus half the round-trip; Jupiter only as fallback; marks() reuses fresh guard marks.
- Pump-play: grace period of 75 s (pump_grace_s): only hard stop/max_trade_loss, liquidity_pull/rugged/dev_dump and spike_exit. Reversal/volume-fade and pump_exit signals need 2 consecutive confirmations. Basis: exits <30 s (HYPERCHAN 11 s −0.056, 20 s −0.010; USELESS 24 s −0.0005) were all noise; the profitable ones came after ≥3 min (DOPE 571 s +0.048, HYPERCHAN 178 s +0.023).
- Bug 19:01: the startup re-halt ignored halt_override (wrong order) and closed RIV; fixed (override checked first) + one-shot unhalt_once (day_start 50.17 kept).
- Backups *.bak_rl.

## 2026-10-30 20:05 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live, Solana REAL, panel, insider vivos. Avisos: ciclo de escaneo Solana volvió a alargarse (equity log 19:33→19:48→20:02, ~14 min; objetivo ~1 min); 40 respuestas 429 de Jupiter de 620 llamadas desde las 19:20.
- BUG: venta USELESS 19:47 marcada "not confirmed in 75s" pero SÍ se ejecutó on-chain (finalized, +0.0312 SOL); los reintentos fallaron (sim 6024, sin tokens) y reconcile la borró sin registrar SELL → equity 19:48 inflada (52.51). Venta registrada a mano en CSV (−0.074 USD, reason reconciled_late_landing). Fix live_sol.swap: antes de dar por fallida, re-chequeo getSignatureStatuses con searchTransactionHistory hasta ~30 s. Backup live_sol.py.bak_conf. Solana reiniciado 20:03 (posiciones Fartcoin, PUMPCADE conservadas, halted=False, day_start 50.17).
- Equity: Binance 998.80 (bear). Coinbase live 3.36 USD, halted. Solana REAL 49.41 USD (cash 43.42, 2 abiertas), −1.5% sobre day_start 50.17 (−8.3% vs 53.89 de inicio de día real).
- Cerrados REAL Solana hoy: 28, 5 ganadoras, neto ≈ −0.98 USD. Pump-play pierde poco pero no gana (pump_exit:time 7 −0.12, early_exit 5 −0.21); la única ganancia relevante es protect_take JOB +0.45.
- Cambios de parámetros: ninguno (muestra <30 por bucket).
- Próxima vez: verificar duración de ciclo tras reinicio (si sigue >5 min, perfilar; sospecha: límite Jupiter 0.5 req/s + quotes de compra), y que no haya más ventas "no confirmadas" fantasma.

## 2026-10-30 20:25 — Solana: scan cycle 14 min → ~1 min (2nd time)
- py-spy: ~70% of the time the MainThread waited in jupr._take (pricing priority needed a full bucket with RESERVE 2/3) because of per-candidate Jupiter quotes: honeypot (2), depth_curve (3); plus whales() via GeckoTerminal at 2.1 s per candidate; scam.py was calling Jupiter outside the limiter (extra 429s).
- Fix: TTL caches per mint: honeypot 10 min, depth_curve 10 min, whales 5 min. RESERVE pricing 2→1, buys 1→0.5 (exits still take priority). scam.py's Jupiter calls go through jupr. The final sellable() check in buy_live is still done live before every buy (vetoes unchanged).
- Incident: the 20:18 restart killed the process mid-confirmation of a Fartcoin sell (tx 3JKANCon…, landed OK); the bot then dropped the position without recording it. Row recorded manually in the CSV. Lesson: restart only with no sell in progress (use STOP_solana / wait).
- Backups *.bak_cyc.

## 2026-10-30 21:06 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live, Solana REAL, panel, insider loop/daemon vivos; sin tracebacks nuevos (los de Binance son del 29/10). Ciclo de escaneo Solana ~1–3 min tras el fix de 20:25 (salvo huecos de ~9–11 min 20:42→20:53 y 20:56→21:05); Jupiter 15×429 de 500 llamadas (3%, antes 6.5%). Sin ventas "no confirmadas" nuevas.
- Equity: Binance 998.80 (bear). Coinbase live 3.36 USD, halted. Solana REAL 49.78 USD (cash 37.76, 4 abiertas: CHILLHOUSE, CATE, Fartcoin, USELESS), −0.8% sobre day_start 50.17.
- Cerrados REAL Solana hoy: 34, 8 ganadoras, neto −0.95 USD. Desde 20:05: 6 cierres, +0.03 USD. pump_exit:time 11 −0.07; early_exit 6 −0.23 (sigue siendo el peor bucket de pump-play).
- Cambios: ninguno (muestra <30 por bucket).
- Próxima vez: huecos de 9–11 min entre escaneos (perfilar si se repiten), early_exit de pump-play, llegar a 30 cierres en pump_exit para decidir.

## 2026-10-30 22:00 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live, Solana REAL, panel, insider loop/daemon vivos; sin tracebacks nuevos en Solana. Avisos: status_solana.json/equity_solana.csv sin actualizar 21:42→22:00 (hueco de escaneo ~17 min, aunque guard y compras siguen); Jupiter 93×429 de 1060 llamadas (8.8%, sube desde 3%); "levels ...: 'NoneType' object is not subscriptable" en pre-levels/levels (cálculo de niveles falla en algunos tokens, el trade sigue con stop 6%).
- Equity: Binance 998.80 (bear). Coinbase live 3.36 USD, halted. Solana REAL ~49.1 USD (último CSV), abiertas USELESS, Cupsey, POPCAT, CHILLHOUSE (pump-play).
- Cerrados REAL Solana hoy: 44, 11 ganadoras, neto −1.29 USD. Desde 21:06: 10 cierres, −0.34 USD. Pump-play: pump_exit:time 16 −0.21, early_exit 9 −0.36 (peor bucket), total pump ~27 cierres.
- Cambios: ninguno (muestra <30 por bucket).
- Próxima vez: al llegar a 30 cierres pump-play, decidir sobre early_exit (endurecer confirmación o quitarlo); perfilar huecos de escaneo; arreglar bug de levels NoneType; vigilar 429.

## 2026-10-30 22:40 Madrid: 22:00 review
- early_exit (pump-play): 4 of 6 analysed exits recovered afterwards (HYPERCHAN +4%/+16.5%, JOB +0.4%/+1.6%). Now early_exit alone needs net>=0; dev_selling/whale_dump still exit immediately. 6% stop and rug exits unchanged.
- Scan gap: caused by (a) slow sells holding the lock (confirm 75s, RPC 20s, retries), which blocked guard/main, and (b) Jupiter lite-api 429s (~40% of calls). Fix: sell lock timeout 5s (defer), late-landing detection via balance, confirm 45s, RPC timeout 10s, honeypot quotes skipped when m5<=0 (fail-closed: candidate rejected, filters not bypassed), TTL caches.
- Levels bug: GeckoTerminal ohlcv failure → None → 6% fallback. Now bars are cached 5 min and there is a DexScreener-based levels_fallback (atr proxy).

## 2026-10-30 22:42 Madrid: Jupiter call reduction
- Honeypot TTL 30 min. _ttl (honeypot/whales/depth) + _bars caches are persisted to state/sol_caches.pkl after each scan and restored at start.
- Sellability (honeypot) quote now only for final buy candidates (no hard fail, score>=thr / elite / pump setup with m5>0 / brain active, free slot, not halted). Otherwise "no_sellability_check" = fail-closed, so no filter is bypassed. robust_equity no longer calls Jupiter price (DexScreener + mark).
- Levels: fallback also when bars <5, sup>=px*0.999 or atr=0.
- jupr: optional JUP_API_KEY env → api.jup.ag + x-api-key; without it, lite-api as before.

## 2026-10-30 23:02 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live, Solana REAL, panel vivos; logs frescos (23:00); 0 tracebacks Solana. Reinicios Solana 22:29 y 22:42 (SIGTERM por los fixes de la revisión anterior); tras el de 22:42 reconcile adoptó on-chain Bonk (mint DezX…, aparece como "DezX" en abiertas) y 9Pq7…pump; sin pérdidas de posición. Nota: la venta "DezX" 22:37 es Bonk (comprado 22:18), solo etiqueta de símbolo.
- Equity: Binance 998.80 (bear). Coinbase live 3.36 USD, halted. Solana REAL 48.60 USD (cash 24.80, 8 abiertas: CHILLHOUSE, Fartcoin, USELESS, CATE, POPCAT, $WIF, Bonk, JOB), −3.1% sobre day_start 50.17.
- Cerrados REAL Solana hoy: 49, 13 ganadoras, neto −1.47 USD, PF 0.35. Desde 22:00: 5 cierres, −0.19 USD.
- Pump-play llegó a 30 cierres: PF 0.32 (10 ganadoras, +0.26 / −0.82). Por la regla PF<0.8 tocaría desactivarlo, pero Àngel pidió explícitamente pump-play y el cambio de early_exit (22:40) aún no tiene muestra → no se desactiva; se consulta a Àngel. Pérdidas por trade pequeñas (~−0.03 USD, sobre todo fees/impacto en posiciones de ~3 USD).
- Cambios: ninguno.
- Próxima vez: medir pump-play después de 22:40 (nueva regla early_exit); si sigue PF<0.8 con ~15 cierres nuevos, proponer reducir tamaño o pausarlo; corregir etiqueta de símbolo en posiciones adoptadas.

## 2026-10-30 23:07 — Àngel: regla pump-play
Àngel decide: si el pump-play no mejora en los próximos ~15 cierres (desde 30 cierres, PF 0,32 a las 23:00), PAUSAR el pump-play (no reducir tamaño). Revisión horaria debe evaluarlo: si tras 45 cierres totales el PF de los cierres posteriores a 22:40 sigue <1, desactivar pump-play en memebot.py y avisar.

## 2026-10-31 00:06 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live, Solana REAL, panel, insider loop/daemon vivos; logs frescos (00:04); 0 tracebacks Solana; sin reinicios desde 22:42.
- Equity: Binance 998.80 (bear). Coinbase live 3.36 USD, halted. Solana REAL 48.19 USD (cash 24.32, 8 abiertas: Fartcoin, USELESS, CATE, POPCAT, Bonk(DezX), MANIFEST, GLITCH, RIV), −3.9% sobre day_start 50.17.
- Cerrados REAL Solana 30/10: 55, 15 ganadoras, neto −1.83 USD, PF 0.36. Desde 23:00: 6 cierres, −0.35 USD.
- Pump-play llegó a 45 cierres: PF total 0.16, neto −1.71 USD. Cierres 31–45: PF ~0.1. Posteriores a 22:40: 3, todos perdedores (GLITCH stop −0.20, JOB time −0.22, dreams whale_dump −0.18).
- DECISIÓN (regla de Àngel 23:07): pump-play PAUSADO → config.json "pump_play": false (backup config.json.bak_pumpoff). Recarga en caliente, sin reinicio. Solo bloquea nuevas entradas pump; las abiertas pump (MANIFEST, GLITCH, RIV) siguen gestionadas con sus salidas pump. Estrategia meme normal sigue activa.
- Próxima vez: confirmar que no hay nuevas compras PUMP-PLAY; medir PF de la estrategia meme normal sin pump-play.

## 2026-10-31 00:28 (Madrid): post-mortem of the 55 REAL Solana closes on 30/10
- Total −1.83 USD. Pump-play 52 closes, −1.88, PF 0.24 (closes 31–52 PF 0.39 <1) → paused per Àngel's rule (config pump_play=false since 00:05; MANIFEST 00:07 got in before the hot reload). Normal score: 3 closes, +0.06 (PF 1.14). No elite entries.
- 30 min after the exit (GeckoTerminal, partial sample): moves of ±1–2% → the exits were not the main problem. The losses come from entries with ATR ~0.4% that cannot cover the round-trip/impact cost on positions of ~3 USD. Pump entries with ATR ≥0.5%: 22 closes, −1.45.
- Churn: re-entries into the same coin (CATE 7, JOB 7, USELESS 6, HYPERCHAN 5) = 31 closes, −1.04. Walk-forward: a 2 h cooldown after a loss would have blocked 27 closes worth −0.84.
- Changes: (1) 2 h cooldown after a losing close (loss_cooldown_hours); (2) max_roundtrip_loss_pct 6→3 (fail-closed, stricter). Unchanged: daily stop 5%, all vetoes, stops.
- kill_switch 7 closes −0.40, price +2.6% after → false trigger, already hardened (median + 2 checks) at 20:25.

## 2026-10-31 00:56 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live, Solana REAL vivos; logs frescos (00:55); 0 tracebacks Solana; último reinicio 00:28 (cambios del post-mortem). Pump-play pausado confirmado: ninguna compra PUMP-PLAY tras MANIFEST 00:07.
- Equity: Binance 998.80 (bear). Coinbase live 3.36, halted. Solana REAL 48.60 USD (cash 39.46, abiertas Fartcoin, USELESS, POPCAT).
- Cierres desde 00:06: 5 (GLITCH +0.07, RIV +0.01, CATE −0.04, MANIFEST −0.03, Bonk/DezX +0.01) ≈ +0.01 USD. Último escaneo: 0 candidatos pasan todos los filtros.
- Cambios: ninguno (cooldown 2h y roundtrip 3% recién aplicados, sin muestra).
- Próxima vez: medir estrategia meme normal sin pump-play; verificar que el cooldown bloquea reentradas tras pérdida.

## 2026-10-31 00:57 (Madrid): new strategy research (Àngel: "crea algo nuevo")
- Mean-reversion VWAP band, WIF/BONK/POPCAT, 5m bars from GeckoTerminal (~7 days, 1000–2000 bars per coin), cost 0.6% round trip. Grid of 108 combinations, walk-forward (first half to choose, second half to test): best in-sample PF 0.46 → out-of-sample PF 0.6 (17 trades, −0.66% per trade). REJECTED.
- Pump.fun graduations: no fetchable history of graduations + first dip → not testable today.
- Copy-trade of elite insiders (alert elite>=3): our detection lag is 70–130 s, not seconds; no historical price data to replay. Chosen as the only candidate with no negative evidence → PAPER: copytrade_paper.py (state/copytrade_paper.json, trades_solana_copy_paper.csv, $2 per trade, 0.6% cost, exit on elite sell / +15% / −8% / 30 min, liq>=50k, max 5). Dashboard: /api/copytrade.
- Live ONLY if >=20 paper closes with PF>1.3, at $1–2 with the normal vetoes (scam/honeypot) and the same daily stop. Nothing live now.

## 2026-10-31 02:04 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL, panel, insider, copytrade paper vivos. Logs se quedaron ~11 min sin escribir (01:53→02:03) en todos los bots a la vez (pausa de la máquina), se reanudaron solos; sin reinicio necesario. 0 tracebacks Solana. Proceso Solana arrancado 01:07.
- Equity: Binance 998.80 (bear). Coinbase live 3.36, halted. Solana REAL 48.88 USD, todo en cash, 0 abiertas.
- Cierres REAL desde 00:56: 3 (POPCAT +0.08, Fartcoin +0.09, USELESS +0.01) = +0.18 USD, todos estrategia normal (protect_take/time_exit). Escaneos recientes: 0 candidatos pasan filtros.
- Copytrade PAPER: 3 cierres, WORM +1.32 (tp), XTO −2.00, iCoin −2.00 (ambos a ~cero: rug; el −8% no protege ante colapsos de liquidez). Neto −2.68 sobre $6. Muestra mínima.
- Cambios: ninguno.
- Próxima vez: copytrade necesita filtro anti-rug (scam/honeypot/LP) antes de la entrada paper; vigilar si sigue el patrón de colapsos.

## 2026-10-31 03:03 (Madrid) — revisión horaria (director financiero)
- Salud: todos los procesos vivos (Binance paper, Coinbase live halted, Solana REAL, panel, insider, copytrade paper). Nueva pausa de máquina ~02:52→03:03 en todos los logs, reanudados solos; sin reinicio. 0 tracebacks Solana.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.94 USD, todo cash, 0 abiertas.
- Cierres REAL desde 02:04: 0. Copytrade paper: sin nuevos cierres. Escaneos: candidatos bloqueados por anti-scam (clone_ticker).
- Cambios: ninguno.
- Próxima vez: anti-rug para copytrade paper; medir estrategia normal cuando haya muestra.

## 2026-10-31 03:58 (Madrid) — revisión horaria (director financiero)
- Salud: todos los procesos vivos (Binance paper, Coinbase live halted, Solana REAL, panel :8787, insider, copytrade paper); logs frescos (03:55); 0 tracebacks Solana; sin reinicios.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.90 USD, todo cash, 0 abiertas.
- Cierres REAL desde 03:03: 0. Copytrade paper: sin nuevos cierres. Escaneos: 0 candidatos pasan filtros.
- Cambios: ninguno.
- Próxima vez: anti-rug para copytrade paper; medir estrategia normal cuando haya muestra.

## 2026-10-31 04:58 (Madrid) — revisión horaria (director financiero)
- Salud: todos los procesos vivos (Binance paper, Coinbase live halted, Solana REAL, panel, insider, copytrade paper); logs frescos (04:57); 0 tracebacks Solana; errores Coinbase son antiguos (30-oct); sin reinicios.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.71 USD, todo cash, 0 abiertas (−0.19 vs 03:58 sin cierres: variación del precio de SOL en la reserva de comisiones, SOL=96.30).
- Cierres REAL desde 03:58: 0. Copytrade paper: sin nuevos cierres.
- Cambios: ninguno.
- Próxima vez: anti-rug para copytrade paper; medir estrategia normal cuando haya muestra.

## 2026-10-31 05:58 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL, panel, insider vivos; logs frescos (05:55); 0 tracebacks Solana; sin reinicios de bots.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.60 USD, todo cash, 0 abiertas. Cierres REAL desde 04:58: 0.
- Copytrade PAPER: 3 cierres nuevos: Black cat +0.32 (tp), XTO −0.01 (time), KYC registrado como +5727.71 → ERROR de valoración: el pool original se vació (rug) y el precio cayó al de un pool residual de $19 de liquidez (0.33 USD). Corregido a −2.00 (rug) en CSV y estado. Total paper: 7 cierres, −3.82 USD sobre $14 (3 de 7 son rugs).
- Cambio (solo paper, copytrade_paper.py, backup .bak_rugpx): precio de salida desde el MISMO pool de entrada; si el pool desaparece o su liquidez cae >80% → cierre "rug" a −100%. Reiniciado el proceso paper.
- Próxima vez: copytrade necesita filtro anti-rug en la entrada (scam.py / LP bloqueada); con 3/7 rugs, no apto para real.

## 2026-10-31 07:00 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso desde 03:57), panel, insider, copytrade paper (reiniciado 06:33) vivos; logs frescos (06:59); 0 tracebacks Solana; errores Coinbase/Binance son antiguos (29–30 oct). Sin reinicios.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.44 USD, todo cash, 0 abiertas (−0.16 vs 05:58 sin cierres: SOL 95.76). Cierres REAL desde 05:58: 0 (último cierre real 01:19).
- Copytrade PAPER: 2 cierres nuevos marcados "rug" a −2.00 (万圣节, MONEKO), total 9 cierres, −7.82 USD sobre $18. DUDA de valoración: en ambos el precio de salida era SUPERIOR al de entrada (+10% / +3.5%) y el pool pumpswap sigue existiendo; la regla "liq <20% de la de entrada" saltó porque DexScreener reporta liquidity=0 en esos pools. Puede ser vaciado real o hueco de datos de DexScreener en pumpswap (GeckoTerminal con rate limit 429, no se pudo verificar la reserva).
- Cambios: ninguno (solo paper, sin evidencia suficiente para cambiar la regla).
- Próxima vez: verificar reserva del pool en GeckoTerminal/on-chain antes de marcar rug cuando liquidez=0 pero el precio no cae; copytrade sigue NO apto para real.

## 2026-10-31 07:58 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso 04:22), panel (04:50), insider, copytrade paper (06:57) vivos; logs frescos (07:57-07:58); 0 tracebacks Solana; sin reinicios.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.52 USD, todo cash, 0 abiertas. Cierres REAL desde 07:00: 0 (último 01:19).
- Copytrade PAPER: 3 cierres nuevos: Lamrock −2.00 (rug), LUMI +0.92 (tp), GEMPTY −2.00 (rug, de nuevo precio de salida > entrada → probable hueco de liquidez=0 en DexScreener). Total 12 cierres, −10.90 USD, 4 marcados rug.
- Cambios: ninguno (paper; regla de rug pendiente de verificación on-chain).
- Próxima vez: verificar reservas del pool antes de marcar rug cuando el precio no cae; copytrade NO apto para real.

## 2026-10-31 08:59 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso 04:46), panel (05:15), insider, copytrade paper (07:22) vivos; logs frescos (08:57-08:59); 0 errores Solana; sin reinicios.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.29 USD, todo cash, 0 abiertas (−0.23 vs 07:58 sin cierres: SOL 95.47). Cierres REAL desde 07:58: 0 (último 01:19). Escaneo: 235 pares, 46 con liquidez, 0 pasan filtros.
- Copytrade PAPER: 3 cierres nuevos: GEOM +0.02 (time), Tesla +1.11 (tp), LUMI +0.43 (tp). Total 15 cierres, −9.34 USD, 4 marcados rug.
- Cambios: ninguno.
- Próxima vez: verificar reservas del pool antes de marcar rug; copytrade NO apto para real (necesita >=20 cierres con PF>1.3). Revisar si la estrategia normal lleva demasiadas horas sin entradas.

## 2026-10-31 09:1x — Modo salida "trail" (estrategia TikTok) a dinero real (OK Àngel t61u)
- config solana: exit_mode=trail, size_pct=8, hard_stop_pct=6 (neto de fees sobre coste), trail_pct_tt=12 (desde el máximo). Sin TP fijo ni time_exit.
- Se mantienen todos los vetos, coste máx 3%, bloqueo 2h tras pérdida, stop diario 5%, pump-play pausado.
- Overrides: liquidity_pull/dev_dump/rugged, exit_intel insider; venta en pico de ballena solo si net>0 y precio sobre nivel de trailing.
- Backups: memebot.py.bak_trail, config.json.bak_trail. Revertir: exit_mode=volscale.

## 2026-10-31 09:55 — Filtros de entrada (datos, petición de Àngel)
- Estudio: 620 candidatos (30-oct 08h → 31-oct 06h, liq≥40k), precio al evaluar vs ahora (DexScreener).
- Pasaban vetos duros 92: 29% muertos (<-80%). RugCheck score_norm>20: 57% muertos vs 20%. Holders<5000: 76% muertos vs 2% (≥5000). Rugs típicos: liq 50-170k, mcap 0.3-3M, <5k holders, fake-stocks (Nvidia/Tesla/Apple), XTO/NODF/USOE.
- Cambio: nuevos vetos (solo más estrictos) max_rc_norm=20, min_holders=5000. Backups .bak_filt. Tamaño/riesgo sin cambios.
- Nota: RugCheck API devuelve 400 "unable to generate report" desde ~05h → rugcheck_unavailable bloquea todo (fail-closed, sin tocar).

## 2026-10-31 10:03 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso 09:53, tras cambio de filtros), panel (09:49), insider, copytrade paper (07:22) vivos; logs frescos (10:01); 0 errores Solana; errores Coinbase antiguos (30-oct). Sin reinicios.
- RugCheck vuelve a responder (58-60/60 informes por escaneo desde ~09:41) → ya no bloquea todo; aun así 0 candidatos pasan filtros (vetos nuevos holders≥5000, rc_norm≤20).
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.18 USD, todo cash, 0 abiertas (−0.11 vs 08:59 sin cierres: SOL 95.26). Cierres REAL: 0 (último 01:19).
- Copytrade PAPER: 4 cierres nuevos: HORMUZ −2.00 (rug), HI +0.32 (tp), Eurgdp −2.00 (rug), Pum Coin +0.36 (tp). Ambos "rug" de nuevo con precio salida > entrada (probable hueco liquidez=0 DexScreener). Total 19 cierres, 9 ganadores, −12.66 USD, PF 0.30. XTO abierto (token en lista de rugs típicos del estudio de filtros).
- Cambios: ninguno.
- Próxima vez: comprobar que entradas reales aparecen con los nuevos vetos; verificar reservas on-chain antes de marcar rug en copytrade; copytrade NO apto para real.

## 2026-10-31 10:58 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL, panel, insider, copytrade paper vivos; logs frescos (10:51-10:55); 0 errores Solana nuevos; sin reinicios.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.25 USD, todo cash, 0 abiertas. Cierres REAL desde 10:03: 0 (último 01:19). Escaneos: ~220 pares, solo 2-3 con liquidez suficiente, 0 pasan filtros.
- Copytrade PAPER: 2 cierres nuevos marcados rug (XTO −2.00, Hormcrb −2.00). Total 21 cierres, −16.66 USD aprox.; sigue NO apto para real.
- Cambios: ninguno.
- Próxima vez: si sigue sin entradas reales tras los vetos nuevos (~10h sin cierres), revisar qué veto bloquea más en candidates_solana.jsonl (sin relajar anti-scam sin datos).

## 2026-10-31 11:58 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso 10:51), panel (10:47), insider, copytrade paper vivos; logs frescos (11:54-11:57); 0 tracebacks Solana; sin reinicios.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.34 USD, todo cash, 0 abiertas. Cierres REAL desde 10:58: 0 (último 01:19, ~10.5h).
- Embudo 05:00-11:57: 7175 candidatos evaluados, 0 pasan. Motivo principal: liquidez insuficiente (4745), luego rugcheck_unavailable (1156, ya resuelto ~09:41), top10 (905), mint/freeze authority (~1290). Por escaneo solo 2 pares superan el mínimo de liquidez → el bloqueo es el universo/liquidez, no los vetos nuevos (holders/rc_norm).
- Copytrade PAPER: 2 compras nuevas 狙姬 (11:57); sin cierres nuevos.
- Cambios: ninguno (no se relajan liquidez ni anti-scam sin datos; mercado de sábado flojo).
- Próxima vez: si continúa sin entradas, estudiar would-have P&L de candidatos rechazados solo por liquidez (bucket justo bajo el mínimo) antes de proponer cambio a Àngel.

## 2026-10-31 12:45 — Estudio min_liquidity (Àngel: "Ajusta")
- 566 tokens únicos rechazados SOLO por liquidez (10k-50k). Precio actual DexScreener vs precio al rechazo (pools muertos/liq<1k = -100%):
  10-20k: n=267, mediana -100%, crash 84%. 20-35k: n=204, mediana -99%, crash 82%. 35-50k: n=95, mediana -100%, crash 78%. Base actual (pasa vetos, ≥5000 holders): crash 2%.
- RugCheck solo generó informe para 4/566 → con los vetos actuales casi ninguno sería comprable igualmente. Coste ida+vuelta a 4 USD: impacto ~0.04-0.10% (dentro del 3%), no es el problema.
- Decisión: NO bajar min_liquidity_usd (sigue 50000). Sin cambios en config.

## 2026-10-31 13:01 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso 11:00), panel (10:56), insider, copytrade paper (08:29) vivos; logs frescos (12:52-12:58; Solana tarda ~80s por escaneo en RugCheck); 0 tracebacks Solana; sin reinicios.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.29 USD, todo cash, 0 abiertas. Cierres REAL desde 11:58: 0 (último 01:19, ~12h). Escaneo: 216 pares, 1 con liquidez ≥ mínimo, 0 pasan.
- Copytrade PAPER: 7 cierres nuevos (3 tp +0.99, 4 rug −8.00). DNIPAT sí fue rug real (−99% en 1 min); GHOST20 marcado rug con precio salida > entrada (hueco liquidez=0 DexScreener). Total 28 cierres, 12 ganadores, −23.67 USD, PF 0.21, 12 marcados rug. Sigue NO apto para real.
- Cambios: ninguno (sin entradas reales; no se relajan filtros sin datos, ver estudio 12:45).
- Próxima vez: vigilar si aparecen entradas reales; copytrade paper con PF 0.21 tras 28 cierres → candidato a proponer a Àngel su desactivación o rediseño (filtro anti-rug antes de copiar).

## 2026-10-31 13:58 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso reiniciado 13:48 por SIGTERM externo, arrancó bien en modo trail 8%/-6%/12%), panel, insider, copytrade paper vivos; logs frescos (13:56-13:57); 0 errores Solana nuevos.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.47 USD, todo cash, 0 abiertas (SOL 95.83). Cierres REAL: 0 (último 01:19, ~12.5h). Escaneos: 230-335 pares, 1-2 con liquidez ≥ mínimo, 0 pasan.
- Copytrade PAPER: sin cierres nuevos desde 13:01 (total 28, PF 0.21).
- Cambios: ninguno.
- Próxima vez: igual que 13:01; si sigue sin entradas al anochecer, proponer a Àngel revisar fuentes/universo (no los vetos).

## 2026-10-31 13:48 — Ampliación de fuentes de candidatos (Solana live), filtros SIN cambios
- Salud: módulo vivo; status "viejo" (13:24) era un ciclo lento: RugCheck tardó 778 s en 60 informes. No estaba colgado.
- Añadido en memebot.py scan(): GeckoTerminal pools por volumen 24h (1 llamada más, respetando espaciado 2.1 s), Jupiter toptraded/1h y /24h, toporganicscore/24h, toptrending/24h (100 c/u). Excluye stables/LSTs/wrapped (STABLES). Backup memebot.py.bak_src.
- Reinicio 13:48 sin posiciones abiertas.
- Antes: ~230 pares/scan, 84 pasan liquidez+vol. Después: 316-335 pares, 123-125 pasan liquidez+vol (eval cap 60 sin tocar).
- 0 compras: RugCheck devuelve 400 "unable to generate report" para todo (incl. JUP/BONK) desde ~13:50 → veto rugcheck_unavailable (se mantiene, no se salta).

## 2026-10-31 14:30 — Pasada de mejora del cerebro (Àngel: "Haz una pasada")
- Datos: 689 muestras etiquetadas (candidatos operables + sim trail), split temporal 70/30 (207 test).
- Probado A) features nuevas (holder_growth fuerte, tendencia liquidez negativa, volatilidad m5, dump h1, flujo neto insider, liq media): OOS 97 trades, +0.55%/trade, PF 1.29 vs actual 0.48%/1.27 → mejora marginal; con hiperparámetros tuneados empeora (1.07%, PF 1.47) → NO se adopta.
- Probado B) hiperparámetros elegidos en validación interna del train (sin mirar test): K 20→10, DAMP 0.5→0.3, umbral EV >0 → >1%.
  OOS 70/30: actual 90 tr +0.48% PF 1.27 → nuevo 19 tr +2.57% PF 3.13. Robustez splits 50/60/80: nuevo gana en todos (45 tr +2.78% PF 7.5; 19 tr +4.0%; 16 tr +2.47% PF 2.68) vs actual (+1.22/1.05/0.12%).
- PROMOVIDO B. Backups: brain.py.bak_tune, brain_state.json.bak_tune, memebot.py.bak_tune (gate usa dec["ev_ok"]). Vetos anti-scam, tamaño/stops sin tocar (Kelly sigue capado a position_pct; algo más conservador). Reinicio Solana 14:29 con 0 posiciones.
- Nota: ~4x menos entradas. RugCheck sigue devolviendo 400 → veto rugcheck_unavailable activo, 0 compras posibles.

## 2026-10-31 14:50 — RugCheck fallback (Àngel: "Arregla rug check")
- Cause: api.rugcheck.xyz returns 400 "unable to generate report" for most tokens (BONK/JUP/WIF too), on /report and /report/summary alike, with any UA; not auth/rate-limit. Third-party outage; still serves some cached reports.
- Change (memebot.py, backup memebot.py.bak_rc): if RugCheck fails -> rug_fallback(): GoPlus Solana token_security (keyless) + on-chain getAccountInfo (mint/freeze authority). Fail-closed: no data -> reject.
  Danger flags (any -> score 100, reject): mutable balances, closable, default-frozen, state upgradable, transfer hook, fee upgradable, malicious authority; any transfer-fee config -> transfer_tax veto.
  LP locked = burn% of highest-TVL pool only if Standard AMM; CLMM/pumpswap/unknown -> 0 -> lp_unlocked veto. Top10 excludes pool ids/AMM authority.
  All other vetoes unchanged (5000 holders, 50k liq, honeypot, 3% cost, top10, score<=20), size/stops unchanged.
- Verified: BONK/JUP rejected (CLMM LP undeterminable), WIF passes rug checks (LP 99.8% burned), DJT rejected (mint+freeze auth, hooks).
- Known limit: fallback is stricter than RugCheck -> few entries (pumpswap/CLMM coins rejected) until RugCheck returns.

## 2026-10-31 15:04 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso 14:53, tras fallback RugCheck), panel, insider, copytrade paper vivos; logs frescos (15:03); 0 errores Solana; sin reinicios por mi parte.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.57 USD, todo cash, 0 abiertas (SOL 96.02). Cierres REAL: 0 (último 01:19, ~14h).
- Embudo desde 14:48 (230 candidatos, 0 pasan): liq 160, lp_unlocked 49, top10 47, mint_auth 22, freeze 14, rugcheck_unavailable 13, few_holders 13. El fallback (CLMM/pumpswap -> LP 0) bloquea como se esperaba.
- Copytrade PAPER: PUMPE 2 compras y 2 cierres rug (−4.00). Sigue NO apto para real.
- Cambios: ninguno.
- Próxima vez: si RugCheck vuelve, comprobar que reaparecen entradas; si sigue caído al anochecer, valorar con Àngel cómo verificar LP de pools CLMM/pumpswap (sin relajar el veto).

## 2026-10-31 16:02 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso 15:13, reiniciado fuera de esta revisión), panel, insider, copytrade paper vivos; Solana escribe log (16:00) pero ciclos lentos: RugCheck tardó 656 s en 58 informes (hueco 15:48-16:00). 0 errores Solana; sin reinicios por mi parte.
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.35 USD, todo cash, 0 abiertas (SOL 95.60; caída por precio SOL). Cierres REAL: 0 (último 01:19, ~15h). Escaneos: 280-320 pares, 53-55 con liquidez, 0 pasan (top10, lp_unlocked, few_holders, mint_authority).
- Copytrade PAPER: PUMPE 1 compra + 1 cierre rug (−2.00) a las 15:17-15:18. Sigue NO apto para real.
- Cambios: ninguno.
- Próxima vez: si RugCheck sigue lento/caído al anochecer, proponer a Àngel verificación de LP CLMM/pumpswap (sin relajar vetos); vigilar duración de ciclo Solana.

## 2026-10-31 16:35 (Madrid) — mejora continua del modelo (rutina 2 h)
- Autocrítica:
  1) Error principal operativo: 0 entradas REALES desde 01:19 (~15 h). Causa: RugCheck caído/lento (400 o ~11 min por 60 informes) y el fallback estricto (LP CLMM/pumpswap = 0) veta casi todo. No es un fallo del modelo; vetos sin tocar.
  2) Peor entrada del modelo OOS: −12.3% en token con score_hi + h1_hot + insider_sell (perseguir subida ya hecha). Resto de pérdidas −5% con perfil buy_press+insiders+deep_liq.
  3) Ganadores perdidos OOS: +22% a +31% rechazados con EV −1% a −5% (el modelo es conservador).
  4) Datos: solo 695 muestras (+6 desde 14:30); sin cierres reales ni paper nuevos.
- Reentreno (split temporal 70/30, 209 test): actual K=10/DAMP=0.3/EV>1% → 29 tr, +1.70%/tr, PF 2.64.
- Mejora probada: hiperparámetros elegidos en validación interna (K 5-20, DAMP 0.2-0.5, EV 1-3%) → K=10, DAMP=0.2, EV>1%. OOS 7 tr, +4.39%/tr, PF 99 (sin pérdidas). Splits 50/60/80: 28/8/6 trades, gana en media y PF.
- Decisión: NO se promueve — muestras OOS insuficientes (7 trades en el split principal, 6-8 en dos de los robustez). Se mantiene el modelo actual. Sin cambios en código, config, tamaño, stops ni vetos; sin reinicios.
- Próxima vez: atacar la peor pérdida (penalizar score_hi+h1_hot) cuando haya más muestras; reevaluar DAMP=0.2 con más datos.

## 2026-10-31 17:03 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL, panel, insider, copytrade paper vivos; logs frescos (16:59); 0 errores Solana; sin reinicios. Ciclo lento 16:42-16:56 (~14 min).
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.48 USD, todo cash, 0 abiertas (SOL 95.84). Cierres REAL: 0 (último 01:19, ~16h). Escaneos 285-330 pares, 56-60 con liquidez, 0 pasan. RugCheck vuelve a responder rápido a ratos (60 informes en 7 s a las 16:59).
- Copytrade PAPER: sin cierres nuevos desde 15:18.
- Cambios: ninguno.
- Próxima vez: comprobar si con RugCheck recuperado reaparecen entradas; si no, al anochecer proponer a Àngel revisar verificación LP CLMM/pumpswap (sin relajar vetos).

## 2026-10-31 17:37 (Madrid) — Pump-play reactivado SOLO en papel (OK de Àngel)
- config: `pump_play` sigue en false (nunca compra real); nuevo `pump_paper: true`, `pump_paper_extra_slip_pct: 1.0`.
- memebot.py: si un candidato cumple pump_ok y pump_play=false → se abre posición virtual (`pump_paper_open`), se marca `pump_paper_only` y NO llega a `s.buy`. Pasa los mismos vetos (honeypot/round-trip, LP bloqueada, mint/freeze, liquidez 50k, scam.check).
- Salidas simuladas cada 15 s con precio DexScreener: stop -6%, TP +15%, trailing 5% tras +4%, tiempo 25 min, liquidez <5k = rug. Coste = round-trip Jupiter medido + 1% de deslizamiento extra.
- Resultados: `trades_solana_pump_paper.csv` (tag PUMP_PAPER, columna net_pct). Posiciones abiertas de papel solo en memoria (se pierden al reiniciar).
- Live sin cambios: trail 8% / -6% / 12%, liq 50k, vetos intactos.
- Criterio: solo proponer dinero real con 20+ cierres y profit factor > 1.3 (neto).
- Backups: *.bak_pumppaper.

## 2026-10-31 18:01 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso 17:43 tras activar pump-paper), panel, insider, copytrade paper vivos. Hueco de ~9 min en TODOS los logs (17:51-18:00), carga 0.1, procesos dormidos y reanudados solos → pausa de la máquina, no fallo del bot. Sin reinicios. 0 errores Solana; 4 avisos "pump paper loop Expecting value" (respuesta JSON vacía de DexScreener, inofensivo; vigilar).
- Equity: Binance 998.80 (bear). Coinbase 3.36, halted. Solana REAL 48.46 USD, todo cash, 0 abiertas (SOL 95.82). Cierres REAL: 0 (último 01:19, ~17h). Escaneos ~300 pares, 60 con liquidez, 0 pasan.
- Pump-paper: 0 aperturas aún (trades_solana_pump_paper.csv no existe); 1 bloqueo por scam (Dacity: serial_dev, insiders).
- Copytrade PAPER: 17:31-17:51 2 tp (+0.75), 2 rug (−4.00), 1 compra abierta. Sigue NO apto para real.
- Cambios: ninguno.
- Próxima vez: confirmar primeras aperturas pump-paper; si los avisos JSON se repiten mucho, añadir reintento; al anochecer, si siguen 0 entradas, proponer a Àngel verificación LP CLMM/pumpswap (sin relajar vetos).

## 2026-10-31 18:27 — Cambios pedidos por Rugpull (OK de Àngel), solo endurecen riesgo
Backups: memebot.py / copytrade_paper.py / config.json / DECISIONS.md .bak_rugpull. Reinicio 18:26 sin posiciones abiertas.
1) Pump-play: confirmado solo papel (pump_play=false, pump_paper=true). El camino pump nunca llega a s.buy cuando pump_play=false.
2) Copytrade papel: veto() antes de cada entrada = informe RugCheck obligatorio (fail-closed), mint/freeze, LP>=90% bloqueada, round-trip Jupiter <=3%, + scam.check completo; liquidez mínima 50k (ya estaba).
3) Live (_buy_live): bloquea si price impact cotizado >1% (100 pb) o si EV del modelo < 3x round-trip real medido (o EV desconocido). Nota: el "slip=XXXbps" del log es tolerancia, no deslizamiento real (mínimo 100), por eso se usa el impacto.
   Retro sobre 56 entradas live (55 eran pump-play): impacto>1% bloquearía 6 (−0,28 $, 1 ganadora); round-trip >0,33% (≈ EV típico 1%/3) bloquearía 34 (−1,67 $, 6 ganadoras) vs 22 restantes (−0,72 $, 10 ganadoras).
4) Salidas (net % aprox. por cierre): kill_switch 7 (−1,9%, 0 gan.), sell_pressure 5 (−9,7%, 2 gan.), early_exit 12 (−0,9%, 2 gan., solo pump), protect_take 4 (+5,7%, 4 gan.), pump time 21 (−0,8%). Muestras pequeñas y casi todo pump-play (ya pausado en real); sell_pressure pierde por salir tarde, no pronto; protect_take gana porque el precio ya subió. Sin cambios en salidas.

## 2026-10-31 18:35 (Madrid) — mejora continua del modelo (rutina 2 h)
- Autocrítica:
  1) Operativo: siguen 0 entradas REALES desde 01:19 (~17 h). Causa: vetos (RugCheck lento/caído + fallback estricto LP CLMM/pumpswap, top10, lp_unlocked). No es fallo del modelo; vetos sin tocar.
  2) Pump-paper: 3 cierres, los 3 por tiempo (25 min) con neto −1.47/−1.18/−0.26%: el coste (~1.1-2.6%) se come movimientos pequeños; muestra mínima, sin cambios.
  3) Peores entradas OOS del modelo actual: 4 pérdidas de −14% a −15%, todas con la señal `insiders` (concentración de insiders) + buy_press/holder_growth/vol_liq_hi; una además h1_hot+insider_sell (perseguir subida).
  4) Ganadores perdidos OOS: +22% a +30% con EV −2% a +0.6% (modelo conservador).
  5) Datos: 715 muestras etiquetadas (+20). Copytrade papel: Mischief cerrado por tiempo (+0.17); sigue no apto para real.
- Reentreno (split temporal 70/30, 215 test): actual K=10/DAMP=0.3/EV>1% → 124 tr, +1.80%/tr, PF 1.98.
- Mejora probada: señal nueva `chase` = h1_hot y (score_hi o insider_sell) (penaliza perseguir subidas). 70/30: 122 tr, +2.05%/tr, PF 2.24. Robustez: 60/40 y 80/20 gana (+1.80 vs +1.55, PF 2.43 vs 2.11; +1.78 vs +1.62, PF 2.39 vs 2.14), pero 50/50 PIERDE (+1.51 vs +1.66, PF 1.85 vs 2.03). Las peores pérdidas (−15%) no cambian.
- Decisión: NO se promueve — mejora pequeña, inconsistente entre cortes y no arregla el error principal (pérdidas −15% con `insiders`). Se mantiene el modelo actual. Sin cambios en código, config, tamaño, stops ni vetos; sin reinicios.
- Próxima vez: probar interacción `insiders`+`vol_liq_hi` / pesar más la señal insiders; re-evaluar `chase` con más datos.

## 2026-10-31 18:59 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso 18:26), panel, insider (logs en ráfagas, último 18:33, normal), copytrade paper vivos. Logs frescos (18:51-18:58). Sin reinicios. 0 errores nuevos Solana; avisos "pump paper loop Expecting value" ya 17 (DexScreener vacío, inofensivo).
- Equity: Binance 998.80 (bear). Coinbase halted. Solana REAL 48.54 USD, todo cash, 0 abiertas (SOL 95.97). Cierres REAL: 0 (último 01:19, ~17.5 h).
- Pump-paper: 6 cierres, 0 ganadores, neto suma −9.14% (todos por tiempo 25 min; coste 1-2.6% > movimiento). 1 abierta (Fartcoin). Muestra <20: sin cambios, pero tendencia mala.
- Copytrade PAPER: Mischief +0.17 (time) 18:21; sigue no apto para real.
- Cambios: ninguno.
- Próxima vez: si pump-paper sigue sin ganadores a ~10 cierres, revisar en papel salida por tiempo (25 min) vs coste; nada de dinero real.

## 2026-10-31 19:36 — Prueba on-chain de LP para pools PumpSwap (OK de Àngel)
- Nuevo `lpcheck.py`; se usa solo en `rug_fallback` (cuando RugCheck falla) si el pool principal no es Standard.
- PumpSwap: se lee la cuenta del pool (owner = pAMMBay6…), se comprueba base/quote = mint, y lp_burned% = 1 − supply actual del LP mint / lp_supply del pool. Debe ser ≥90% (umbral existente). Solo cuenta si el pool PumpSwap tiene ≥80% de la liquidez del token.
- CLMM / Whirlpool / DLMM: siguen rechazados (las posiciones NFT no se pueden enumerar de forma fiable con RPC público, ya que getProgramAccounts/indexed requiere token). Cualquier error = 0% = rechazo.
- Tests: CATE, neet, GATO, USOE → 100% quemado (supply LP = 0); DJT (orca) → 0; STONK (meteora) → sin pool PumpSwap → 0.
- Backtest: en la era fallback, 5 monedas PumpSwap tenían "lp_unlocked" como único veto (GATO, DESSA, neet, CATE, USOE). Con RugCheck activo ya daban 100%.
- El resto de vetos, tamaño 8%, stop −6% y trail 12% no cambian. Backup: memebot.py.bak_lpclmm. Reiniciado a las 19:36 sin posiciones abiertas.

## 2026-10-31 19:57 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso 19:36 tras lpcheck), panel, insider, copytrade paper (19:00) vivos. Logs frescos. Sin reinicios. 0 errores Solana; avisos "Expecting value" de DexScreener 33 (inofensivo).
- Equity: Binance 998.80 (bear). Coinbase 3.36 halted. Solana REAL 48.54 USD, todo cash, 0 abiertas. Cierres REAL: 0 (último 01:19, ~18.5 h). lpcheck PumpSwap aún sin aprobar ninguna entrada.
- Pump-paper: 10 cierres, 0 ganadores, neto suma −19.06% (media −1.9%). Todos por tiempo 25 min. Bruto medio ≈ −0.15% (máx +2.4%) vs coste 1.1-3.0%: el setup no se mueve lo bastante para cubrir costes; cambiar la salida no lo arregla.
- Cambios: ninguno (muestra <20 y es papel). Lejos del criterio de dinero real (PF>1.3).
- Próxima vez: a 20 cierres, si PF sigue ~0, proponer a Àngel apagar pump-paper o exigir movimiento esperado > 3x coste en la entrada.

## 2026-10-31 20:35 (Madrid) — mejora continua del modelo (rutina 2 h)
- Autocrítica:
  1) Operativo: 0 entradas REALES desde 01:19 (~19 h). Rechazos últimas 2 h (liq≥50k, 1204 candidatos): top10 786, rugcheck_danger 534, mint_authority 287, few_holders 212, lp_unlocked 202, freeze 184. Son los vetos anti-scam, no el modelo; sin tocar.
  2) Pump-paper (papel): 14 cierres, 1 ganador (BORGY +1.98% neto); todos por tiempo 25 min y todos con `rug_insiders`. Coste 1.2-2.9% > movimiento. Es el peor error vivo, pero es papel y ya hay criterio (20 cierres / PF>1.3).
  3) Peores entradas OOS del modelo actual (corte 70/30): BEAST −13.6%, XTO −12.3/−11.4%, IOF −11.5% ×2. Patrón común: `young` + `h1_hot` (+ buy_press): entrar persiguiendo una subida en monedas de <24 h. La señal `insiders` ya no explica las pérdidas (on: +1.33%/tr, off: +1.38%/tr).
  4) Ganadores perdidos OOS: HI +29.8% (EV −0.05%), jeff +22% (EV −2.7%), HI +22% (EV +0.61%): EV mínimo 1% algo conservador.
  5) Datos: 721 muestras etiquetadas (caché OHLCV 3 días, ventana móvil). Copytrade papel sin cierres nuevos.
- Reentreno (mismo Brain K=10/DAMP=0.3/EV>1%), cortes temporales. Actual: 50/50 145 tr +1.45% PF 2.48; 60/40 113 tr +1.00% PF 1.66; 70/30 84 tr +1.34% PF 1.91; 80/20 67 tr +0.87% PF 1.55.
- Mejoras probadas:
  a) `ins_volhi` (insiders y vol_liq_hi, idea anterior): peor en los 4 cortes (p.ej. 70/30 +0.25% PF 1.13).
  b) `ins_buyp` (insiders y buy_press): peor en 3 de 4.
  c) `young_hot` (young y h1_hot, dirigida al error 3): 50/50 +1.46% PF 2.53, 60/40 +1.06% PF 1.73, 80/20 +1.67% PF 2.21, pero 70/30 PIERDE (+0.99% PF 1.60). Peor pérdida sin cambio (−14%).
  d) `hot_sell` (h1_hot e insider_sell): igual o peor.
- Decisión: NO se promueve ninguna (ninguna gana en todos los cortes). Se mantiene el modelo actual. Sin cambios en código, config, tamaño, stops ni vetos; sin reinicios.
- Próxima vez: re-evaluar `young_hot` con más datos (prometedor en 3/4 cortes); probar umbral EV dependiente de liquidez/coste.

## 2026-10-31 21:00 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (proceso 19:36), panel, insider, copytrade paper vivos. Logs frescos (20:59). Sin reinicios. 0 tracebacks Solana; avisos "Expecting value" DexScreener 44 (inofensivo).
- Equity: Binance 998.80 (bear). Solana REAL 48.38 USD, todo cash, 0 abiertas (baja por precio SOL 95.66). Cierres REAL: 0 (último 01:19, ~20 h). Último scan: 60 con liquidez, 0 pasan filtros.
- Pump-paper: alcanzados 20 cierres. 2 ganadores, neto suma −40.1% (media −2.0%), PF 0.06. Bruto medio −0.16% vs coste 1.1-3.0%. Todos salida por tiempo, todos `rug_insiders`. Criterio de dinero real (PF>1.3) muy lejos.
- Cambios: ninguno (es papel; decisión de apagar/endurecer se propone a Àngel).
- Propuesta: apagar pump-paper o exigir en la entrada movimiento esperado > 3x coste ida y vuelta.
- 2026-10-31 21:40 pump_paper=false por orden de Àngel tras 20 cierres en papel (PF 0,06).

## 2026-10-31 21:59 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL (reinicio 21:40 por pump_paper=false), panel, insider, copytrade paper vivos. Logs frescos (21:54). 0 tracebacks. Sin reinicios por mi parte.
- Equity: Binance 998.80 (bear). Solana REAL 48.30 USD, todo cash, 0 abiertas (SOL 95.49). Cierres REAL: 0 (último 01:19, ~21 h). Último scan: 60 con liquidez, 0 pasan filtros (vetos anti-scam).
- Pump-paper apagado confirmado: sin cierres nuevos tras 21:33.
- Cambios: ninguno (sin muestra nueva).
- Próxima vez: vigilar si sigue la sequía de entradas reales; revisar qué veto domina sin relajar los anti-scam.

## 2026-10-31 22:30 (Madrid) — mejora continua del modelo (rutina 2 h)
- Autocrítica:
  1) Operativo: 0 entradas REALES desde 01:19 (~21 h); último scan 60 con liquidez, 0 pasan (vetos anti-scam). Pump-paper apagado 21:40. Sin tocar vetos.
  2) Peores entradas OOS del modelo (70/30, EV>1%): swordcat −14.1% (insiders+deep_liq), XTO −12.3/−11.4/−11.3%, IOF −11.5% ×2. Patrón: `young`+`h1_hot`+`buy_press` (perseguir subidas en monedas <24 h). Coste ida y vuelta medio: perdedoras 1.11% vs ganadoras 0.76%.
  3) Ganadores perdidos: HI +29.8/+22%, jeff +21.8%, TYGR +21.8% (EV −1.9% a +0.2%).
  4) Datos: 723 muestras etiquetadas (+2).
- Reentreno (Brain K=10/DAMP=0.3/EV>1%). Actual solo-modelo: 50/50 184 tr +1.92% PF 2.88; 60/40 116 +1.45% PF 2.46; 70/30 87 +0.93% PF 1.71; 80/20 58 +1.27% PF 2.83.
- Mejoras probadas: `young_hot`, umbral EV dependiente del coste (0.3/0.5/1×rt) y combinación. La combinación `young_hot` + EV>0.5%+0.5×coste gana en los 4 cortes solo-modelo (p.ej. 70/30 +0.98% PF 1.89; 60/40 +1.77% PF 4.19).
- PERO con la puerta real que ya usa el bot en vivo (EV ≥ 3× coste medido), el umbral por coste es redundante y `young_hot` PIERDE en 3 de 4 cortes (60/40 +0.97% PF 4.39 vs +1.06% PF 5.65; 70/30 +0.84% PF 4.81 vs +0.89% PF 5.68; 80/20 +1.07% PF 8.66 vs +1.22% PF 24.9). Nota clave: con esa puerta la peor pérdida OOS ya baja de −14% a −2.9/−5%: el error de las pérdidas grandes ya está cubierto en vivo.
- Decisión: NO se promueve. Se mantiene el modelo actual. Sin cambios en código, config, tamaño, stops ni vetos; sin reinicios. Script: research/brain_cycle_2230.py.
- Próxima vez: evaluar siempre con la puerta viva (EV≥3×coste); con ella el cuello de botella es la falta de entradas, no las pérdidas; mirar ganadores perdidos (HI, jeff, TYGR) bajo esa puerta.

## 2026-10-31 23:05 (Madrid) — revisión horaria (director financiero)
- Salud: Binance paper, Coinbase live (halted), Solana REAL, panel, insider, copytrade paper vivos. Logs frescos (23:04). 0 tracebacks Solana. Sin reinicios.
- Equity: Binance 998.80 (bear, swing apagado por filtro BTC). Coinbase 3.36 halted. Solana REAL 48.52 USD, todo cash, 0 abiertas (SOL 95.92). Cierres REAL: 0 (último 01:19, ~22 h). Último scan: 339 mints, 60 con liquidez, 0 pasan filtros (vetos anti-scam).
- Pump-paper apagado; copytrade papel sin cierres desde 18:21.
- Cambios: ninguno (sin muestra nueva; no se relajan vetos anti-scam).
- Próxima vez: seguir vigilando la sequía de entradas reales.
## 2026-10-31 20:05 (Madrid) — MVP Hyperliquid con Keel + Coinversa (sesión autónoma de Claude; Àngel: "usa Keel y Coinversa, mejora hasta un MVP que dé muy buen rendimiento")
- Diagnóstico con backtests (Keel, Hyperliquid perps, 4,5 pb + 4,5 pb + funding): la MISMA regla de tendencia sobre 18 memecoins en perps da Sharpe 0,70 / DD −53 % (PF 1,11) frente a Sharpe 1,84 / DD −30 % sobre los 15 mayores perps. El problema del bot es el universo memecoin, no la ejecución. Spec: docs/superpowers/specs/2026-10-31-trading-bot-mvp-design.md.
- 6 estrategias (4 forks de la librería Keel + 2 diseños propios) y variantes, in-sample 2024-08-15→2026-03-31 y fuera de muestra 2026-04-01→2026-10-30 (sin tocar parámetros con la OOS). ELEGIDA: SuperTrend(10,3)+Bollinger+ATR7/21>0,85, 1d, long-only, top-15, 33 %/nombre, 1x, on_change → IS 1,69 / OOS **1,98, +105 %, DD −30 %, PF 1,70**; ventana completa 1,74, +773 %, DD −36,8 %, 8/10 trimestres positivos (no 9/10 como se escribió primero); multiplicador 2,4/3,0/3,6 → 1,59/1,74/1,79. **CORREGIDO a las 21:45 (ver entrada siguiente): estos números llevan supervivencia del universo; los honestos son OOS 1,15 / ventana completa 0,76.** Rechazadas: confluence 4h (IS 1,85 → OOS 0,53), momentum+funding (robusta, 1,99 OOS, pero exige ~15.000 $), rotación top-3 (0,43), estocástico (0,78), meme-perps (0,70). Registro: hl_leg/evidence.json; fuentes DSL en hl_leg/strategies/.
- Capital: a 48 $ el 48 % de las órdenes caería bajo el mínimo de 10 $ de Hyperliquid → NO ejecutable tal cual. Los umbrales de ~132 $ / ~337 $ que se anotaron primero eran engañosos: venían de órdenes de reajuste minúsculas; con `Execution(min_trade_size=0.05)` (v8) a 150 $ solo el 2 % de las órdenes queda bajo mínimo. Decisión: paper run en Keel (dep_01m69j62wfa03zrqxgbf71k436, 1.000 $ simulados, 11:59 UTC diario; **sustituido a las 21:45 por dep_01m69ygrjews0qmgq2sraj8rdr, versión causal**) y pasar a real solo con ≥150 $ y ≥21 días / 20 evaluaciones con paridad (criterios en hl_leg/hl_paper.json). Real = paso manual de Àngel en la web de Keel.
- Coinversa (plan Pro): estudio de 30 días horarios BTC/SOL/FARTCOIN (research/coinversa_study.py): sesgo Apex/Sharps/Crowd vs retorno 1/4/24 h → |corr| ≤ 0,10, signo inconsistente. NO entra en la señal. Queda como capa de riesgo: hl_leg/coinversa.py + hl_context.py (banderas crowd_with_us/apex_against/liq_cluster/high_leverage; multiplicador solo reduce), log horario en data/hl_context.csv, panel /api/hl, proceso en run_forever.sh solo si keys.env tiene COINVERSA_API_KEY. Paths REST no verificables desde la sesión (dominio bloqueado): configurables, fail-safe.
- memebot.py (sin relajar vetos): get() ya no reintenta 3×15 s los 4xx definitivos (RugCheck 400 "unable to generate report" era la causa de escaneos de 650-780 s); RugCheck con timeout 8 s/2 intentos; caché negativa 180 s (rc_fail_cache_s) y presupuesto por escaneo 150 s (rc_scan_budget_s) en prefetch_rug(); lo no verificado sigue vetado (rugcheck_unavailable). Tests: tests/test_memebot_rug.py.
- Pendiente: hallazgos confirmados del workflow de revisión del código (solo los que no relajen vetos/tamaño/stops). Recomendación a Àngel: pasar el memebot a papel hasta que la pata Hyperliquid esté en real.
- 20:40 — Correcciones verificadas en memebot.py/scam.py (dos lectores independientes + verificación manual en el código; ninguna relaja vetos, tamaño ni stops; tests en tests/test_memebot_fixes.py):
  1) Puerta EV real (_buy_live): el round-trip se medía vendiendo `otherAmountThreshold` (= outAmount × (1−slip), slip ≥ 100 pb), así que rt incluía toda la tolerancia y "EV ≥ 3×rt" exigía ≥ 3-5 % → bloqueaba casi todas las compras. Ahora se mide con `outAmount` (fill esperado). La regla 3× y el bloqueo con EV desconocido siguen igual.
  2) Kill switch diario: era un evento único; una venta diferida (lock 5 s), fallida o sin ruta quedaba abierta todo el día con halted=True. Ahora `_flatten` se reintenta cada paso hasta quedar plano (también tras "halt restore").
  3) Posiciones zombi en real (sin ruta/venta imposible): write-off solo si venta completa + ≥5 swaps fallidos + ≥10 quotes sin ruta + ≥15 min + DexScreener aún lista el par con liquidez < 1.000 $ (una caída de Jupiter/RPC nunca da de baja nada). Registra SELL con got=0 "WRITEOFF", libera el slot, aplica cooldown de pérdida y `dead` impide re-adoptar el mint.
  4) guard_loop: una caída de DexScreener reutilizaba el lote anterior y re-sellaba marcas obsoletas como frescas (stops/trail/daily stop sobre precios viejos). Ahora cae a la cotización de Jupiter.
  5) rug(): un informe RugCheck malformado abortaba todo el ciclo de escaneo cada ciclo → ahora fail-closed (None) para ese mint.
  6) reload(): config.json a medio escribir abortaba step() entero (sin manage ni daily stop) → se conserva la config anterior.
  7) score_normalised ausente leía como 0 (mejor nota) → `rc_score_missing` (fail-closed). pump_play por defecto False (borrar la clave ya no activa el pump en real).
  8) scam.check sin datos de RugCheck NI Jupiter pasaba todos los checks → `scam_data_unavailable`. (Con solo RugCheck caído sigue valiendo el fallback GoPlus.)
  9) honeypot(): una cotización ausente (posible caída de Jupiter) se cacheaba 30 min como veto; ahora veta solo ese ciclo. Ban del creador en hilo aparte (antes retenía el lock de ventas hasta 60 s en salidas urgentes).
  10) go_live carga también `seen` (cooldowns de pérdida/reentrada se perdían en cada reinicio) y `dead`. sell_live: la comprobación "ya vendido" compara con el saldo previo (correcta para ventas parciales del 33/50 %; antes podía vender dos veces).
  11) Slots de evaluación: un mint con veto determinista (mint/freeze authority, LP, holders, historial rug, tasa) no se re-evalúa durante 1 h (`hardfail_recent`), liberando los 60 slots para candidatos nuevos; posiciones abiertas e insiders siempre se evalúan. scam.check se ejecuta antes del único logc (evita filas duplicadas pass=True/False que contaminaban eval y el dataset del cerebro).
  - NO aplicado (decisión de Àngel): la puerta del cerebro exige score ≥ 45 mientras el modelo pondera `score_hi` (≥45) como su señal más negativa (p 0,36 vs 0,67): la regla real no es la validada OOS. Opciones: quitar el gate de score en la rama del cerebro o validarlo en learn(). Tampoco: stop diario en SOL en vez de USD, cierre de ATAs (rent ~0,002 SOL/mint ≈ 4,7 $ bloqueados), registro de posiciones que reconcile descarta.
- 21:15 — Segundo lote (lectores "modelo" y "ejecución/APIs" del workflow, verificado en código; tests en tests/test_brain.py y tests/test_memebot_fixes.py):
  12) live_sol.swap(urgent=True) para rug/liquidity_pull/dev_dump/gap/stop/kill: prioridad "veryHigh" con tope 10× (≤1.000.000 lamports ≈ 0,10 $) en vez de "medium"/100k como una compra rutinaria. sell_live lo usa. Sin lookup de fee para la firma sintética "late_landing" (bloqueaba el lock de ventas ~30 s).
  13) Rent de la cuenta de token (0,00203928 SOL ≈ 0,19 $) se contabiliza como coste en la primera compra de un mint (antes invisible: 4-6 % de una posición de 3-5 $; ~4,7 $ bloqueados en 24 ATAs). Cerrar las ATAs vacías (recuperar el rent) queda pendiente.
  14) Capa scam fail-closed también ante excepciones (`scam_error`).
  15) copytrade_paper (solo papel): "rug" requiere pool desaparecido o liquidez < 20 % de la de entrada, en 2 sondeos consecutivos, y mientras el contador está armado la posición espera confirmación en vez de salir con un precio dudoso (15 de 36 "rugs" tenían precio de salida > entrada por huecos liquidity=0 de DexScreener). Reglas puras en copytrade_rules.py. insider.py: RPC con commitment "confirmed" (~12 s menos de retraso). news.py: "blacklists/checklist/delisting" ya no cuentan como noticia positiva de listing; "(SEC)/(ETF)/(AI)…" no son tickers.
  16) Cerebro (brain.py / eval_solana.sim), integridad de la evaluación, sin tocar vetos/tamaño/stops:
      - sim() replica la regla de salida REAL: exit_mode=trail → hard stop neto de costes + trail 12 % desde el máximo (antes etiquetaba con el bracket v3.1 que ya no se opera); orden conservador dentro de la vela (stop con el mínimo antes que TP con el máximo; trail contra el máximo de la vela anterior).
      - Dataset: la primera vela debe estar a ≤5 min del avistamiento (la caché reemplazaba las velas por las últimas 1000 y la repetición empezaba horas después); caché de velas por fusión; solo etiquetas resueltas (salida disparada o ≥ max_hold_hours); máximo 6 filas por mint y día (los tokens establecidos dominaban el 61 % del dataset); los rechazos del propio modelo (brain_ev<=0) y los "no_sellability_check" (libro lleno/halt) vuelven al universo entrenable (sin bucle de retroalimentación).
      - learn(): purga (ninguna etiqueta de train usa velas de la ventana de test), evalúa la POLÍTICA DESPLEGADA (ev>1 % Y score≥brain_min_score; antes solo ev), exige ≥10 mints distintos y 3 reentrenos consecutivos de acuerdo para activar/desactivar (histéresis); escrituras atómicas; el hilo de aprendizaje registra excepciones en vez de morir en silencio. Consecuencia esperada: el cerebro puede pasar a modo sombra cuando se evalúe con honestidad (sus +1,8 %/op OOS estaban inflados por solapamiento 18× y etiquetas de 20 min).
      - Bug `young`: age_h=0,0 (pool recién creado) se leía como 99 h.

## 2026-10-31 21:45 (Madrid) — Revisión adversarial del trabajo de la sesión: lo que estaba mal y cómo queda (Claude, sesión autónoma)
- **Supervivencia del universo (lo más importante).** El top-15 de la estrategia elegida lo resolvió Keel el 2026-07-06, dentro de la ventana fuera de muestra: PUMP, XPL, LIT, ZEC, VVV, GRAM están en la lista porque se hicieron grandes en 2026. Comprobaciones: (a) la misma regla sobre una cesta de nombres anteriores a 2025 da ventana completa Sharpe 0,33 / +7,5 % / DD −71 % y OOS 0,15 (str_01m69nekhr5kw2p5xk64etgh8b); (b) versión **causal** (pool top-60 resuelto hoy, top-15 re-elegido cada 7 días por volumen de los 30 días previos, `RollingVolumeUniverseMask`): **OOS Sharpe 1,15 / +43,5 % / DD −30 % / PF 1,31**; ventana completa 0,76 / +91 % / **DD −58 %**, 6/10 trimestres positivos (2025-Q1 −28 %, 2026-Q1 −28 %), tramo in-sample +29 % (str_01m69nnhfd4z38bbcy07gs7kk6, btr_01m69npabhj1hsrvx1534x709n, btr_01m69np54xf2f34gbpx0nb77yd). (c) Un filtro de régimen de mercado sobre la causal baja el DD in-sample pero mata el OOS (0,33 / +1 %): rechazado (str_01m69y4wqh1epbc2jg5xambwt7). Conclusión: la regla tiene una ventaja **pequeña** medida sin trampas; "muy buen rendimiento" no está demostrado. Paper run cambiado a la causal: dep_01m69ygrjews0qmgq2sraj8rdr (1.000 $ simulados, 11:59 UTC); el anterior (dep_01m69j62wfa03zrqxgbf71k436, 1 evaluación) parado. Fuente: hl_leg/strategies/supertrend_bollinger_causal_top15.keel.py; la de hindsight queda como referencia con aviso en cabecera.
- **"El universo memecoin es el problema"** se afirmó comparando dos universos de hindsight (memes 0,70 / −53 % vs top-15 1,84 / −30 %). Contra el top-15 causal in-sample (+29 % / −58 %) la distancia es pequeña: los backtests de Keel no lo demuestran. Lo que sí lo dice es el historial real del bot (PF 0,44). Corregido en README, hl_leg/README y spec.
- **Capital mínimo**: los ~132 $ / ~337 $ venían de órdenes de reajuste minúsculas del LeverageCap; con `min_trade_size=0.05` a 150 $ solo el 2 % de las órdenes queda bajo el mínimo de 10 $ (btr_01m69npdg72gr22ygwya3wtvbw); la causal: <25 % desde ~64 $, <5 % desde ~100 $. Criterio de paper unificado a **21 días / 20 evaluaciones** (umbrales de Keel; antes se escribió "4 semanas" en un sitio).
- **Correcciones a mis propias correcciones (verificadas por lectores adversarios, tests en tests/):** rent de la ATA ya no entra en el coste de compra (hacía saltar el hard stop neto −6 % con posiciones de 3-5 $): se anota en `rent_usd` y se descuenta al cerrar la posición completa; el kill switch ya no usa una bandera `_flatten` que nunca se limpiaba: aplana mientras `halted` persista y no exista KILL_solana; el write-off exige evidencia positiva (DexScreener lista el par con liquidez < 1.000 $ **y** Jupiter responde a una cotización USDC→SOL): una caída de Jupiter o un hueco de DexScreener nunca da de baja nada; ventas fallidas con back-off exponencial (3+ fallos → espera 30 s·2^n, máx. 30 min) para no quemar prioridad; `prefetch_rug` ya no bloquea `manage()` (bucle con `wait(≤30 s)` + `inline_manage()`); `_ban` con lock; cliente Coinversa leyendo el payload real (`market.totalOi`, `avgLongLeverage`, `nearLiquidationNotional` de nivel superior); hl_context escribe `status: ok/partial/degraded` conservando las últimas monedas buenas en vez de un fichero vacío con fecha fresca; histéresis del cerebro asimétrica (desactivar es inmediato, activar exige 3 votos); velas con hueco etiquetadas con min(stop, cierre) en vez de −6 % fijo; paquete `hyperliquid/` renombrado a `hl_leg/` (sombreaba al SDK oficial).
- **Puerta EV real (corrección 1 de las 20:40), para decisión de Àngel:** medir el round-trip con `outAmount` en vez de `otherAmountThreshold` hace la puerta **numéricamente más laxa** que el código anterior (el rt deja de incluir la tolerancia de slippage). Coincide con la calibración aprobada a las 18:27 (EV ≥ 3× coste real), pero es un cambio que **puede aumentar el número de compras en real**: si Àngel prefiere el comportamiento antiguo, basta con volver a `otherAmountThreshold` en `_buy_live`. Grok debe vigilar la primera hora (HANDOFF §3).
- insider.py: `parse_swap` pedía `getTransaction` en commitment finalizado mientras la lista de firmas venía en "confirmed", así que el cursor avanzaba sobre swaps aún no consultables y se perdían; ahora misma commitment y cursor fail-closed (`pending_swaps`: una firma solo se marca cuando su tx se ha podido leer; se reintenta si no). Tests en tests/test_rules.py.
- Estudio Coinversa reproducible: entradas copiadas a research/data/coinversa_2026-10/ (antes el script leía una ruta temporal de la sesión).
- Pendiente para Àngel (no aplicado): memebot a papel; puerta del cerebro (score ≥ 45 vs modelo); stop diario en SOL; cierre de ATAs vacías; registro de posiciones que `reconcile` descarta; decidir si la puerta EV queda como está (ver arriba).
- Tests: 51 pasan (`python3 -m pytest -q tests/`). Cuota Keel: 43 de 75 backtests restantes en el periodo (18 de la primera semana).

## 2026-10-31 23:08–23:20 — Instalación traspaso Claude (opción B, zip) — Grok
- Aprobado por Àngel: instalar con la puerta EV nueva (outAmount, más laxa).
- Parada sin posiciones abiertas (open=[]), sin venta en curso. Backup completo: /workspace/ai-trading-bot.bak_2026-10-31_2308.
- Copiados según HANDOFF §2: memebot, scam, brain, eval_solana, live_sol, copytrade_paper, copytrade_rules, news, insider, dashboard, run_forever.sh, PLAYBOOK, README, HANDOFF_GROK; hl_leg/, tests/, research/coinversa*. Eliminado hyperliquid/. NO tocados config.json, data/, state_*, trades_*, keys.env, wallet, dashboard_password, brain_state.
- Diferencia: el memebot.py nuevo no incluía la integración lpcheck (prueba LP-burn PumpSwap en rug_fallback). Re-añadida tras el cálculo de `lp` (mismo bloque de antes, fail-closed).
- config: pump_play=false, pump_paper=false (sin cambios).
- Tests: `python3 -m pytest -q tests/` → 51 passed in 1.25s.
- Reinicio con run_forever.sh + copytrade_paper.py (aparte, como antes). insider_loop.sh antiguo retirado (run_forever ya lanza insider). 6 procesos, sin duplicados.
- Vigilancia 12 min: prefilter/rugcheck 1–21 s (≤150 s), sin tracebacks nuevos, modo REAL confirmado (8%, −6%, trail 12%). 0 compras (0 pasan filtros). El logger Coinversa de run_forever queda inactivo (no hay key).
- 2026-10-31 23:35 Àngel autoriza impacto de compra hasta 5% (antes 1%). max_buy_impact_pct=5 (defecto en código).

## 2026-10-31 23:50 — Panel móvil reconstruido (solo panel, sin tocar trading/config/claves) — Grok
- Causa: /live (live_view.py) hacía polling cada 1,5 s sin control de peticiones en vuelo ni timeout; a través de Tailscale Funnel en el móvil las peticiones se acumulaban y el navegador redibujaba todo (DOM + canvas) en cada tick → bloqueos. Además mostraba poca información. El servidor en sí respondía rápido (Flask threaded, 2–40 ms).
- Nuevo panel_v2.py + panel_v2.html en /live: API /api/live2 cacheada 4 s, lectura solo de colas de ficheros (~35 ms en frío, ~2 ms en caché); refresco cada 12 s, una sola petición a la vez, timeout 8 s, pausa con la pestaña oculta, gráfico solo se redibuja si cambia.
- Muestra: saldo/P&L día + curva 48 h, posiciones (entrada, P&L, stop −6 %, trailing), escaneos (evaluadas/pasan), motivos de rechazo 24 h, compras bloqueadas, operaciones reales, salud de procesos, cerebro, Coinbase/Binance, últimas DECISIONS.
- Panel antiguo en /live_old; avanzado sigue en /panel. Backups: dashboard.py.bak_panel, live_view.py.bak_panel. Solo se reinició dashboard.py (run_forever lo relanza).

## 2026-10-31 23:50 Acceso remoto al panel
- Funnel inestable: el proxy sandbox (198.18.0.1) corta TLS (handshake EOF) y PollNetMap EOF; el host también 'duerme' (time jump).
- Probado cloudflared quick tunnel --protocol http2: el proxy corta TLS a argotunnel :7844 -> HTTP 530. SSH (localhost.run) también bloqueado. Watchdog tunnel_watchdog.sh creado pero parado. Sin cambios en trading/config/claves.

## 2026-11-01 00:05 — Revisión horaria CFO — Grok
- Salud: 6 procesos vivos (run_forever, solana, binance, coinbase, insider, dashboard, copytrade_paper), logs frescos, 0 errores/tracebacks. Sin reinicios.
- Solana REAL: equity 48,21 $, sin posiciones; 0 compras desde la instalación de las 23:08. Bloqueos: PAWCAT (impacto 1,27 % > 1 %, antes del cambio a 5 %), AAPLCAT (requiere 510 bps de slippage > máximo). Binance/Coinbase sin operaciones nuevas.
- Sin cambios (muestra insuficiente). Próxima vez: vigilar si la puerta EV/impacto 5 % genera compras y su resultado.
- 2026-11-01 00:11 Àngel: tope slippage compra 5% y aceptar si se pasa por poco -> max_buy_slip_bps=550, max_buy_impact_pct=5.5.

## 2026-11-01 00:26 — X buzz signal (owner OK: "Sí, añade la señal de X")
- New: x_buzz_candidates.py, x_buzz_score.py, X_BUZZ_ROUTINE.md, data/x_buzz.json (written by a 15-min routine with the x MCP tools).
- memebot.x_buzz_adj: score points only (+2..+6 genuine buzz, −3 shill-heavy), applied AFTER brain sizing; vetoes in f untouched; size and stops use the pre-X score (score_noX); missing/stale(>45 min)/broken file = 0. Buy log reason shows x=+N.
- Test run 00:25: cashtag search is noisy (X ignores '$'), so only posts naming the mint or literal $SYM count. Top: JUP 47, AAPLCAT 33 (shill 0.36, one VIP-telegram caller), PAWCAT 25 (shill 0.53 → would get −3). Nobody reached the +bonus bar.
- Backup memebot.py.bak_xbuzz. Tests 52/52.

## 2026-11-01 00:30 (Madrid) — mejora continua del modelo (rutina 2 h)
- Autocrítica:
  1) Operativo: 0 cierres REALES desde 01:19 del 31-oct (~23 h); sin posiciones. Bloqueos recientes de compra por impacto/slippage (PAWCAT, AAPLCAT) ya resueltos por Àngel (5 %/550 bps a las 00:11). Solana reiniciado 00:26 (señal X). Sin trades paper nuevos (pump-paper apagado).
  2) Dataset honesto (tras las correcciones de Claude: etiquetas con salida real trail 12 %/−6 % neto, purga, máx. 6 filas/mint/día): 368 filas, 99 mints, acierto 20,7 %, media −11,4 %/op, PF 0,15. 35 filas ≤ −30 % (huecos/colapsos), dominadas por imitadores de marcas/stablecoins (Apple, NVIDIA/Nvidia, TESLA SI, Gemini, USDP, USDF, XTO/X T O, SPACEINU…) que pasan los vetos duros y entran en el universo entrenable.
  3) Peores filas OOS: Apple −33 %, AAPLCAT −17 %, GTA6 −15 % ×3: perfil `buy_press`+`vol_liq_hi`+`young`/`h1_hot` (perseguir subidas de imitadores).
  4) Ganadores perdidos: XTO +40/+36/+31 % (el mismo token también da −30 % o peor: lotería), iCoin +13 %, KIM +12 %.
- Reentreno (Brain K=10/DAMP=0.3, puerta viva EV>max(1 %, 3×coste) y score≥45): el modelo actual selecciona 0 operaciones en los 4 cortes temporales con purga (50/60/70/80 %); EV máximo en test ≈ −17 %. brain_state: active=False (modo sombra) — correcto: no hay ventaja medible en este universo.
- Mejoras probadas (dirigidas al error 2, colas de −100 % que hunden avg_loss): (a) hiperparámetros K∈{5,10,20} × DAMP∈{0,2;0,3;0,5}; (b) winsorizar las pérdidas al ajustar (−30/−15/−8 %); (c) quitar el suelo de score en evaluación. Todas: 0 operaciones OOS (EV máx. −2,8 % a −9,4 % incluso con pérdidas topadas a −8 %). No hay muestras para comparar.
- Decisión: NO se promueve nada. Se mantiene el modelo actual (sombra). Sin cambios en código, config, tamaño, stops ni vetos; sin reinicios; sin backup (nada reemplazado). Script: research/brain_cycle_0030.py.
- Para Àngel/CFO (no aplicado, solo endurecería): un veto de imitadores de marca/stablecoin por nombre (ya existe `audit_stable_impersonator` en auditoría) eliminaría la mayoría de las colas ≤ −30 % del universo.
- Próxima vez: re-evaluar cuando el dataset honesto tenga más filas; probar la tasa base/EV excluyendo imitadores para ver si aparece algún subconjunto con EV > 0.

## 2026-11-01 00:36 — Vetos de entrada: imitadores de marca/stablecoin + ya disparada (owner OK: "Sí, aplica los dos filtros") — Grok
- Solo endurecen. Ningún veto, tamaño ni stop relajado. Backup: memebot.py.bak_entryveto.
- `brand_fake(sym, name)`: veto en la entrada (antes de RugCheck) para APPLE/AAPL, NVIDIA/NVDA, TESLA/TSLA, GEMINI, AMAZON, GOOGL, MSFT, BLACKROCK, PAYPAL/PYUSD, TETHER/USDT/USDC/USDP/USDF/USDE/USD1, XTO (los espacios se ignoran: "X T O"). Se suma a `stable_fake`, que se mantiene.
- `entry_pumped`: veto si priceChange h1 > `max_entry_h1_pct` (por defecto 50). Umbral elegido con el dataset honesto (research/entry_veto_study.py), una vez quitadas las marcas: h1>50 elimina las 8 pérdidas ≤−30 % que quedaban y solo 6 de 70 ganadoras. Umbrales más bajos (h1>20/30) también eliminan las 8, pero pierden 12 y 9 ganadoras. Se descartó m5: no separa (m5>5 quita 2 colas y 12 ganadoras).
- Backtest (368 filas): todas 76 ganadoras / 35 pérdidas ≤−30 % / media −11,4 %. Veto de marcas: −43 filas (27 colas, 6 ganadoras, todas de XTO), media −5,3 %. Con los dos vetos: 277 filas, 64 ganadoras, 0 colas, media −3,0 %. La EV sigue siendo negativa: los vetos reducen pérdidas, no crean ventaja.
- Tests: 54 passed (nuevo tests/test_entry_veto.py). Reinicio a las 00:36 sin posiciones ni venta en curso. REAL, 8 %, −6 %, trail 12 % confirmados.

## 2026-11-01 ~00:50 — Solana Tracker SHADOW signal (paper only)
- Added solanatracker.py + st_shadow_daemon.py (separate process; memebot.py NOT modified, no restart needed). Key stored in keys.env (chmod 600, backup keys.env.bak_st).
- Shadow veto: snipers+bundlers+dev >22% supply, insiders >22%, creator with >=3 or >=50% dead tokens (liq<100$ after 1h), or ST "rugged". Shadow prio: migrated <6h, >=300 holders, buys>sells.
- Logs data/st_shadow.jsonl (with live pass/fail/bought), forward returns +1h/+6h/+24h in data/st_forward.jsonl. Review after 48h (~03/11 01:00) before any live use.
- Budget: <=1 req/1.2s, cap 400 req/day, caches 15min/6h/5min. Tests: tests/test_solanatracker.py.
- Creator rug rule tightened to >=3 AND >=50% (KIM/CATE/CLAUDIA-style 500-token deployers were false positives).

## 2026-11-01 00:52 — Solana Tracker en REAL (orden de Àngel 00:49)
- memebot: tras x_buzz, si el candidato no tiene vetos duros, `solanatracker.live_check()`: veto duro (snipers+bundles+dev >22%, insiders >22%, creador >=3 muertos y >=50%, flag rugged de ST) y +3 de score si prio (migrada <6h, >=300 holders, compras>ventas). Sin clave/API caída/presupuesto agotado = neutral. Solo endurece; tamaño 8%, stops -6%/12%, slippage/impacto sin tocar. Desactivar: `st_live: false` en config.
- Presupuesto: mismo caché/contador que st_shadow_daemon (cap 400/día, escrituras atómicas). No se sube (plan gratis ~10k/mes ≈ 330/día).
- run_forever.sh lanza st_shadow_daemon (con guarda anti-duplicado) → sigue el registro de retornos a futuro.
- Tests: tests/test_st_live.py; 65 pasan. Backups *.bak_stlive.

## 2026-11-01 01:01 — Revisión CFO horaria — Grok
- Salud: todos los procesos vivos (solana, binance paper, coinbase live, insider, copytrade, dashboard, st_shadow); logs frescos; 0 errores nuevos (los avisos 6024 de venta son del 30-oct).
- Equity: Solana REAL 48,23 $ (sin posiciones), Coinbase 3,25 $ (SOL-USD abierta), Binance paper sin operaciones desde 29-oct.
- Hallazgo: 0 cierres REALES desde 31-oct 01:19 (~24 h). Causa estructural, no impacto/slippage: memebot.py:1061 pone `_ev=None` cuando brain_state.active=False (modo sombra), y la puerta viva (l.486) bloquea toda compra con EV None ("PAWCAT blocked: EV None%" a las 00:37 y 00:52). Mientras el cerebro siga en sombra (sin ventaja OOS), el bot REAL no comprará nada.
- Decisión: sin cambios (relajar la puerta subiría el riesgo; requiere orden de Àngel). Se le informa.
- Próxima vez: si Àngel decide, opciones: mantener (capital protegido), o puerta alternativa sin cerebro (p. ej. score ≥ umbral + ST pass + rt bajo) en tamaño reducido.

## 2026-11-01 01:58 — Revisión CFO horaria — Grok
- Salud: todos los procesos vivos (solana, binance, coinbase, insider, copytrade, dashboard, st_shadow; data/st_shadow.jsonl fresco); 0 errores nuevos; sin reinicios.
- Equity: Solana REAL 48,34 $ (sin posiciones), Coinbase 3,25 $ (SOL-USD abierta, día +0,4 %), Binance paper sin operaciones.
- Sin operaciones nuevas. PAWCAT bloqueado otra vez por EV None (01:08, 01:26, 01:43): sigue la causa estructural del cerebro en sombra, ya informada a Àngel a las 01:01.
- Sin cambios (pendiente de decisión de Àngel). Sin informe nuevo: no hay nada nuevo.

## 2026-11-01 02:30 (Madrid) — mejora continua del modelo (rutina 2 h)
- Autocrítica:
  1) Operativo (error principal): 0 compras/cierres REALES desde 31-oct 01:19 (~25 h). Causa ya identificada por el CFO (01:01): cerebro en sombra (active=False) → `_ev=None` → la puerta viva bloquea todo (PAWCAT bloqueado varias veces; además SMART en sombra marca PAWCAT early_exit con 12 vendedores tempranos, así que el bloqueo ahí fue acertado). Sin trades paper nuevos. Fuentes de datos: sin errores nuevos en el log.
  2) Dataset honesto: 393 filas (+25), 99 mints, media −11,1 %/op, PF 0,15. En el universo coherente con los vetos vivos de 00:36 (sin marcas/stablecoins ni h1>50 %): 302 filas, 73 mints, media −3,3 %, PF 0,34 → los vetos recortan pérdidas pero no hay ventaja.
- Mejora probada (dirigida al error 1: el modelo no encuentra EV>0 porque se entrena con filas que los vetos vivos ya excluyen): reentrenar solo con el universo coherente con los vetos, con K∈{5,10,20}, DAMP∈{0,3;0,5} y pérdidas topadas a −15 %, cortes temporales con purga 50/60/70/80 %.
- Resultado OOS: modelo actual 0 operaciones en todos los cortes; candidatos 0 operaciones (EV máx. en test −5,5 % a +0,23 %, nunca por encima de la puerta max(1 %, 3×coste)). Sin muestras para comparar.
- Decisión: NO se promueve. Se mantiene el modelo actual (sombra). Sin cambios en código, config, tamaño, stops ni vetos; sin reinicio; sin backup (nada reemplazado). Script: research/brain_cycle_0230.py.
- Próxima vez: K=5 en el universo filtrado es el que más se acerca (EV máx. +0,23 % en corte 70 %); revaluar cuando haya más filas.

## 2026-11-01 02:57 — Revisión CFO horaria — Grok
- Salud: todos los procesos vivos (solana, binance, coinbase, insider, copytrade, dashboard, st_shadow); logs frescos; 0 errores nuevos (los contados son del 29/30-oct); sin reinicios.
- Equity: Solana REAL 48,30 $ (sin posiciones), Coinbase 3,25 $ (SOL-USD abierta, día +0,3 %), Binance paper 998,80 (sin operaciones, régimen bear).
- Sin operaciones nuevas. PAWCAT bloqueado otra vez por EV None (02:03): misma causa estructural (cerebro en sombra), ya informada a Àngel a las 01:01.
- Sin cambios; sin informe (nada nuevo). Próxima vez: igual, salvo decisión de Àngel sobre la puerta EV.

## 2026-11-01 03:59 — Revisión CFO horaria — Grok
- Salud: todos los procesos vivos (solana, binance, coinbase, insider, copytrade, dashboard, st_shadow); logs frescos; 0 errores nuevos (los contados son del 29/30-oct); sin reinicios.
- Equity: Solana REAL 48,21 $ (sin posiciones), Coinbase 3,24 $ (SOL-USD abierta, día +0,08 %), Binance paper 998,80 (sin operaciones, régimen bear).
- Sin operaciones nuevas ni compras bloqueadas nuevas desde 02:03 (PAWCAT, EV None por cerebro en sombra; ya informado a Àngel a las 01:01).
- Sin cambios; sin informe (nada nuevo). Próxima vez: igual, salvo decisión de Àngel sobre la puerta EV.

## 2026-11-01 04:30 (Madrid) — mejora continua del modelo (rutina 2 h)
- Autocrítica:
  1) Operativo (error principal, sin cambios): 0 compras/cierres REALES desde 31-oct 01:19 (~27 h) y 0 paper nuevos. Cerebro en sombra (active=False) → `_ev=None` → puerta viva bloquea todo: PAWCAT bloqueado otra vez a las 04:00 y 04:18 (rt 1,0–1,4 %). SMART en sombra seguía marcando PAWCAT early_exit/whale_dump, así que el bloqueo sigue siendo razonable. Fuentes de datos: sin errores nuevos en el log.
  2) Dataset honesto: 442 filas (+49), 102 mints, media −10,3 %/op, PF 0,15. Universo coherente con los vetos vivos: 351 filas, 76 mints, media −3,4 %, PF 0,31 (empeora ligeramente vs 02:30: −3,3 % / 0,34).
- Mejora probada (dirigida al error 1, que el modelo no encuentra subconjunto con EV>0): nuevas features binarias de coste y calidad de entrada (rt_low <1,5 %, score_hi ≥60, h1_neg <0, h1_mid 0–20 %), universo filtrado, K∈{5,10}, DAMP 0,3, pérdidas con/sin tope −15 %, cortes temporales con purga 50/60/70/80 %.
- Resultado OOS: modelo actual 0 operaciones en todos los cortes; candidatos también 0 (EV máx. en test −4,4 % a +0,09 %, nunca sobre la puerta max(1 %, 3×coste)). Las features nuevas no aportan separación (K=5 en corte 60 %: +0,15 % → +0,09 %). Sin muestras para comparar.
- Decisión: NO se promueve. Se mantiene el modelo actual (sombra). Sin cambios en código, config, tamaño, stops ni vetos; sin reinicio; sin backup (nada reemplazado). Script: research/brain_cycle_0430.py.
- Próxima vez: probar etiquetado con horizonte de salida más corto (salida rápida en el primer +x %) en vez de features nuevas; revaluar con más filas.

## 2026-11-01 04:59 — Revisión CFO horaria — Grok
- Salud: todos los procesos vivos (solana, binance, coinbase, insider, copytrade, dashboard, st_shadow); logs frescos; 0 errores nuevos en solana; sin reinicios.
- Equity: Solana REAL 48,30 $ (sin posiciones), Coinbase 3,25 $ (SOL-USD abierta, día +0,3 %), Binance paper 998,80 (sin operaciones, régimen bear).
- Sin operaciones nuevas. PAWCAT bloqueado otra vez por EV None (04:00, 04:18, 04:49): misma causa estructural (cerebro en sombra), ya informada a Àngel a las 01:01.
- Sin cambios; sin informe (nada nuevo). Próxima vez: igual, salvo decisión de Àngel sobre la puerta EV.

## 2026-11-01 05:59 — Revisión CFO horaria — Grok
- Salud: todos los procesos vivos (solana, binance, coinbase, insider, copytrade, dashboard, st_shadow); logs frescos; 0 errores nuevos en solana; sin reinicios.
- Equity: Solana REAL 48,24 $ (sin posiciones), Coinbase 3,25 $ (SOL-USD abierta, día +0,15 %), Binance paper 998,80 (sin operaciones, régimen bear).
- Sin operaciones nuevas. Bloqueos: PAWCAT (05:05, 05:25) y SIS (05:35) por EV None (cerebro en sombra, ya informado a las 01:01); SIS vetado a las 05:54 como no vendible (rt 12,7 %), veto correcto.
- Sin cambios; sin informe (nada nuevo). Próxima vez: igual, salvo decisión de Àngel sobre la puerta EV.

## 2026-11-01 06:30 (Madrid) — mejora continua del modelo (rutina 2 h)
- Autocrítica:
  1) Operativo (error principal, sin cambios): 0 compras/cierres REALES desde 31-oct 01:19 (~29 h) y 0 paper nuevos. Cerebro en sombra → `_ev=None` → la puerta viva bloquea todo: PAWCAT (04:49, 05:05, 05:25) y SIS (05:35). SIS se vetó después como no vendible (rt 12,7 %), veto correcto.
  2) Fuente de datos débil: Solana Tracker devuelve "neutral" en el 89 % de los chequeos de hoy (3361 neutral / 404 pass / 32 reject), probablemente por el tope de presupuesto o datos que faltan. El filtro aporta poco ahora mismo. No se toca (solo endurece; el presupuesto no se sube).
  3) Dataset honesto: 492 filas (+50), 109 mints, media −9,6 %/op, PF 0,16. Universo coherente con los vetos vivos: 401 filas, 83 mints, media −3,35 %, PF 0,32.
- Mejora probada (dirigida al error 1, la que quedó pendiente a las 04:30): reetiquetar con salida rápida, cobrando el primer +2/+3/+5 % neto (tras coste de ida y vuelta) antes de la salida original. K∈{5,10}, DAMP 0,3, universo filtrado, cortes temporales con purga 50/60/70/80 %.
- Resultado: la salida rápida mejora un poco el universo entero (media −3,35 % → −2,8 %; PF 0,32 → 0,35 con +5 %), pero sigue negativa. OOS: modelo actual 0 operaciones en todos los cortes; candidatos también 0 (EV máx. en test −2,7 % a −0,19 %, nunca sobre la puerta). Sin muestras para comparar.
- Decisión: NO se promueve. Se mantiene el modelo actual (sombra). Sin cambios en código, config, tamaño, stops ni vetos; sin reinicio (no había ventas en curso; 0 posiciones); sin backup (nada reemplazado). Script: research/brain_cycle_0630.py.
- Próxima vez: el universo actual no tiene ventaja con ningún etiquetado probado; probar features de flujo (compras/ventas, smart-wallet entrante) del registro st_shadow cuando tenga retornos a futuro suficientes.

## 2026-11-01 07:03 — Revisión CFO horaria — Grok
- Salud: todos los procesos vivos (solana, binance, coinbase, insider, copytrade, dashboard, st_shadow); logs frescos; 0 errores hoy en los tres bots; sin reinicios.
- Equity: Solana REAL 48,36 $ (sin posiciones), Coinbase 3,26 $ (SOL-USD abierta, día +0,43 %), Binance paper 998,80 (sin operaciones, régimen bear).
- Sin operaciones nuevas. Bloqueos de la última hora: BLOB (wash_organic0, repetido) y PAWCAT (wash_traders 375/8470) por el filtro anti-scam; vetos correctos. Solana Tracker sigue devolviendo casi todo "neutral".
- Sin cambios; sin informe (nada nuevo). Próxima vez: igual, salvo decisión de Àngel sobre la puerta EV.

## 2026-11-01 07:2x — ALT entry gate (owner OK 07:16) + Solana Tracker budget fix
- Model in shadow -> EV None blocked every live buy. ALT gate: allowed only if ALL hard vetoes pass (unchanged), ST real verdict (not neutral), score (pre-X) >= 50, real Jupiter round-trip (outAmount) <= 1.5%. Size 4% equity (half of 8%), no $3-5 floor; stops -6%/12% trail, slip/impact caps unchanged. Logged gate=alt. EV present -> EV>=3x rule unchanged.
- Score 50 chosen: all recent passing candidates scored 45-59 (normal min 45); 60 would never fire.
- ST neutral 89%: daily cap 400 exhausted by bot calls on every low-score candidate + shadow daemon. Fix: bot calls ST only if score >= min_score-5; daemon capped at 120/day and skips score<35, re-check 2h; cache tokens 1h, deployer 24h. Cap not raised.
- Backups *.bak_altgate. Tests 67 pass.

## 2026-11-01 07:58 — Revisión CFO horaria — Grok
- Salud: todos los procesos vivos (solana reiniciado a las 07:2x con la puerta ALT, binance, coinbase, insider, copytrade, dashboard, st_shadow); logs frescos; 0 errores en solana; sin reinicios en esta revisión.
- Equity: Solana REAL 48,33 $ (sin posiciones), Coinbase 3,25 $ (SOL-USD abierta, día +0,38 %), Binance paper 998,80 (sin operaciones).
- Sin operaciones nuevas. Puerta ALT activa y funcionando, pero SIS (único candidato que pasa filtros) se salta en cada scan por "Solana Tracker neutral": el presupuesto diario de ST ya está agotado (data/st_budget.json n=400/400 del 01-nov, consumido antes del arreglo de las 07:2x). Resultado: la puerta ALT no puede disparar hasta que el contador se reinicie a medianoche (hora Madrid). SIS además en sombra SMART early_exit (18 vendedores tempranos), así que hoy no se pierde una buena entrada.
- Sin cambios (subir el tope de ST no se hace sin Àngel). Informado a Àngel. Próxima vez: tras las 00:00 comprobar que ST da veredictos reales y si la puerta ALT dispara.

## 2026-11-01 08:30 (Madrid) — mejora continua del modelo (rutina 2 h)
- Autocrítica:
  1) Operativo (error principal): siguen 0 compras/cierres REALES desde 31-oct 01:19 (~31 h). La puerta ALT (07:2x) no puede disparar hoy: SIS pasa filtros pero Solana Tracker da "neutral" porque el presupuesto diario (400) se agotó antes del arreglo; además SMART en sombra marca SIS early_exit (7 vendedores tempranos a las 08:24), así que no se pierde una buena entrada.
  2) Fuente de datos: Solana Tracker solo cubre 122 de 521 filas del dataset (23 %), y casi todo reciente; el filtro aún no tiene historia suficiente para aprender de él.
  3) Dataset honesto: 521 filas (+29), 109 mints, media −9,3 %/op, PF 0,16. Universo coherente con vetos: 430 filas, 83 mints, media −3,45 %, PF 0,30 (algo peor que 06:30).
  4) Aviso crítico sobre la puerta ALT: en las filas con datos ST, incluso "pass" de ST tiene media −3,97 % y PF 0,28 (n=24, 10 mints); top10 <25 % similar (−3,99 %, PF 0,26). Mejor que el resto (−5 %, PF 0,11) pero sigue negativo. No hay filas históricas que cumplan a la vez score ≥50 y coste ≤1,5 %, así que la puerta ALT opera sin respaldo histórico; vigilar sus primeros cierres de cerca.
- Mejora probada (la pendiente de 06:30): features de flujo del registro st_shadow (compras dominantes, snipers/bundlers bajos, top10 bajo, veredicto pass, score ST alto), unidas por mint al registro ST más cercano (≤2 h antes). K∈{5,10}, DAMP 0,3, cortes temporales con purga 50/60/70/80 %.
- Resultado OOS: modelo actual 0 operaciones en todos los cortes; candidato también 0 (EV máx. en test −2,99 % a +0,12 %, nunca sobre la puerta). Sin muestras para comparar.
- Decisión: NO se promueve. Se mantiene el modelo actual (sombra). Sin cambios en código, config, tamaño, stops ni vetos; sin reinicio (0 posiciones, sin ventas en curso); sin backup (nada reemplazado). Script: research/brain_cycle_0830.py.
- Próxima vez: repetir flujo ST cuando haya más cobertura (la cola de st_shadow crece ~120/día); revisar los primeros cierres de la puerta ALT en cuanto los haya.

## 2026-11-01 08:58 — Revisión CFO horaria — Grok
- Salud: todos los procesos vivos (solana, binance, coinbase, insider, copytrade, dashboard, st_shadow); logs frescos; 0 errores; sin reinicios.
- Equity: Solana REAL 48,26 $ (sin posiciones), Coinbase 3,25 $ (SOL-USD abierta, día +0,22 %), Binance paper 998,80 (sin operaciones).
- Sin operaciones nuevas. ALT gate sigue saltando SIS por ST neutral (presupuesto 400/400 agotado, se reinicia a medianoche); SIS además SMART early_exit. DESSA bloqueado (creador en lista negra), correcto.
- Sin cambios; sin informe (ya informado a las 07:58). Próxima vez: tras 00:00 comprobar veredictos ST reales y disparo de la puerta ALT.

## 2026-11-01 10:03 — Revisión CFO horaria — Grok
- Salud: todos los procesos vivos (solana, binance, coinbase, insider, copytrade, dashboard, st_shadow); logs frescos; 0 errores hoy; sin reinicios.
- Equity: Solana REAL 48,42 $ (sin posiciones), Coinbase 3,26 $ (SOL-USD abierta, día +0,57 %), Binance paper 998,80 (sin operaciones, régimen range).
- Sin operaciones nuevas. SIS y PAWCAT siguen con ST neutral (presupuesto agotado hasta medianoche); PAWCAT bloqueado por wash_traders (correcto). 0 candidatos pasan todos los filtros en los scans de la última hora.
- Sin cambios; sin informe (nada nuevo). Próxima vez: tras 00:00 comprobar veredictos ST reales y disparo de la puerta ALT.

## 2026-11-01 10:30 (Madrid) — mejora continua del modelo (rutina 2 h)
- Autocrítica:
  1) Operativo (error principal, sin cambios): 0 compras/cierres REALES desde 31-oct 01:19 (~33 h) y 0 paper nuevos. La puerta ALT no puede disparar: Solana Tracker sigue en 400/400 (agotado hasta medianoche) y los 116 chequeos ST de 08:00–10:30 dieron "neutral". 0 candidatos pasan todos los filtros en los últimos scans.
  2) Dataset honesto: 533 filas (+12), 110 mints, media −9,07 %/op, PF 0,16. Universo coherente con vetos: 442 filas, 84 mints, media −3,33 %, PF 0,32.
  3) Hallazgo: coste de ida y vuelta bajo (≤1,5 %) es el mejor subgrupo (n=111, 37 mints, −2,15 %, PF 0,46) y score ≥50 aún mejor (n=14, 8 mints, −1,16 %, PF 0,74), pero ambos negativos y no hay ninguna fila histórica con las dos cosas a la vez (justo la condición de la puerta ALT): la ALT sigue sin respaldo histórico.
- Mejora probada: features de coste (rt ≤1,5 %, 1,5–2,5 %) y score ≥50 + hiperparámetros con menos encogimiento (K∈{3,5,10}, DAMP∈{0,1, 0,3}); cortes temporales con purga 50/60/70/80 %.
- Resultado OOS: modelo actual 0 operaciones en todos los cortes; candidatos también 0 (EV máx. en test −3,3 % a +2,0 %, nunca sobre la puerta ≥ max(1 %, 3×coste)). Sin muestras para comparar.
- Decisión: NO se promueve. Se mantiene el modelo actual (sombra). Sin cambios en código, config, tamaño, stops ni vetos; sin reinicio (0 posiciones, sin ventas en curso); sin backup (nada reemplazado). Script: research/brain_cycle_1030.py.
- Próxima vez: tras el reinicio del presupuesto ST (00:00) revisar veredictos reales y primeros cierres ALT; repetir flujo ST con más cobertura.

## 2026-11-01 11:02 — Revisión CFO horaria — Grok
- Salud: todos los procesos vivos (solana, binance, coinbase, insider, copytrade, dashboard, st_shadow); logs frescos; 0 errores hoy; sin reinicios.
- Equity: Solana REAL 48,27 $ (sin posiciones), Coinbase 3,25 $ (SOL-USD abierta, día +0,11 %), Binance paper 998,80 (sin operaciones, régimen range).
- Sin operaciones nuevas. Presupuesto Solana Tracker sigue 400/400 (agotado hasta medianoche), la puerta ALT no puede disparar.
- Sin cambios; sin informe (nada nuevo). Próxima vez: tras 00:00 comprobar veredictos ST reales y disparo de la puerta ALT.

## 2026-11-01 11:56 — Revisión CFO horaria — Grok
- Salud: procesos vivos (solana, binance, coinbase + servicios auxiliares); logs frescos; 0 errores hoy; sin reinicios.
- Equity: Solana REAL 48,18 $ (sin posiciones), Coinbase 3,24 $ (SOL-USD abierta, día +0,06 %), Binance paper 998,80 (sin operaciones, régimen range).
- Sin operaciones nuevas; 0 candidatos pasan todos los filtros en los scans recientes. Presupuesto Solana Tracker 400/400 (agotado hasta medianoche), la puerta ALT no puede disparar.
- Sin cambios; sin informe (nada nuevo). Próxima vez: tras 00:00 comprobar veredictos ST reales y disparo de la puerta ALT.

- 2026-11-01 12:11: Àngel ordered alt_gate_min_score 50 -> 45 (hot reload, backup config.json.bak_alt45). Still requires real ST verdict, all vetoes, rt cost <=1.5%, size 4%.

## 2026-11-01 12:30 (Madrid) — mejora continua del modelo (rutina 2 h)
- Autocrítica:
  1) Operativo (error principal, sin cambios): 0 compras/cierres REALES desde 31-oct 01:19 (~35 h) y 0 paper nuevos. Solana Tracker sigue 400/400 (agotado hasta medianoche), así que la puerta ALT (ahora score ≥45 desde 12:11) no puede disparar. Últimos scans: 0 candidatos pasan todos los filtros.
  2) Dataset honesto: 541 filas (+8), 111 mints, media −9,08 %/op, PF 0,15. Universo coherente con vetos: 450 filas, 85 mints, media −3,45 %, PF 0,30.
  3) Aviso sobre el cambio a score ≥45: score ≥45 histórico n=41 (13 mints) media −4,30 %, PF 0,21 (peor que ≥50: −1,16 %, PF 0,74). Score ≥45 + coste ≤1,5 % (condición ALT): solo n=2, −4,28 %, PF 0. Bajar a 45 añade entradas históricamente peores; vigilar los primeros cierres ALT.
- Mejora probada: momento de salida — reetiquetar con tenencia máxima corta (cierre de la primera vela ≥15/30/60 min tras la entrada, si es antes de la salida original), K∈{5,10}, DAMP 0,3, cortes temporales con purga 50/60/70/80 %.
  - En el universo completo las salidas cortas pierden menos (15 min: −2,65 %, PF 0,24; 30 min: −2,92 %; 60 min: −3,18 %) frente a −3,45 % actual, pero siguen negativas.
- Resultado OOS: modelo actual 0 operaciones en todos los cortes; candidatos también 0 (EV máx. en test −0,22 % a −2,64 %, nunca sobre la puerta). Sin muestras para comparar.
- Decisión: NO se promueve. Se mantiene el modelo actual (sombra). Sin cambios en código, config, tamaño, stops ni vetos; sin reinicio (0 posiciones, sin ventas en curso); sin backup. Script: research/brain_cycle_1230.py.
- Próxima vez: tras 00:00 revisar veredictos ST reales y primeros cierres ALT; repetir flujo ST con más cobertura; si la ALT llega a operar, evaluar salida por tiempo ~15 min como regla de salida candidata.

## 2026-11-01 17:30 (Madrid) — Panel v2, Director con autoridad acotada, cerebro v2 y rent de las ATAs (Claude, sesión autónoma; Àngel: "haz un dashboard en vivo profesional con todo real" y "mejora el cerebro y las decisiones, que tenga autoridad propia para ganar dinero")
- **Diagnóstico con los 64 cierres reales del 30-oct:** tamaño medio 2,94 $; win 33 %, +1,72 % / −3,51 % → esperanza −1,8 % por operación; PnL −1,65 $ pero el patrimonio cayó −4,73 $: los ~3 $ restantes son el rent de 24 cuentas de token (0,00204 SOL cada una) más comisiones. Con posiciones de 3 $ el coste fijo es ~6 % por operación, mayor que cualquier ventaja medida (cerebro OOS +1,8 %). Primero se elimina ese lastre; después se da autoridad al cerebro para operar poco y bien.
- **Rent de ATAs:** `live_sol.close_empty_atas` (solo saldo 0; simula antes de enviar; ≤12 por tx; lote fallido → una a una) + `tools/close_atas.py` (dry run por defecto) + `memebot.ata_sweep` tras cada venta completa en real (3 intentos, registro en research/ata_close.jsonl). Pendiente de Àngel: ejecutar `--yes` para recuperar ~4,7 $.
- **Director (`director.py`, spec docs/superpowers/specs/2026-10-31-director-brain-design.md):** cada hora mide la evidencia por jugada (real + papel con peso 0,5, PF y esperanza con shrinkage), el coste fijo (comisiones + rent × probabilidad de no poder cerrar la cuenta), y escribe `director_state.json`: jugadas on/off (pump nunca pasa a real por sí solo), score mínimo efectivo (bucket con mejor esperanza, nunca < config), EV mínimo = máx(1 %, 3 × coste fijo/posición), tamaño objetivo (menor de los topes; 0 $ si el coste fijo supera el 2 % de la posición), horas permitidas (esperanza OOS ≥ 0 con n ≥ 10), perfil de salida por replay (nunca más laxo que config, mínimo 40 trayectorias), tope diario (presupuesto de pérdida / pérdida al stop). `apply_director` solo endurece: test con 500 estados aleatorios. Estado ausente/corrupto/obsoleto > 3 h = config base. **Sombra las primeras 24 h.** Registro en `director_log.jsonl`; `python3 director.py --report`. Interruptor `director_enabled: false`.
- **Cerebro v2:** regresión logística (numpy, L2, sin sklearn) junto al modelo Beta; se despliega solo si gana en OOS en retorno de la política Y en Brier; probabilidad pesimista (p − 1 error estándar por tamaño de muestra); EV neto del coste fijo del Director; calibración por cubos en brain_state.json. Las filas con `director_gate` siguen entrenando (no son vetos). Recordatorio del 30-oct: con 52 muestras ningún modelo batía al score; ahora hay 715 etiquetadas y la elección es automática y reversible.
- **Panel v2 (`/`, DASHBOARD.md):** `dash_data.build_overview` lee solo ficheros de la máquina (sin red), cada bloque con ts/edad/`fresh`; lo que falta se muestra como "sin datos". Gráficos SVG sin CDN, controles con confirmación (KILL exige escribir KILL). Verificado con Playwright a 1280/390 px: 0 errores de consola, sin desbordamiento. Revisión de seguridad hecha a mano (los agentes revisores no pudieron correr por límite de cuota): rutas bajo el guard de sesión, CSRF en POST, todo string de la API escapado, ningún secreto leído.
- Tests: 97. Lo que NO se ha podido hacer desde aquí: validar el Director y el cerebro v2 con `candidates_solana.jsonl` y `ohlcv_cache.json` reales (no están en el repo); por eso el Director arranca en sombra y Grok debe pegar `director.py --dry-run` antes de que mande.

## 2026-11-01 19:00 (Madrid) — Bot autosuficiente: operador automático en código (Àngel: "crea tú el bot, no usaremos el de Grok, todo automático y autosuficiente")
- Decisión de diseño: no se reescribe el ejecutor (Jupiter, vetos, trail) que ya ha operado dinero real; se sustituye al **operador** (la revisión horaria que hacía una persona/IA) por código: `operador.py` (nombre en castellano porque `operator` es un módulo de la librería estándar).
- Cada hora (`run_forever.sh`): revisión de salud por proceso (caído/colgado/STOP/KILL), SOL insuficiente, status obsoleto, cerca del stop diario, escaneo lento o ausente, posiciones atascadas, errores en logs, cerebro sin reentrenar, Director ausente/obsoleto/sombra, Coinversa degradado, CEX sin efectivo, PF real 30 d < 1. Resumen con el mismo formato que las revisiones anteriores (Salud / Equity / Escaneo / Director / Copytrade / Acciones) añadido a este fichero. `operator_state.json` para el panel; `alerts.jsonl` con deduplicación de 6 h y gancho `ALERT_CMD` (webhook/Telegram).
- Acciones automáticas, todas reversibles y acotadas: cierre de cuentas de token vacías (solo real, con wallet, máx. cada 6 h, nunca un mint en cartera), SIGTERM a un proceso vivo pero mudo > 10 min (una vez por hora, nunca con STOP_<ex>), recálculo del Director si falta o > 2 h, recorte de logs > 50 MB. Nunca: relajar vetos/tamaños/stops, cambiar papel↔real, pump real, tocar config.json, mover fondos.
- Informe diario (desde las 08:00): 24 h por pata, rent recuperado, cambios del Director, cerebro, y la lista de decisiones que siguen siendo de Àngel (memebot a papel si PF < 1; Hyperliquid real en Keel; Director al mando).
- Instalación en un comando (`install.sh`: dependencias, keys.env vacío, contraseña del panel, tests) y parada ordenada (`stop.sh`); `requirements.txt`. Guía de operación para Àngel: `OPERACION.md`. `HANDOFF_GROK.md` queda superado.
- Tests: 105 (operador: hallazgos, acciones acotadas, dry run sin escrituras, DECISIONS/estado/alertas, informe diario).

## 2026-11-01 22:10 (Madrid) — Traspaso de Grok (21:30) recibido por chat e incorporado (Claude)
- Estado de la máquina de Grok a las 21:30: Solana REAL ~47,4 $ en efectivo, 0 posiciones, fichero STOP (bots parados 21:18), cerebro en sombra (554 filas; baseline OOS ≈ −7,3 %), rutinas de Grok sin cupo. El wallet se rota a uno nuevo que solo existe en el PC de Àngel (tools/wallet_rotar.py).
- Decisiones de Àngel del 31-oct/1-nov que esta versión no tenía y que se adoptan (config.json): `max_buy_slip_bps` 550 y `max_buy_impact_pct` 5,5 (tope configurable en `_buy_live`; antes 1 % fijo), `pump_paper` false, veto "ya bombeada" (`max_entry_h1_pct` 50 → `already_pumped`), puerta ALT sin modelo: tamaño `alt_gate_size_pct` 4 % y round-trip ≤ `alt_gate_max_rt_cost_pct` 1,5 % (`alt_rt_cost`), `min_score` 50 (sus propios datos: score ≥ 50 → −1,16 %/PF 0,74 frente a ≥ 45 → −4,30 %/PF 0,21; solo endurece).
- Lo que la versión de Grok tiene y esta NO (el código solo existe en su máquina): filtro Solana Tracker (veredicto ST en la puerta ALT, cupo 400/día, daemon sombra), señal X (buzz humano vs shill), veto marca/stablecoin-copy. Pendiente: si Àngel consigue un zip de esa carpeta (sin keys.env ni wallet), se fusionan.
- Sus datos confirman el diagnóstico: media global −9 %/op (PF 0,15), con vetos −3,4 % (PF 0,30). La mejora con más valor esperado sigue siendo la jugada de tendencia sobre tokens líquidos.
- Tests: 115.

## 2026-11-01 22:50 (Madrid) — Jugada de tendencia sobre tokens líquidos de Solana: construida en papel; la prueba en Keel sale negativa (Claude)
- `trend_spot.py`: la regla validada (SuperTrend 10/3 + Bollinger 20/2 > 0,5 + ATR7/21 > 0,85, diaria, solo largos) sobre los tokens de Solana con más volumen y liquidez (GeckoTerminal), evaluación tras el cierre UTC, marcado cada 15 min, registro `trades_solana_trend_paper.csv`, estado `state/trend_status.json`, tarjeta "Tendencia" en el panel, jugada `trend` en el Director (papel; off si PF < 1 con n ≥ 15; nunca a real sin `trend_live` del dueño). 7 tests.
- Comprobación previa en Keel (misma regla, cesta manual de 31 perps del ecosistema Solana, top-5 causal semanal por volumen): ventana completa Sharpe −0,03 / −36 % / DD −72 %; fuera de muestra Sharpe −0,86 / −29 % / PF 0,63. **La ventaja de la regla está en los grandes (BTC/ETH/SOL…), no en los tokens de Solana.** Conclusión honesta: no es la mejora que buscábamos; se deja en papel como evidencia hacia delante y no se le dedica más capital ni más trabajo salvo que la evidencia en papel diga lo contrario.
- Lo que sí sostiene la evidencia: pata Hyperliquid causal (OOS 1,15) en paper en Keel; memebot con costes fijos eliminados (rent recuperado: 28 cuentas, 0,042 SOL) y Director; agente insider en tiempo real.
- Tests: 123.

## 2026-11-01 22:51 (Madrid) — "¿Ya puede operar para ganar dinero?": auditoría de la ruta real con 5 revisores independientes (Claude)
- Hecho verificado (2 de 3 refutadores no lo refutan; el tercero solo señala un caso de caché <1 h): en REAL, con el cerebro en sombra (necesita 85 filas etiquetadas, 10 mints y 3 reajustes seguidos), la ÚNICA puerta de compra es la ALT (memebot.py ~l.1113-1117) y exige veredicto no neutral de Solana Tracker. Sin SOLANATRACKER_API_KEY en keys.env el bot real escanea, aprende y NO compra nunca ("ALT gate ... skipped: Solana Tracker verdict neutral/missing"). La clave deja de ser opcional: sin ella no hay operaciones reales.
- Fallo nuevo corregido: arranque con --live sin state_solana_live.json ponía day_start = starting_equity (1000 $) frente a un wallet de ~96 $ → el stop diario del 5 % saltaba el primer día contra una base que nunca existió (KILL SWITCH falso hasta la medianoche). `Meme.rebase_day_start()`: tras el primer reconcile la base del día es el patrimonio real del wallet; repara también un estado guardado con esa base ficticia (day_start == starting_equity y wallet < mitad) y levanta ese halt falso si no hay posiciones. Nunca toca una base real ni un halt real. Tests: tests/test_day_start_rebase.py (5).
- Presupuesto Solana Tracker: el plan gratuito es ~10k/mes ≈ 330/día; el tope 400/día agotaba el mes antes de tiempo y el 1-nov dio 116/116 neutrales. Nuevo: ST_DAILY_CAP 300 (bot ≥ 240) y ST_DAEMON_CAP 60. Solo baja el gasto; no relaja nada.
- Expectativa con el libro REAL (data/trades_solana_live.csv, 30-31 oct, trades de Grok antes de los vetos nuevos): 63 cierres, acierto 33 %, media −1,43 %/op, PF 0,44; coste fijo 0,004 $/op (irrelevante): el problema es el borde de entrada/salida, no los costes. Conclusión honesta: la evidencia real NO sostiene aún "ganar dinero"; el bot opera con 4 % por operación (~4 $) para generar evidencia bajo los filtros nuevos, y el Director apagará la jugada scanner si con n_eff ≥ 15 el PF sigue < 1 (hoy n_eff 12, PF 0,34). Eso es lo que debe hacer.
- Otras puertas que pueden bloquear el 100 % (no son fallos): ventanas horarias del Director al salir de la sombra (dataset negativo → casi todas las horas cerradas); stop diario medido en USD con el patrimonio en SOL (un día de SOL −5 % para las compras hasta medianoche); caída de RugCheck (fail-closed). Se dejan como están.
- Tests: 144.

## 2026-11-02 10:29 (Madrid) — Insiders fiables (1/2): ranking de fiabilidad y seguidor en vivo por ranking (Claude)
- Diagnóstico (mapa con 3 lectores): el motor de insiders medía fiabilidad con muestras diminutas y prior plano (2121 de 2196 "good" eran exactamente 2 aciertos y 0 fallos; 820 de 1560 "elite" tenían ≤ 4 lanzamientos), sin decaimiento, con un filtro de bots tan laxo que las 5 wallets mejor puntuadas estaban en el 32-39 % de TODOS los lanzamientos minados (francotiradores automáticos, no insiders), y sin usar el PnL real. La convergencia contaba direcciones, así que un actor con tres wallets autofinanciadas disparaba "elite ≥ 3".
- `insider_rank.py` (nuevo, puro + build): por wallet, aciertos/fallos decaídos por edad del lanzamiento (vida media 7 d), prior Beta centrado en la tasa base minada (fuerza 10), fiabilidad = percentil 20 del posterior (cota inferior), participación (bot si > 10 % de los lanzamientos o francotirador de slot 0-1 con > 3 %), exclusión de desarrolladores y granjas, colapso por clúster de financiación (solo la mejor wallet del clúster puede ser elite/good), veto por pista en vivo a 1 h y por PnL real (Solana Tracker /pnl, tope propio ST_INSIDER_CAP 40/día bajo el dueño "insider"; el bot conserva ≥ 200/día: los demás dueños paran en DAILY_CAP − BOT_RESERVE). Umbrales relativos a la tasa base: elite exige cota inferior ≥ base + 2 pp (con base 0,6 son ~7-8 aciertos recientes y ≤ 1 fallo), good ≥ base − 5 pp; dos aciertos sueltos son "watch". Subir de nivel: un escalón por construcción (saltos mayores quedan pendientes hasta la siguiente); bajar: inmediato. Registro de cambios en research/insider_rank_log.jsonl. Descubrimiento vía ST (/first-buyers de ganadores recientes, /top-traders) solo amplía el universo que mira el minero; nunca da nivel sin confirmación on-chain. Formas de respuesta de ST no verificables desde aquí (sin red): parsers defensivos, None ante cualquier cosa inesperada.
- `insider.py` / `insider_ws.py`: el seguidor en vivo y el WebSocket siguen el orden del ranking (elite/good no bot y presentes en insider_wallets.json: el ranking estrecha, nunca amplía); 100 plazas fijas + 20 rotatorias para que las wallets de baja frecuencia acumulen pista; convergencia por clúster (conv.n_clusters, elite = clústeres elite distintos; alerta cluster_buy exige ≥ 2 clústeres); sells_n_by_mint con vendedores distintos; estado en vivo persistente (insider_live_state.json) para que un reinicio no borre 30 min de convergencia; rpc_err_n y ws_health en el estado. Sin ranking fresco, comportamiento anterior. Umbrales que lee el memebot (elite ≥ 3, etc.) sin tocar.
- Efecto esperado: menos wallets seguidas y más fiables; el disparador "insider_elite_group" se vuelve más raro y más limpio. En una instalación nueva el ranking está vacío hasta que el minero acumula evidencia propia (horas-días): preferible a seguir una lista ruidosa.
- Tests: 169.

## 2026-11-02 11:32 (Madrid) — Insiders fiables (2/2), cerebro v3 y contexto de mercado: construido en paralelo por 7 agentes en worktrees, fusionado y probado (Claude)
- Petición de Àngel: "que aprenda cada vez más, siga a las mejores wallets de insiders más fiables y tenga mucha más información y contexto". Nada de esto sube tamaños, afloja stops ni vetos: solo añade información y endurece.
- `context.py` (nuevo; `run_forever.sh` lo lanza cada hora): instantánea horaria en data/context_now.json y data/context.jsonl: SOL y BTC (retornos 1 h/4 h/24 h, volatilidad 24 h, régimen BTC con antigüedad), noticias (riesgo-off, F&G, sentimiento, fuentes vivas), mercado meme (nuevos pools y graduaciones por hora, volumen, "calor" frente a la mediana de 7 días de la misma hora), amplitud de la tendencia (trend_spot), Hyperliquid (hl_risk) y salud de los módulos. Todo lo que no se puede calcular queda en null y en la lista `stale`; nada falla abierto. Lo consumen: memebot (una lectura por ciclo; btc_on solo puede pasar a False y riesgo-off solo a True: solo endurece; cada candidato queda sellado con su `ctx`), cerebro (rasgos de contexto), Director (puerta de régimen), operador (línea "Mercado" y avisos context_stale / news_riskoff_6h / market_dead) y panel (tarjeta "Contexto de mercado").
- `brain.py` v3: archivo de etiquetas data/labels_solana.jsonl (una etiqueta por candidato, nunca se re-etiqueta; antes el conjunto se reconstruía cada hora sobre 7 días y oscilaba en ~550 filas, ahora crece), pesos con vida media de 10 días, tope por mint (6/día, 30 en total), etiquetado con la configuración BASE (cierra el bucle de realimentación con el Director; cfg_hash por fila), bloque de 49 rasgos continuos (liquidez, vol/liq, h1, m5, edad, coste medido, top10, holders, insiders, ratio compras, hora, origen, Solana Tracker, contexto) solo para el logit y el nuevo modelo de retorno ridge (cota inferior por n_eff local), lambda elegida en un corte interno {2,5,10,20}, validación en 3 cortes temporales por episodio de mint con embargo de 3 h, voto solo con ≥ 25 filas nuevas, cambio de modelo tras 2 victorias seguidas. La puerta de activación NO se afloja: batir a la regla base en todos los cortes, tres reajustes seguidos. Expectativa honesta con los datos actuales (PF 0,15-0,44): sin voto y modelo beta durante semanas; el valor está en que ahora acumula evidencia que no se olvida.
- `memebot.py`: filas de candidatos con rid, score_brain (la puntuación que vio el cerebro, no la ajustada después), veto_class (duro/política/suave), ctx, st_f (rasgos de Solana Tracker), smart_flags, rt_src, hour_utc, vol_h1, whale_*/bots a null cuando no se consultaron; learn con cfg base; Director con trayectorias (rejilla de salida real) y contexto; puerta del Director en hora UTC; status con contexto y extras del cerebro. Arranque: siembra la base de "calor" desde el histórico de contexto (brain.seed_heat).
- `director.py` v2: puerta de régimen desde el contexto registrado (una clave entra en la puerta con ≥ 10 filas conocidas; un valor con ≥ 10 filas y retorno medio negativo se cierra; "na" nunca se permite); con puerta no vacía y sin contexto fresco (< 2 h) la entrada se bloquea (fail-closed); horas en UTC; estado v2 con carga compatible; informe con sección "Régimen". Consecuencia esperada con el dataset histórico negativo: la puerta puede cerrar casi todo al salir de la sombra, igual que las ventanas horarias; es lo que la evidencia dice.
- Panel/operador: tarjeta de contexto con sparkline de SOL, tabla de las 10 wallets más fiables con su evidencia (nivel, fiabilidad, aciertos/fallos, participación, bot, pista en vivo, PnL), campos del cerebro v3 (modelo, lambda, archivo, cortes, calibración) y del Director (puerta de régimen y tabla), línea "- Mercado:" en el diario. Capturas Playwright 1280/390 px sin desbordes.
- Integración posterior a la fusión (maestro): expectativas de 3 tests ajustadas al estado fusionado (Director acepta ctx; context.py presente), hook brain.seed_heat añadido (el memebot lo buscaba por nombre), vol_h1 en la fila (agregado de volumen del contexto), fixture v3 solo en la vista previa.
- Tests: 259. Pendiente en la máquina de Àngel: primera ejecución real de `python3 context.py --once` (formas de Binance/GeckoTerminal no verificables desde la sesión) y de `python3 insider_rank.py --top 20`.

## 2026-11-02 15:24 (Madrid) — Revisión adversarial de riesgo (lente de invariantes) y correcciones (Claude)
- Alto, corregido: el cerebro v3 mantenía en el universo de entrenamiento filas vetadas "por política" (honeypot/coste medido, vetos de Solana Tracker, ya subido, noticias, insiders, momentum), que la puerta real nunca opera; la comparación "bate a la base" corría sobre un universo más laxo y podía activar el modelo y saltarse la exigencia del veredicto ST de la puerta ALT. Regla v2 restaurada: solo score*/brain_ev*/director*/no_sellability_check mantienen la fila; veto_class queda como información. Test de regresión.
- Medio, corregido: la puerta de régimen del Director estaba muerta (las filas de entrenamiento perdían `ctx`); ahora llevan ctx y hour_utc y el test comprueba que un régimen con 12 filas y media −5 % se cierra.
- Medio, corregido: el veto por PnL y el descubrimiento de Solana Tracker nunca corrían (insider.build no pasaba el módulo); ahora sí, bajo el dueño "insider".
- Medio, corregido: la siembra del "calor" desde el contexto mezclaba una medida distinta (volumen de la última hora, solo página 1) con la del bot (páginas 1+2 sin filtro) y podía dar "hot" falso tras un reinicio (umbral −5, tamaño ×1,0): eliminada. El bot vuelve a necesitar 10 muestras propias antes de declarar calor.
- Bajo, corregido: reserva explícita del cupo de Solana Tracker para el bot (BOT_RESERVE 200/día; daemon e insider paran antes). Bajo, corregido: director_cycle reconstruía el dataset con la configuración endurecida y sin cfg_base; ahora usa la base.
- Pendientes de las otras tres lentes (integración, E/S y secretos, estadística): se aplicarán al terminar su verificación.
- Tests: 260.

## 2026-11-02 16:23 (Madrid) — Revisión adversarial completa (4 lentes, 15 agentes): 7 hallazgos confirmados, todos corregidos (Claude)
- Alto, corregido (estadística): desfase entrenamiento/servicio del cerebro v3: decide() puntuaba un vector sin contexto, sin rasgos de Solana Tracker ni coste medido (se adjuntaban después), mientras el archivo y la validación usaban la fila completa. Ahora el sello de contexto se hace ANTES de decidir y decide() guarda el vector exacto que puntuó (`x_dec`), que es el que se archiva: lo validado fuera de muestra es lo que opera. Test de regresión.
- Medio, corregido: la puerta "cerebro activo" comparaba brain_min_score con la puntuación ya subida por bonos X/ST (hasta +9 puntos no validados); ahora compara score_brain. Test.
- Medio, corregido: el modelo ridge se ajustaba con retornos recortados en −30 %, ignorando la cola de rugs en su EV; ahora conserva toda la bajada.
- Medio→bajo, corregido: ventanas horarias y puerta de régimen abrían los valores con < 10 filas aunque el conjunto fuera negativo (solo quedaban operables los regímenes menos medidos); ahora un valor poco medido hereda el veredicto agregado (abierto solo si la media agregada ≥ 0). Tests.
- Medio, corregido: el panel no mostraba archivo/cortes/lambda con el bot vivo (status sin esas claves; lambda es un dict logit/ridge). Ahora el status las lleva y el panel las lee.
- Medio, corregido (E/S y secretos): insider_ws_status.json guardaba la URL completa del WebSocket (puede llevar clave de RPC) y no estaba en .gitignore; ahora solo el host, el error solo por tipo, y .gitignore cubre insider_ws_status.json, insider_ws_queue.jsonl y data/st_cache.json.
- Medio→bajo, corregido (rendimiento): local_n era O(n) en Python por predicción (92 s por aprendizaje a 12k filas); ahora popcount vectorizado con numpy; filas de más de 60 días fuera del entrenamiento; nunca dos aprendizajes a la vez; ficheros temporales con nombre único.
- De propina, descubierto por el test nuevo: apply_director convertía una lista de ventanas VACÍA en "todas las horas" (`or range(24)`), es decir, fallaba abierto justo cuando la evidencia cerraba todo; corregido (lista vacía = ninguna hora).
- Tests: 266.

## 2026-11-02 16:33 (Madrid) — Verificación de las correcciones y diagnóstico en una pantalla (Claude)
- Verificación independiente de la puerta "cerebro activo": la corrección era correcta para los bonos, pero el ajuste de X puede ser NEGATIVO (−3 por "shill") y quedaba ignorado: hasta 3 puntos más laxa. Ahora la puerta exige que superen el mínimo tanto la puntuación validada (score_brain) como la ajustada: `min(sc, score_brain) >= brain_min_score`. Solo endurece. El motivo de rechazo en esa rama ya no se etiqueta siempre como "brain_ev<=0" (dice score<45 cuando es el mínimo).
- Las otras seis verificaciones (los agentes se quedaron sin cupo) las hice a mano: archivo con el vector exacto de decide() (logc escribe la fila completa con x_dec; las filas sin señales se saltan igual en decide y en el archivo), RET_CLIP solo afecta al objetivo del ridge y al MSE, ventanas/régimen con veredicto agregado ('na' sigue sin permitirse), panel con archive_n/folds/lambda desde el status, ficheros del WebSocket ignorados por git. Dos mejoras de paso: la caché del popcount de local_n se comprueba por identidad del objeto (un id() puede reutilizarse tras liberarse la lista) y las líneas de log del panel ya no muestran rutas ni parámetros de URL (una URL de RPC en un error puede llevar la clave). Tests.
- `tools/diagnostico.py` (nuevo, solo lectura): una pantalla que responde "¿está en real, ha operado y, si no, por qué?": procesos, modo, patrimonio y wallet (acortado), stop diario/KILL/STOP, operaciones reales 24 h y totales con PnL, embudo (escaneos, aptos, sin veredicto ST, bloqueos por motivo, Director), cupo de Solana Tracker, Director, cerebro, contexto, insiders, huecos del log (PC suspendido) y errores (URLs y claves enmascaradas). Nunca abre solana_wallet.json ni imprime valores de keys.env (test que lo garantiza). El instalador termina mostrándolo y ya no imprime la contraseña del panel.
- Corrección de un mensaje engañoso del instalador: Solana pasa a REAL sola en cuanto solana_wallet.json tiene ≥ 0,05 SOL (go_live), aunque config diga paper; para impedirlo, KILL_solana.
- Tests: 276.
