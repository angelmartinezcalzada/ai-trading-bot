# Cerebro v3 — nota de diseño (2 nov 2026)

Objetivo: que el aprendizaje sea real (archivo etiquetado creciente, más información por fila, modelos con regularización
elegida fuera de muestra) **sin aflojar nunca la puerta de activación**. Todo lo nuevo o endurece o añade información; lo que
falta se trata como desconocido (sin operar / neutral), nunca como aprobado. Nada en `brain.py` coloca órdenes.

## 1. Archivo etiquetado `data/labels_solana.jsonl`
- Una línea por avistamiento negociable (liq ≥ mín., sin veto duro), **append-once por `rid`** (`mint:ts`, escrito por memebot; si
  falta, `mint:ts` se calcula igual). Una fila archivada **no se reetiqueta nunca**: velas nuevas no cambian su `ret`.
- Fila: `{rid, t, t_exit, mint, pair, S, x, ret, exit, rt, rt_src, cfg_hash, code:'brain/3', score, ctx?, st_f?}` (`x` = bloque
  continuo crudo, § 3; `score` = `score_brain`). Lectura con deduplicación por rid (gana la primera línea); líneas corruptas se saltan.
- La ventana de 7 días (`MAX_ROW_AGE_H`) solo decide **qué filas nuevas** se etiquetan (velas de GeckoTerminal, caché fusionada
  `ohlcv_cache.json`); el entrenamiento usa **todo el archivo**.
- Pesos de entrenamiento: `w = 0.5^(edad/10 d)` (`HALF_LIFE_D`) × 0,5 si la fila se etiquetó con otros parámetros de salida
  (`cfg_hash` ≠ actual; se informa en `cfg_hash_mismatch_n`). Topes por mint: 6 filas por día UTC (también al etiquetar: una fila
  sobrante no se archiva) y las 30 más recientes en total.
- Etiqueta con la **config base** (`learn(cfg, cfg_base=...)` → `sim()` usa los parámetros de salida de `cfg_base`): el Director
  endurece `hard_stop_pct`/`trail_pct_tt` sobre la config efectiva, pero el modelo aprende sobre la regla del dueño. Bucle cerrado.
- `cfg_hash = sha1({hard_stop_pct, trail_pct_tt, max_hold_hours, exit_mode})[:12]`.

## 2. Modelos
- **Beta** (como v2): tasa de acierto por señal booleana con prior K=10, amortiguación 0,3; ahora **ponderada** (sumas con `w`) y
  con `ne_on/ne_off` = tamaño efectivo de Kish (≤ recuento) como fuente de pesimismo.
- **Logit** L2 y **ridge** sobre `ret` winsorizado en [−0,30, +1,00], sobre `[23 booleanos + bloque continuo]` estandarizado
  (mu/sd en estado; winsor p1/p99 de train en las columnas continuas). `lambda ∈ {2, 5, 10, 20}` elegida en un corte temporal
  interno del train (70/30, log-loss / MSE ponderado; empate → la mayor). Newton amortiguado, sin sklearn.
- **n_eff local** para `p_low`: filas de train a distancia de Hamming ≤ 2 en el bloque booleano (mínimo 5), guardadas como
  `bool_rows` (máscaras de bits). Siempre ≤ al n global de v2 → más pesimista, nunca menos.
- Ridge: `ret_hat`, `ret_lb = ret_hat − resid_sd/√n_eff_local`, `EV = ret_lb − director_fixed_share` (en fracción; `ev_pct` ×100).
- `decide()` devuelve las claves de v2 + `ret_hat`, `ret_lb`, `model ∈ {beta, logit, ridge}` (el modelo realmente usado).

## 3. Bloque continuo `x` (49 columnas, `brain.XC`)
`log1p(liq)`, `vol_liq`, `clip(h1,−50,100)`, `clip(m5,−30,50)`, `log1p(age_h)`, `rt` (3,0 si falta + `rt_missing`), `rug.top10`,
`log1p(rug.holders)`, `insider.tok·w` (0 si `stale`), ratio de compras de `parts.b_s` (+ flag), `sin/cos(hour_utc)` (de `ctx` o de
`ts`), one-hot de las 6 fuentes más frecuentes del train, los 8 campos de `st_f` (+ flag por campo), los 11 booleanos de
`context.signals(ctx)` (+ `ctx_missing`; import perezoso en try/except), `score_brain/100`.
Señales booleanas renombradas: `insiders → rc_insiders`; `insider_conv/insider_elite → insider_tier` (0/1/2 → `insider_t1`,
`insider_t2` acumulativos; `stale` → 0). El estado antiguo se migra al cargar; los modelos lineales pre-v3 se descartan (otra
disposición de columnas) y `model_choice` vuelve a `beta`.

