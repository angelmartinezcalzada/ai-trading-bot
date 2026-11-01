# Traspaso a Grok — bot de trading, versión MVP 31-oct-2026 (revisada 1-nov-2026)

> **Superado el 1-nov-2026:** Àngel decidió no usar un operador externo. El bot se opera solo (`operador.py`); la guía vigente es
> `OPERACION.md`. Este documento se conserva como registro de lo que incluía la versión del 31-oct.

Este paquete es la versión mejorada del bot que Àngel compartió con Claude (zip `ai-trading-bot-share.zip` + `PROYECTO_PARA_CLAUDE.md`).
Fuente de verdad: rama **`claude/trading-bot-mvp`** del repo `angelmartinezcalzada/Angel-proyectos` (carpeta `ai-trading-bot/`).
El razonamiento completo está en `DECISIONS.md` (entradas del 31-oct 20:05, 20:40, 21:15, 21:45 y **1-nov 17:30**) y en
`../docs/superpowers/specs/2026-10-31-trading-bot-mvp-design.md` + `2026-10-31-director-brain-design.md` (Director) + `DASHBOARD.md` (panel).

## 1. Qué cambia, en cinco frases
1. **Pata nueva en Hyperliquid, en paper en Keel.** Una regla de tendencia (SuperTrend+Bollinger, 1d, long-only) sobre el top-15 de
   perps por volumen, re-elegido cada semana sin mirar el futuro. Evidencia honesta: fuera de muestra Sharpe 1,15 / +43,5 % / DD −30 %;
   ventana completa 2024-08→2026-10 Sharpe 0,76 / +91 % / **DD −58 %**. Es una ventaja **pequeña** medida sin trampas, no "muy buen
   rendimiento": los Sharpe 1,9-2,0 que circularon durante la sesión venían de un universo elegido con hindsight (ver `hl_leg/README.md`).
2. **El memebot de Solana sigue igual de estricto** (vetos, tamaños y stops intactos) con 18 correcciones verificadas por revisión
   adversarial: escaneos de 650-780 s → ≤150 s, puerta EV en real medida con el fill esperado, kill switch que aplana de verdad,
   write-off de posiciones muertas solo con evidencia, cerebro evaluado sin fugas, salidas urgentes con prioridad alta, etc.
3. **Dinero seguro primero: el rent de las cuentas de token.** Cada compra de un mint nuevo bloquea 0,00204 SOL (≈0,19 $) de rent;
   con posiciones de 3 $ eso es un 6 % por operación y explica ~3 $ de los 4,7 $ perdidos el 30-oct. `tools/close_atas.py` recupera el
   rent de las cuentas vacías (≈24 → ~4,7 $) y el memebot cierra la cuenta tras cada venta completa (`ata_sweep`).
4. **Director (`director.py`): el bot decide por sí mismo dentro de los topes.** Cada hora mide la evidencia (real + papel por jugada,
   coste fijo, dataset etiquetado) y escribe `director_state.json`: jugadas encendidas/apagadas, score y EV mínimos, tamaño que mantiene
   el coste fijo ≤ 0,5 %, horas permitidas, perfil de salida (nunca más laxo), tope diario. `apply_director` **solo endurece** (invariante
   probado con 500 estados aleatorios). Las primeras 24 h va en **sombra** (calcula y registra, no manda). Interruptor: `director_enabled: false`.
5. **Cerebro v2 y panel v2.** El cerebro añade una regresión logística (numpy) junto al modelo Beta, elegida solo si gana fuera de muestra
   en retorno y calibración; usa una probabilidad pesimista por tamaño de muestra y descuenta el coste fijo del EV. El panel (`/`) enseña
   todo lo real con marca de tiempo y bandera de frescura; lo que falta lo dice. **Coinversa es contexto de riesgo, no señal.**

## 2. Instalación en la máquina del bot (`/workspace/ai-trading-bot`)
Orden exacto; no saltar el backup.

