# Director: cerebro con autoridad propia para el bot de Solana (diseño, 31-oct-2026)

Petición de Àngel: "viendo el bot, mejóralo haciendo un trabajo espectacular: mejora el cerebro del bot y las decisiones, que
tenga autoridad propia con tal de ganar el objetivo, que es ganar dinero". Sesión autónoma; este documento recoge el
entendimiento, los supuestos y el diseño. Todo revisable. Nada de lo diseñado mueve dinero fuera de las reglas de Àngel.

## 1. Lo que dicen los datos reales antes de diseñar nada

Historial real de Solana (trades_solana_live.csv, 30-oct 16:10 → 31-oct 01:19, 64 cierres):

| Hecho | Número |
|---|---|
| Tamaño medio de operación | 2,94 $ (mediana 3,0 $) |
| Win rate / ganancia media / pérdida media (sobre la posición) | 33 % / +1,72 % / −3,51 % |
| Esperanza por operación | ≈ −1,8 % de la posición (≈ −0,05 $) |
| PnL neto de las 64 ventas | −1,65 $ (PF 0,44); 60 de 64 eran pump-play (PF 0,33), hoy solo en papel |
| Caída del patrimonio en el mismo tramo | −4,73 $ |
| **Diferencia no explicada por el PnL** | **−3,08 $** = rent de las cuentas de token (24 mints × 0,00204 SOL ≈ 0,19 $) + comisiones |
| Cerebro (replay OOS, 215 tests) | +1,8 %/op frente a +1,3 % del universo entero: ventaja pequeña, antes de costes fijos |

Conclusión que manda sobre el diseño: con posiciones de 3 $, **el coste fijo por operación (rent 0,19 $ + comisiones) es un
6-7 % de la posición**, mayor que cualquier ventaja medida (+1,8 %). Ningún modelo gana dinero con ese lastre. Primero se
elimina el lastre; después se da autoridad al cerebro para elegir pocas operaciones buenas, no muchas.

## 2. Objetivo y supuestos

- **Objetivo:** maximizar la esperanza neta de la cuenta real de Solana respetando las reglas de Àngel. "Autoridad propia" =
  el bot decide por sí mismo qué, cuándo y cuánto operar **dentro de los topes**, y lo justifica con números en un registro.
- **Supuestos explícitos (corrígelos si no):**
  1. Las reglas de Àngel siguen vigentes: vetos antiestafa, tamaño máximo y stops no se relajan nunca; fail-closed.
     La autoridad del Director solo puede **endurecer** (menos operaciones, menor tamaño, stops más cerrados, pausas).
  2. Pump-play sigue en papel hasta tener 20+ cierres con PF > 1,3 (decisión 17:37).
  3. La cuenta sigue siendo ~48 $; no hay depósito nuevo. Recuperar el rent de las ATAs vacías (~3-4,7 $) es dinero real.
  4. Datos para validar (candidates_solana.jsonl, ohlcv_cache.json, logs) están en la máquina del bot, no aquí: el código
     se entrega con tests sintéticos y un comando de validación que Grok (o yo por Remote Control) ejecuta con los datos reales.

## 3. Arquitectura

```
                         ┌──────────────────────────────────────────┐
  ledgers reales/papel   │  director.py  (cada hora + al arrancar)  │   director_state.json  ──► memebot.reload()
  brain_state.json  ───► │  evidencia → presupuesto por jugada,     │   director_log.jsonl   ──► panel (/api/overview.director)
  candidates/ohlcv cache │  umbral EV, tamaño, ventanas, perfil de  │   director_report.md   ──► DECISIONS (Grok lo pega)
  insider/hl/eval        │  salida, pausas; nunca relaja topes      │
                         └──────────────────────────────────────────┘
                                   ▲                      │
                 brain.py v2 (modelo logístico numpy,     │ apply_director(cfg, state) -> cfg_efectiva
                 walk-forward purgado, p pesimista,       ▼
                 coste total por operación)         memebot.py: entradas, tamaño, salidas, cierre de ATAs
```

