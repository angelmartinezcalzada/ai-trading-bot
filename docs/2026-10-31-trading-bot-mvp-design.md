# Bot de trading 24/7 — diseño del MVP (31-oct-2026)

Sesión autónoma: Àngel pidió "usa Keel y Coinversa, mejora el proyecto hasta que sea un MVP que dé muy buen rendimiento".
No podía responder preguntas durante el trabajo, así que este documento recoge el entendimiento, los **supuestos explícitos**
y las decisiones tomadas en su nombre. Todo es revisable; nada de lo hecho mueve dinero real.

## 1. Entendimiento del objetivo

- **Lo que dijo Àngel:** bot autónomo 24/7 que haga crecer ~48,5 $ hacia ~1.000 € sin garantías; gestionado "como un CFO"
  (revisión horaria, panel, automejora cada 2 h). Hoy: 64 cierres reales en memecoins de Solana con PF 0,44 y 17 h sin entradas.
- **Lo que interpreto como "MVP con muy buen rendimiento":** una estrategia con **evidencia fuera de muestra** (objetivo inicial:
  Sharpe > 1,5 y drawdown < 40 %) que pueda ejecutarse de forma reproducible, con el riesgo acotado y el camino papel → real documentado.
  No es una promesa de retorno; es un sistema cuya ventaja se ha medido con honestidad. **Resultado (revisión 21:45):** el objetivo
  numérico solo se alcanza con un universo elegido con hindsight; la versión honesta queda en OOS Sharpe 1,15 / DD −30 % y ventana
  completa 0,76 / DD −58 %. Se entrega esa, con la advertencia explícita de que el rendimiento es modesto.
- **Supuestos (corrígelos si no son ciertos):**
  1. Keel (free, 75 backtests/mes) y Coinversa Pulse (plan Pro) seguirán disponibles; Keel puede ejecutar la estrategia en
     papel y, desde su web, en real sobre Hyperliquid.
  2. Àngel puede abrir una cuenta en Hyperliquid y depositar ≥150 $ cuando decida pasar a real; con 48 $ el MVP no es ejecutable
     (mínimo de orden 10 $).
  3. Los vetos antiestafa, los tamaños y los stops del bot de Solana **no se relajan** (regla propia de Àngel en DECISIONS.md).
  4. El bot CEX (Binance papel / Coinbase parado) no forma parte del MVP; se deja como está.

## 2. Diagnóstico

| Evidencia | Fuente |
|---|---|
| Solana real: 64 cierres, PnL −1,65 $, PF 0,44; copytrade papel PF 0,18-0,30 (rugs); pump-play real PF < 1 | README/DECISIONS del proyecto |
| 0 entradas reales en 17 h: universo (liquidez) + RugCheck caído/lento (650-780 s por escaneo) | DECISIONS 31-oct |
| La misma regla de tendencia sobre 18 memecoins (ya en perps líquidos, 4,5 pb) rinde Sharpe 0,70 / DD −53 % frente a 1,84 / −30 % en los 15 mayores perps. **Matiz (21:45):** ambos universos son de hindsight; contra el top-15 causal in-sample (+29 % / DD −58 %) la distancia es pequeña, así que esto no demuestra que el universo sea el problema | backtests Keel (evidence.json) |
| El sesgo de cohortes de Coinversa no predice retornos a 1-24 h en 30 días (|corr| ≤ 0,10, signo inconsistente) | research/coinversa_study.py |

Conclusión: el historial real (PF 0,44, rugs) dice que el universo de memecoins recién nacidas pierde dinero; los backtests de Keel
no lo demuestran por sí solos (ver matiz). La ejecución y el modelo tenían además bugs reales, corregidos en esta sesión.

## 3. Decisión de arquitectura: dos patas

```
                    ┌──────────────────────────────┐
  Keel (backtest,   │ Pata A · Hyperliquid perps    │  paper ahora, real cuando se cumplan los criterios
  paper, live) ───► │ SuperTrend+Bollinger 1d top-15│◄── Coinversa: contexto de riesgo (hl_context.py), no señal
                    └──────────────────────────────┘
                    ┌──────────────────────────────┐
  DexScreener/      │ Pata B · Solana memecoins     │  sigue en real con 48 $ y vetos intactos; se le quitan
  RugCheck/Jupiter ►│ memebot.py (corregido)        │  los cuellos de botella (RugCheck) y bugs verificados
                    └──────────────────────────────┘
                    Panel único (dashboard.py: /api/state + /api/hl) · DECISIONS.md como fuente de verdad
```