```bash
cd /workspace
./ai-trading-bot/stop.sh || touch ai-trading-bot/STOP          # parar el servicio (espera a que no haya posiciones a medio cerrar)
cp -a ai-trading-bot ai-trading-bot.bak_$(date +%F_%H%M)        # backup completo: estado, keys.env, CSV, wallet, config
# opción A (recomendada): clonar la rama en un sitio aparte
git clone -b claude/trading-bot-mvp --depth 1 https://github.com/angelmartinezcalzada/Angel-proyectos.git /tmp/mvp
SRC=/tmp/mvp/ai-trading-bot
# opción B: descomprimir el zip ai-trading-bot-mvp-2026-10-31.zip en /tmp/mvp y usar SRC=/tmp/mvp/ai-trading-bot
cd /workspace/ai-trading-bot
for f in memebot.py scam.py brain.py eval_solana.py live_sol.py copytrade_paper.py copytrade_rules.py news.py insider.py dashboard.py \
         dash_data.py dashboard_v2.html director.py run_forever.sh PLAYBOOK.md README.md HANDOFF_GROK.md DASHBOARD.md; do cp "$SRC/$f" "$f"; done
rm -rf hyperliquid; cp -r "$SRC/hl_leg" "$SRC/tests" "$SRC/tools" .            # el paquete se llama hl_leg (no "hyperliquid": sombreaba al SDK)
mkdir -p research && cp -r "$SRC/research/coinversa_study.py" "$SRC/research/coinversa_study.json" "$SRC/research/data" research/
sed -n '/^## 2026-10-31 20:05/,$p' "$SRC/DECISIONS.md" >> DECISIONS.md          # añadir las entradas nuevas al registro local
pip install -q pytest flask solders && python3 -m pytest -q tests/              # deben pasar los 97 tests (flask/solders ya están si el bot corre)
```

**No copiar**: `config.json` (el de producción manda; añadir a mano las claves nuevas de §5 si se quieren cambiar sus valores por defecto),
`data/`, `state_*.json`, `trades_*.csv`, `keys.env`, `solana_wallet.json`, `dashboard_password.txt`, `brain_state.json`.

Reinicio: `nohup setsid ./run_forever.sh >/dev/null 2>&1 &` y comprobar con `./status.sh`.

Después del reinicio, en este orden:
```bash
python3 tools/close_atas.py            # dry run: lista las cuentas de token vacías y el rent bloqueado (~24 cuentas ≈ 4,7 $)
python3 tools/close_atas.py --yes      # con el OK de Àngel: las cierra (simula → envía → confirma); el SOL vuelve al wallet
python3 director.py --dry-run          # primer informe del Director con los datos reales (no escribe nada)
python3 director.py --report           # cada día: resumen para pegar en DECISIONS.md
```
El panel v2 está en `https://<túnel>/` (la antigua vista móvil sigue en `/live` y `/v1`).

## 3. Qué comprobar en la primera hora tras el reinicio
| Señal | Dónde | Esperado |
|---|---|---|
| Escaneos cortos | `bot_solana.log` línea `[solana] prefilter … rugcheck fetched X/Y (Z past budget) in Ns` | N ≤ ~150 s (antes 650-780 s); `manage()` sigue corriendo durante el prefetch |
| Puerta EV en real | `LIVE buy … blocked: EV …% < 3x real round-trip …%` | el rt ahora es el real (≈0,3-1 %), no ≥1 % + tolerancia. **Atención:** es numéricamente más laxa que antes y puede haber más compras; si Àngel no lo quiere, se vuelve a `otherAmountThreshold` en `_buy_live` (DECISIONS 21:45) |
| Kill switch | tras un `KILL SWITCH` no debe quedar ninguna posición abierta más de unos pasos | aplana mientras `halted` persista; se detiene si existe `KILL_solana` |
| Mints vetados | `hardfail_recent` en `candidates_solana.jsonl` | veto determinista permanente (mint/freeze/LP) → no se re-evalúa en 1 h; veto lento (holders/tasa) → 15 min |
| Rent de ATA | `SELL … rent=0.19` en el motivo de cierre de una posición completa | el rent se descuenta al cerrar, no al abrir (no dispara el stop) |
| Cerebro | `brain_state.json` → `oos.policy`, `oos.n_mints`, `active_votes`, `active` | puede pasar a `active=false` en un reentreno: es la evaluación honesta, no un fallo; volver a activar exige 3 reentrenos seguidos |
| Panel v2 | `/` tras el login | todas las tarjetas con datos reales y hora; las que no tengan fichero dicen "sin datos" (nunca un número inventado) |
| Rent de ATAs | `bot_solana.log` línea `ATA closed N account(s), SOL back …` tras una venta completa; `research/ata_close.jsonl` | cada venta completa en real cierra su cuenta de token; `ATA … not closed after 3 attempts` solo si el token deja dust o es Token-2022 raro |
| Director | `director_state.json`, `director_log.jsonl`, línea `DIRECTOR shadow …` / `DIRECTOR ok: …` en el log | 24 h en sombra; después aplica solo endurecimientos (score/EV/tamaño/stop/ventanas/tope). `python3 director.py --report` |
| Tests | `python3 -m pytest -q tests/` | 97 passed |