### 3.1 Coste total por operación y cierre de ATAs (el dinero más seguro)
- `live_sol.close_empty_atas(dry_run=True)`: lista las cuentas de token (SPL y Token-2022) del wallet con saldo 0 y construye
  transacciones `CloseAccount` (instrucción 9 del programa de tokens; destino del rent = el propio wallet; ≤ 12 cierres por tx),
  firma local, **simula** y envía; devuelve `{closed, sol_recovered, failed}`. Solo cuentas con saldo 0; nunca toca cuentas con tokens.
- memebot: tras una **venta completa confirmada** de un mint, cierra su ATA en el mismo ciclo (cola `ata_close`), con reintento
  y sin bloquear `manage()`. Resultado: el rent deja de ser coste (se recupera en cada salida); solo se pierde si el token muere con saldo.
- `tools/close_atas.py --dry-run | --yes`: barrido manual para recuperar el rent acumulado hoy (24 ATAs ≈ 4,7 $ si siguen abiertas).
- Modelo de coste en la puerta de entrada: `coste_total = rt_real + (fee_tx_ida+vuelta + rent_no_recuperable_esperado)/tamaño`;
  el rent cuenta como coste solo con la probabilidad de no poder cerrar (token muerto con saldo), estimada del historial (`dead`).

### 3.2 Director (`director.py`)
Entrada (solo ficheros locales): trades reales y papel por jugada (`scanner`, `brain`, `insider_elite`, `pump`), `brain_state.json`
(OOS), `eval_solana.json`, dataset etiquetado (`brain.build_dataset`, sin red si `max_fetch=0`), `insider_status.json`, config.
Salida `director_state.json` (atómico) con **solo claves que endurecen**:

| clave | significado | regla |
|---|---|---|
| `plays` | `{scanner: on/off, brain: on/off, insider_elite: on/off, pump: paper/off}` | una jugada se apaga si su PF (real+papel, shrink bayesiano, n ≥ 15) < 1 o su esperanza neta tras costes < 0; se enciende solo con n ≥ 20, PF > 1,2 y esperanza > coste; `pump` nunca pasa de papel por sí solo |
| `min_score_eff` | umbral de score efectivo (≥ `min_score` de config) | el bucket de score con mejor esperanza OOS; nunca por debajo del de config |
| `ev_min_eff` | EV mínimo efectivo (≥ `EV_MIN`) | = coste_total_estimado × 3 (regla 18:27) como mínimo |
| `size_policy` | `{target_usd, max_frac}` | tamaño que hace coste fijo ≤ 0,5 % de la posición, acotado por `max_position_pct`, `max_gap_loss_pct`, `max_trade_loss_pct/max_stop_pct`; si no existe tamaño que cumpla, `target_usd = 0` (no operar) y lo dice |
| `windows` | horas UTC permitidas | horas con esperanza OOS ≥ 0 y n ≥ 10 en el dataset; si no hay datos, todas |
| `regime_gate` | `{heat: [...], sol_trend: [...]}` | igual que arriba por régimen |
| `exit_profile` | `{hard_stop_pct, trail_pct}` | elegido por replay entre una rejilla **nunca más laxa** que config (hard_stop ≤ config, trail ≤ config); mínimo 40 trayectorias; si empata, el de config |
| `max_trades_day` | tope diario de entradas | = presupuesto de riesgo diario / pérdida media esperada; ≤ el que permita `daily_max_drawdown_pct` |
| `evidence` | números que justifican cada clave | se copian al log |

`apply_director(cfg, state)` devuelve la config efectiva: `max(cfg.min_score, state.min_score_eff)`, `min(size, …)`,
`min(hard_stop)`, `min(trail)`, intersección de jugadas, etc. **Test de invariantes** con estados aleatorios: la config
efectiva nunca es más laxa que la base en ninguna clave de riesgo. Si `director_state.json` falta, está corrupto o tiene más
de 3 h, se ignora (se opera con la config base) y se registra.

Gobernanza: cada decisión → `director_log.jsonl` {t, clave, antes, después, evidencia, por_qué}; `python3 director.py --report`
imprime un resumen en castellano para DECISIONS.md; el panel muestra la tarjeta "Director" (estado, última decisión, evidencia).
El Director **no** puede: relajar vetos, subir tamaño por encima de los topes, abrir pump real, tocar `config.json`.