### Pata A (la que aporta el "muy buen rendimiento")
- **Estrategia:** `hl_leg/strategies/supertrend_bollinger_causal_top15.keel.py`. Long-only sobre los 15 perps de mayor volumen,
  re-elegidos cada semana por el volumen de los 30 días previos dentro de un pool de 60 (sin hindsight);
  entra cuando SuperTrend(10, 3) está en verde, el precio está en la mitad alta del canal de Bollinger(20, 2) y la volatilidad no
  está comprimida (ATR7/ATR21 > 0,85); sale cuando cualquiera deja de cumplirse. 33 % del capital por nombre, 1x bruto máximo,
  una orden de entrada y una de salida por posición (`on_change`).
- **Por qué esta y no otra:** de 6 estrategias (4 forks de la librería de Keel + 2 diseños propios) y sus variantes es la única que
  mantiene rendimiento fuera de muestra y es ejecutable con poco capital. Con el universo de hindsight leía IS 1,69 → OOS 1,98; con el
  universo causal, **OOS 1,15 / +43,5 % / DD −30 %** y ventana completa 0,76 / DD −58 %. Momentum+funding es robusta pero necesita
  ~15.000 $. Confluence 4h se derrumba OOS (1,85 → 0,53). Un filtro de régimen sobre la causal mata el OOS (0,33): rechazado.
  Tabla completa en `hl_leg/evidence.json`.
- **Robustez:** multiplicador ±20 % → Sharpe 1,59-1,79 (medido en la versión de hindsight); causal: 6 de 10 trimestres positivos,
  dos trimestres de −28 %, DD máx. −58 %; casi todo el retorno viene de 2026-Q2/Q3.
- **Ejecución:** Keel. Paper run `dep_01m69ygrjews0qmgq2sraj8rdr` (versión causal) arrancado el 31-oct 21:41 UTC (1.000 $ simulados,
  evaluación diaria 11:59 UTC); sustituye a `dep_01m69j62wfa03zrqxgbf71k436` (hindsight), parado.
  Real: paso manual en la web de Keel, solo cuando se cumplan los criterios de `hl_leg/hl_paper.json`.
- **Coinversa:** capa de riesgo/contexto. `hl_context.py` registra cada hora sesgo Apex/Sharps/Crowd, apalancamiento medio y
  notional cerca de liquidación por moneda, y calcula banderas (`crowd_with_us`, `apex_against`, `liq_cluster`, `high_leverage`)
  y un multiplicador de tamaño **que solo reduce** (0,5-1,0). No entra en la señal porque el estudio no encontró poder predictivo.

### Pata B (el bot existente)
- Corrección verificada: `get()` ya no reintenta 3× con 15 s los 4xx definitivos de RugCheck; caché negativa de 180 s y presupuesto
  de 150 s por escaneo (`prefetch_rug`). Fail-closed: lo no verificado sigue vetado como `rugcheck_unavailable`.
- Pendiente de la revisión paralela del código (workflow): aplicar solo los hallazgos confirmados que no relajen vetos.
- Recomendación (no aplicada, decisión de Àngel): dejar el memebot en **papel** hasta que la pata A esté en real; la evidencia
  dice que el universo de memecoins no tiene ventaja con estos costes.

## 4. Riesgos y límites

- Backtest ≠ futuro: 2 años de datos, un solo régimen alcista largo + un bajista corto. El OOS honesto es 1,15 y puede bajar más.
- Drawdown −58 % histórico (causal): con 1x y 150 $ son −87 $. Apalancar multiplica el DD.
- Keel free: 1 estrategia en real, 1 paper run, 75 backtests/mes (quedan 43). El paper run se pausa si nadie visita la web en 28 días.
- Coinversa: la API REST no se pudo verificar desde esta sesión (dominio bloqueado); los paths están en `DEFAULT_ENDPOINTS` y son
  configurables; sin clave el módulo no hace nada.
- Supervivencia: el top-15 resuelto en julio-2026 era un sesgo **grande**, no leve (OOS 1,94 → 1,15 al hacerlo causal). La versión en
  paper re-elige el top-15 cada semana dentro de un pool de 60 resuelto el 31-oct; ese pool también conviene re-resolver trimestralmente.

## 5. Criterios de éxito del MVP

1. Paper run con ≥ 20 evaluaciones y ≥ 21 días cuyas operaciones coincidan con las del backtest (paridad ±50 pb, umbrales de Keel).
2. Panel muestra la pata A (`/api/hl`) y el memebot sin errores.
3. Tests verdes (`pytest tests/`).
4. DECISIONS.md explica cada cambio con su evidencia.