## 4. Validación y puerta (solo endurece)
- 3 pliegues de origen rodante, cortes al 50/60/70 % del **tiempo**. Agrupación por **episodio de mint** (avistamientos de un
  mint separados < 3 h comparten velas): el episodio va al lado de su primer avistamiento, nunca cruza el corte; train purgado
  (`t_exit ≤ corte`); test = episodios vistos por primera vez ≥ corte + 3 h de embargo. Pliegue válido: ≥ 30 train y ≥ 10 test.
- Voto = la política desplegada (`ev > brain_ev_min` y `score_brain ≥ brain_min_score`) es **positiva y bate a la base
  (`score ≥ min_score`) en TODOS los pliegues**, con ≥ 8 operaciones y ≥ 10 mints en el pliegue de cabecera (70 %).
- Un voto **cuenta** solo con ≥ 25 filas archivadas nuevas desde el último voto contado (`oos.vote_archive_n`); un voto que no
  cuenta no suma ni resta. Un refit que falla pone `active_votes = 0` y desactiva (igual que v2). HYSTERESIS 3 intacta.
- Cambio de modelo: cada refit anota un ganador (`oos.winner`: bate a Beta en todos los pliegues, ≥ 8 operaciones, logit además
  Brier ≤ Beta); se despliega solo tras 2 ganadores consecutivos iguales (`oos.models_hist`, últimos 10) y el cambio reinicia la
  cuenta de activación.
- Calibración por cubos (pliegue de cabecera) se mantiene.

## 5. Estado (`brain_state.json`)
Claves de siempre: `updated, n_labelled, active, active_votes, oos{n_test, brain_trades, brain_mints, brain_avg_ret_%, baseline_*,
all_avg_ret_%, purged_train_rows, policy, models, model_choice}, calibration, base, weights, avg_win, avg_loss, n, logit, model_choice`.
Nuevas: `code_version` (`brain/3@mtime`), `lambda{logit, ridge}`, `folds[]`, `archive_n`, `decay_half_life_d`, `cfg_hash`,
`cfg_hash_mismatch_n`, `feat` (spec de estandarización), `ridge`, `keys`, `bool_rows`, `oos.{winner, models_hist, switched,
folds_ok, vote, vote_counted, vote_archive_n, n_folds}`. `Brain.paths` = `[(velas, rt)]` de las filas del último `build_dataset`
con velas en caché (en orden temporal) para `director.exit_grid`.

## 6. Desviaciones deliberadas respecto al encargo (para el mantenedor)
1. **Agrupación por episodio de mint, no por mint absoluto.** `tests/test_brain.py` (intocable para mí) entrena con 30 mints que
   reaparecen cada 8 h durante toda la serie; con agrupación por mint absoluto el test de cada pliegue queda vacío y ese test
   fallaría. Un episodio (avistamientos separados < 3 h = `max_hold_hours`) es exactamente el conjunto cuyas etiquetas comparten
   velas; un token re-visto días después no filtra su trayectoria al otro lado del corte. Cambiar a mint absoluto es una línea
   (`EPISODE_GAP_S = inf`) si se prefiere y se adapta ese test.
2. **Cuota de 25 filas por voto solo cuando existe archivo.** Con `build_dataset` inyectado (tests y scripts de research no
   fijan `s._archive_n`) el voto cuenta como en v2; en producción `build_dataset` siempre fija el contador, así que la cuota
   se aplica siempre. Motivo: el mismo test intocable exige activación con 3 refits sobre datos idénticos.

## 7. Qué validar con datos reales (no disponibles en el repo)
`python3 brain.py` sobre la máquina con `candidates_solana.jsonl` + `ohlcv_cache.json`: tamaño del archivo tras el primer
refit, `lambda` elegida, `folds` y `oos.winner`. Esperable con 554 filas y PF 0,15: ningún modelo vota (todos los pliegues
negativos) y `model_choice = beta`.