### 3.3 Cerebro v2 (`brain.py`)
- **Modelo:** regresión logística con L2 en numpy (sin sklearn en producción) sobre las señales binarias actuales + features
  continuas estandarizadas (log liquidez, vol/liq, h1, m5, edad, score, hora, ratio compras/ventas, heat, insider tok×w).
  Entrenamiento walk-forward **purgado** (ninguna etiqueta de train usa velas de la ventana de test) y **embargo** de 2 h.
- **Elección de modelo por evidencia:** en cada `learn()` se comparan Beta-Bernoulli actual vs logístico por log-loss y
  esperanza de la política desplegada en OOS; se despliega el ganador solo si supera al score simple; si no, modo sombra.
  Umbral y hiperparámetros se eligen con validación interna del train (nunca mirando el test), como en la pasada de las 14:30.
- **p pesimista:** `p_low = p − z·sqrt(p(1−p)/n_eff)` (n_eff = muestras parecidas en train); EV y Kelly se calculan con `p_low`.
  Kelly fraccional 0,25 sobre `p_low`, capado por `size_policy`.
- **EV neto:** `EV = p_low·avg_win − (1−p_low)·avg_loss − coste_total`; entra solo si `EV ≥ ev_min_eff`.
- **Calibración:** Brier y curva de fiabilidad en 5 cubos en OOS se guardan en `brain_state.json` (el panel las enseña).
- Activación/histéresis como hoy (fail-closed; activar exige 3 reentrenos, desactivar es inmediato).

### 3.4 Perfil de salida por replay
`director.exit_grid(paths, cfg)`: para cada perfil {hard_stop ∈ [3, 4, 5, 6] %, trail ∈ [8, 10, 12] %} ≤ config, replay con
`eval_solana.sim` (modo trail) sobre las trayectorias etiquetadas de las últimas 7 días; elige por esperanza neta OOS (split
temporal) con n ≥ 40; se aplica por régimen (`heat`) si hay n suficiente, si no global. Los stops solo se **cierran**.

### 3.5 Integración en memebot
- `reload()`: tras leer config, `s.c = apply_director(s.c, load_director_state())`; log cuando cambia una clave efectiva.
- Entrada: `plays`, `windows`, `regime_gate`, `max_trades_day` como condiciones adicionales (fail-closed: fuera de ventana = no entra).
- Tamaño: `size_policy.target_usd` sustituye a `live_target_min/max_usd` solo hacia abajo o cuando el tope lo permite.
- Salida: `exit_profile` se aplica a posiciones nuevas (las abiertas conservan su stop; nunca se amplía).
- Tras venta completa: cola de cierre de ATA (3.1).

## 4. Riesgos y límites
- Muestras pequeñas: todo con shrinkage y mínimos de n; el Director prefiere **no operar** a operar sin evidencia.
- Fuga temporal: purga + embargo en walk-forward; test con datos sintéticos que detecta fuga (la esperanza OOS no debe mejorar
  cuando se mezclan ventanas).
- Red: el Director no usa red salvo `build_dataset(max_fetch=…)`; ante error, conserva el estado anterior (≤ 3 h) y lo registra.
- Cierre de ATAs: solo saldo 0, simulación obligatoria, ≤ 12 por tx, nunca en medio de una venta del mismo mint.
- No se puede validar aquí con datos reales (no están en el repo): se entrega `director.py --validate` para ejecutarlo en la máquina.

## 5. Criterios de éxito
1. Rent recuperado y dejado de pagar: `tools/close_atas.py` devuelve SOL al wallet; tras cada venta completa el ATA se cierra.
2. Puerta de entrada con coste total: ninguna compra real con EV neto < 3 × coste total.
3. Director activo con registro: cada hora escribe estado + log; el panel lo enseña; `--report` legible.
4. Invariantes: tests que prueban que la config efectiva nunca es más laxa que la base.
5. Validación en la máquina: `director.py --validate` muestra esperanza OOS por política (base vs cerebro v2 vs director) y Grok
   lo anota en DECISIONS.md antes de que el Director tome el mando de las entradas (modo sombra las primeras 24 h).