## 4. Resumen de las correcciones (detalle y evidencia en DECISIONS.md 20:40, 21:15 y 21:45)
1. `_buy_live`: el coste ida-vuelta se medía con `otherAmountThreshold` (incluye toda la tolerancia de slippage) → la regla "EV ≥ 3×rt" exigía ≥3-5 % y bloqueaba casi todo. Ahora mide con `outAmount`. Regla igual, umbral efectivo más bajo (decisión abierta, §7). Además se rechaza la compra si el slippage dinámico supera `max_buy_slip_bps` (400).
2. Kill switch diario como estado: mientras `halted` persista (sobrevive a reinicios) se vende todo cada paso, salvo que exista `KILL_solana`.
3. Write-off de posiciones muertas en real solo con evidencia positiva: venta completa + ≥5 swaps fallidos + ≥10 sin ruta + ≥15 min + DexScreener lista el par con liquidez < 1.000 $ + Jupiter responde a una cotización de control. `dead` impide re-adoptarlas. Ventas fallidas con back-off exponencial (máx. 30 min).
4. `get()`: sin reintentos en 4xx definitivos; RugCheck 8 s/2 intentos; caché negativa 180 s; presupuesto de 150 s por escaneo (`prefetch_rug`) sin bloquear `manage()`. Fail-closed.
5. guard_loop no re-sella precios obsoletos si DexScreener cae; `rug()` fail-closed ante informes malformados; `reload()` tolera config a medio escribir; `score_normalised` ausente = veto; `pump_play` por defecto False; honeypot no cachea cotizaciones ausentes; ban del creador en hilo aparte con lock; `seen`/`dead` sobreviven a `go_live`; venta parcial no puede ejecutarse dos veces; slots de evaluación (`hardfail_recent`, 1 h permanente / 15 min lento); scam.check antes del log único.
6. Salidas urgentes con prioridad "veryHigh" (tope 1.000.000 lamports); rent de la cuenta de token anotado y descontado al cierre; capa scam fail-closed ante excepciones; copytrade papel marca rug con 2 sondeos y espera confirmación mientras tanto (`copytrade_rules.py`); insider con commitment "confirmed" en firmas Y transacciones, cursor fail-closed (`pending_swaps`); news sin falsos positivos de listing.
8. Rent de ATAs: `live_sol.close_empty_atas` (solo cuentas con saldo 0, simulación obligatoria, ≤12 por tx, lote fallido → una a una) y `memebot.ata_sweep` tras cada venta completa en real; `tools/close_atas.py` para el barrido manual. El rent sigue restándose del PnL registrado al cerrar (contabilidad conservadora).
9. Director: `director.compute` cada hora en el hilo de aprendizaje; `director.apply_director` en `reload()` (solo endurece, caché 10 min, estado obsoleto > 3 h = config base); `director.entry_allowed` antes del scam.check (jugada / hora / tope diario, motivo `director_gate`, que NO cuenta como veto para el dataset del cerebro).
10. Cerebro v2: `_logit_fit` (numpy, L2, estandarizado) + `model_choice` por OOS; `p_low` = p − 1 error estándar; `decide()` lee `brain_ev_min` y `director_fixed_share`; `calibration` en `brain_state.json`.
7. Cerebro: `sim()` replica la regla de salida real (trail −6 %/12 %), orden conservador en la vela, velas con hueco = min(stop, cierre), alineación ≤5 min, caché de velas fusionada, solo etiquetas resueltas, máx. 6 filas/mint/día, purga anti-fuga, evalúa la política desplegada (EV>1 % y score≥45), ≥10 mints; desactivar es inmediato y activar exige 3 reentrenos; escrituras atómicas.

## 5. Claves nuevas de `config.json` (todas con valor por defecto en el código)
`rc_timeout_s` 8 · `rc_fail_cache_s` 180 · `rc_scan_budget_s` 150 · `hardfail_skip_s` 3600 · `hardfail_short_s` 900 · `max_buy_slip_bps` 400 ·
`writeoff_sellfail` 5 · `writeoff_min_s` 900 · `writeoff_max_liq_usd` 1000 · `ata_autoclose` true · `brain_ev_min` 0.01 (el Director solo lo sube) ·
`director_enabled` true (false = el Director calcula y registra pero no manda).
Entorno opcional: `COINVERSA_API_KEY` (sin ella `hl_leg/hl_context.py` no hace nada), `COINVERSA_BASE_URL`, `COINVERSA_ENDPOINTS_JSON`.

