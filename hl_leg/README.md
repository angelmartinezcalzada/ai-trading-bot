# Módulo Hyperliquid (Keel + Coinversa)

Pata del MVP con **evidencia medida** de rendimiento: una estrategia de tendencia sobre los 15 perps más negociados de
Hyperliquid, construida, backtesteada y validada fuera de muestra con [Keel](https://app.usekeel.io), y vigilada con el
contexto de posicionamiento de [Coinversa Pulse](https://coinversa.ai). La evidencia honesta es **modesta** (ver abajo):
no es "muy buen rendimiento", es una ventaja pequeña, medida sin trampas y ejecutable con poco capital.

## Qué hay aquí

| Fichero | Para qué |
|---|---|
| `strategies/supertrend_bollinger_causal_top15.keel.py` | **Estrategia en paper** (DSL de Keel, `str_01m69nnhfd4z38bbcy07gs7kk6`). Long-only, 1d, SuperTrend(10,3) + Bollinger + volatilidad no comprimida, 33 % por nombre, máx. 1x bruto, una orden de entrada y una de salida por posición. El top-15 se re-elige **cada semana** por volumen de los 30 días anteriores dentro de un pool de 60 (sin mirar el futuro). |
| `strategies/supertrend_bollinger_small.keel.py` | La misma regla sobre el top-15 que Keel resolvió el **2026-07-06** (dentro de la ventana fuera de muestra). Sus números están inflados por supervivencia; se guarda como referencia y para explicar la diferencia. |
| `strategies/*.keel.py` | Las candidatas rechazadas con el motivo en cabecera (confluence 4h, momentum+funding, meme-perps, rotación top-3). |
| `strategies/universe.json` | Pool causal de 60 (resuelto 2026-10-31) y el top-15 de hindsight (2026-07-06). |
| `evidence.json` | Registro de todos los backtests (ids de Keel, ventanas, métricas, trimestres, capital mínimo) con la versión honesta arriba. |
| `hl_paper.json` | Paper run en marcha en Keel y criterios para pasar a real. |
| `coinversa.py` | Cliente Coinversa (fail-safe) + funciones puras: sesgo por cohorte, banderas de riesgo, multiplicador de tamaño (solo reduce). |
| `hl_context.py` | Logger horario: `data/hl_context.csv` y `data/hl_risk.json` para la revisión CFO y el panel. |

## Evidencia (resumen honesto)

Ventanas: in-sample 2024-08-15 → 2026-03-31; **fuera de muestra 2026-04-01 → 2026-10-30** (ningún parámetro se eligió mirando esta ventana).
Costes: 4,5 pb de comisión + 4,5 pb de slippage por fill, funding incluido. Capital 10.000 $ salvo nota.

| Estrategia | Universo | **OOS Sharpe / retorno / DD** | Ventana completa Sharpe / retorno / DD | Trimestres + |
|---|---|---|---|---|
| **SuperTrend+Bollinger 1d, top-15 causal (en paper)** | semanal, sin hindsight | **1,15 / +43,5 % / −30 %** (PF 1,31) | 0,76 / +91 % / **−58 %** (PF 1,18) | 6 de 10 (2025-Q1 −28 %, 2026-Q1 −28 %) |
| Misma regla, top-15 resuelto 2026-07-06 (referencia) | con hindsight | 1,94 / +104 % / −30 % | 1,79 / +855 % / −35 % | 8 de 10 |
| Misma regla, cesta de nombres anteriores a 2025 | sin hindsight | 0,15 / −2 % | 0,33 / +7,5 % / −71 % | — |
| Top-15 causal + filtro de régimen de mercado | sin hindsight | 0,33 / +1 % | 0,72 / +76 % / −44 % | rechazada |
| Momentum+funding top-30 (continua) | con hindsight | 1,99 / +21 % / −12 % | — | exige ~15.000 $ |
| Confluence 4h top-15 (v4) | con hindsight | 0,53 / +8 % / −27 % | — | IS 1,85 → se derrumba |
| Meme-perps confluence 4h (18 memecoins) | con hindsight | — | IS 0,70 / −53 % (PF 1,11) | — |

Lectura: la diferencia entre 1,94 y 1,15 fuera de muestra es **supervivencia del universo** (PUMP, XPL, LIT, ZEC, VVV, GRAM entraron
en el top-15 por hacerse grandes en 2026), no ventaja de la regla. La versión causal es la única que puede operarse hacia delante y
es la que está en paper. Su tramo in-sample es flojo (+29 % en 19 meses con DD −58 %); casi todo el retorno viene de 2026-Q2/Q3.
Capital mínimo (realismo de Keel con `min_trade_size=0.05`): <25 % de órdenes bajo el mínimo de 10 $ desde ~64 $, <5 % desde ~100 $.
Referencia: BTC en la ventana completa +39 % con DD −53 %.

**Sobre la "lección del universo":** la comparación memecoins (0,70 / −53 %) frente a top-15 (1,84 / −30 %) que abrió esta sesión
se hizo con universos de hindsight en ambos lados. Contra el top-15 causal in-sample (+29 % / −58 %) la distancia es pequeña, así que
los backtests de Keel **no demuestran** que el universo memecoin sea el problema. Lo que sí lo dice es el historial real del propio bot
(64 cierres, PF 0,44).

## Cómo se opera

1. **Paper (ahora):** Keel ejecuta la estrategia causal en simulado con precios reales (`hl_paper.json`, 1.000 $ simulados,
   evaluación diaria 11:59 UTC). Revisarla en la web de Keel al menos una vez cada 4 semanas (si no, se pausa sola).
   Un drawdown de −30 % en paper está dentro de lo medido y no es motivo de parada por sí solo.
2. **Revisión CFO:** `python3 -m hl_leg.hl_context --once` escribe el contexto Coinversa (sesgo Apex/Crowd, apalancamiento,
   notional cerca de liquidación) para cada moneda del universo. Requiere `COINVERSA_API_KEY`; sin clave no hace nada.
   Las banderas **solo informan** y el multiplicador de tamaño **solo reduce**; nunca relajan vetos ni aumentan tamaño.
3. **Real:** se decide en la web de Keel cuando se cumplan los criterios de `hl_paper.json` (≥21 días / ≥20 evaluaciones con
   paridad ±50 pb, ≥150 $ en Hyperliquid, 1x). Con 48 $ no merece la pena: el mínimo de orden es 10 $.

## Por qué Coinversa no está en la señal

Estudio `research/coinversa_study.py` (30 días horarios, BTC/SOL/FARTCOIN; entradas en `research/data/coinversa_2026-10/`):
correlación entre el sesgo de cada cohorte (Apex, Sharps, The Crowd) y el retorno a 1/4/24 h ≈ 0 e inconsistente entre monedas.
Sin evidencia no se mete en la entrada; queda como capa de riesgo y contexto. Se reevaluará con más historia (`data/hl_context.csv`).