## 6. Pata Hyperliquid: qué puede hacer Grok y qué necesita de Àngel
- La estrategia se ejecuta en **Keel** (app.usekeel.io), no en esta máquina. Paper run: `hl_leg/hl_paper.json` (id `dep_01m69ygrjews0qmgq2sraj8rdr`, estrategia causal `str_01m69nnhfd4z38bbcy07gs7kk6`, 1.000 $ simulados, evaluación diaria 11:59 UTC). Se pausa sola si nadie visita la web en 28 días. Un DD de −30 % en paper está dentro de lo medido.
- Grok puede: ejecutar `python3 -m hl_leg.hl_context --once` (si hay `COINVERSA_API_KEY`) y leer `data/hl_risk.json` (campo `status`: ok/partial/degraded) en la revisión horaria; servir `/api/hl` en el panel; mantener `hl_leg/evidence.json` al día si Àngel comparte nuevos resultados de Keel.
- Grok **no debe** cambiar la estrategia (`hl_leg/strategies/supertrend_bollinger_causal_top15.keel.py`) sin un backtest fuera de muestra en Keel que lo justifique, ni usar Coinversa como señal de entrada, ni volver a la versión de hindsight (`supertrend_bollinger_small.keel.py`) aunque sus números parezcan mejores.
- Pasar a real es decisión manual de Àngel en la web de Keel: ≥150 $ en Hyperliquid (con 48 $ no merece la pena, mínimo de orden 10 $), tras ≥21 días / ≥20 evaluaciones de paper con paridad ±50 pb, apalancamiento 1x. Con 1x y 150 $ el DD histórico (−58 %) son −87 $.

## 7. Reglas que no cambian y decisiones abiertas para Àngel
- Nunca relajar vetos antiestafa, tamaño ni stops. Fail-closed cuando falte un dato.
- Abiertas (no aplicadas, las decide Àngel): (a) pasar el memebot a papel mientras la pata Hyperliquid está en paper (su historial real es PF 0,44); (b) mantener o no la puerta EV nueva (más laxa que la antigua; §3); (c) la puerta del cerebro exige score ≥ 45 mientras el modelo pondera `score_hi` como señal negativa: o se quita el gate en la rama del cerebro o se deja como está (ya se evalúa así en `learn()`); (d) stop diario en SOL en vez de USD; (e) **ejecutar `tools/close_atas.py --yes`** (recupera ~4,7 $; solo cuentas vacías); (f) registrar en el CSV las posiciones que `reconcile` descarta; (g) dejar que el Director salga de la sombra a las 24 h (automático) o mantenerlo en sombra con `director_enabled: false`.

## 8. Prompt para pegar a Grok
```
Eres el operador (director financiero) del bot de trading de Àngel. Hay una versión nueva en la rama claude/trading-bot-mvp del repo
angelmartinezcalzada/Angel-proyectos (carpeta ai-trading-bot). Lee primero ai-trading-bot/HANDOFF_GROK.md y las entradas del 31-oct
(20:05, 20:40, 21:15, 21:45) de DECISIONS.md. Tareas, en este orden:
1) Instala la versión siguiendo §2 del HANDOFF al pie de la letra (backup, no sobrescribir config.json, state, CSV, keys ni wallet;
   el paquete hyperliquid/ pasa a llamarse hl_leg/).
2) Ejecuta python3 -m pytest -q tests/ y pega el resultado en DECISIONS.md (deben pasar 97).
3) Reinicia el servicio y durante la primera hora verifica la tabla de §3; anota cada punto en la revisión horaria. Si ves más compras
   en real que antes por la puerta EV nueva, dilo explícitamente a Àngel: es una decisión suya (§7 b).
4) Mantén las reglas de §7: nunca relajes vetos, tamaño ni stops; ante un dato ausente, fail-closed.
5) No toques la estrategia de Hyperliquid, no vuelvas a la versión de hindsight y no uses Coinversa como señal; si Àngel te da
   COINVERSA_API_KEY, añade el logger de contexto (ya está en run_forever.sh) y usa data/hl_risk.json en la revisión horaria.
6) Ejecuta python3 tools/close_atas.py (dry run) y enseña a Àngel cuánto rent hay bloqueado; solo con su OK, --yes.
7) Ejecuta python3 director.py --dry-run con los datos reales y pega el informe en DECISIONS.md; vigila director_log.jsonl.
   El Director va 24 h en sombra y después manda (solo endurece). Si Àngel no lo quiere al mando: director_enabled: false.
8) Las decisiones de §7 se proponen a Àngel con datos, no se aplican solas. Cuando hables de la pata Hyperliquid usa los números
   honestos (OOS Sharpe 1,15, DD histórico −58 %), nunca los de hindsight.
Si algo del traspaso no cuadra con lo que ves en la máquina, para, descríbelo en DECISIONS.md y pregunta antes de seguir.
```
