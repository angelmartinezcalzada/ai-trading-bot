# Bot de trading Binance (spot USDT): modo simulado por defecto

## Arquitectura
- **Universo dinámico**: todos los pares USDT spot con un volumen de 24 h de al menos `min_quote_volume_24h`, sin stablecoins ni tokens apalancados. Se refresca cada `universe_refresh_minutes`.
- **Escaneo eficiente**: en cada ciclo se pide `bookTicker` de todos los pares a la vez (1 llamada) y se calcula el momentum de 5 minutos de cada uno. El análisis completo (velas de 1m, 5m, 15m, 1h y 4h, más el libro de órdenes) solo se hace para los `deep_scan_top` pares que más se mueven.
- **Régimen de mercado** (cada 5 min), según BTC en 1h/4h: alcista si el precio está por encima de la EMA50 y esta por encima de la EMA200 con pendiente 4h positiva; bajista en el caso inverso; lateral en el resto. También mide la volatilidad (ATR%).
- **Estrategias según el régimen**:
  - `momentum` (alcista o lateral): subida de 5 min + pico de volumen + MACD subiendo, con confirmación de VWAP, ruptura de 30 min, RSI<78, al menos 3 de 4 marcos temporales alcistas y más fuerza que BTC.
  - `pullback` (solo alcista): 1h y 4h alcistas, precio a menos de 0,6% de un soporte, RSI5 entre 35 y 50, MACD girando al alza, más fuerza que BTC.
  - `mean_reversion` (solo lateral): precio por debajo de la banda inferior de Bollinger (2σ) en 5m, RSI5<30, MACD girando, 4h alcista.
  - Régimen **bajista**: no abre largos.
- **Filtros**: no entra si hay una resistencia a menos de 0,4%, si el libro de órdenes tiene un desequilibrio < -0,35 (mucha más venta que compra) o si hay un aviso de deslistado.
- **Noticias y sentimiento** (cada 10 min): índice Fear & Greed de alternative.me, titulares RSS (Cointelegraph, CoinDesk, Decrypt) con puntuación por palabras clave para cada moneda, y anuncios de Binance (nuevas listas y deslistados).
  - Noticias muy negativas sobre la moneda: no entra.
  - El tamaño se multiplica por el factor de Fear & Greed (0,5 a 1), por (1 + 0,1 × puntuación de noticias), por 1,2 si es un listado nuevo y por 0,7 si BTC está muy volátil.
- **Gestión de riesgo**: 10% del saldo por operación (interés compuesto), stop a 1,5 ATR, objetivo a 2,5 ATR × el factor de la estrategia, stop que sigue al precio desde +1 ATR, salida a los 45 min, máximo 3 posiciones, freno diario si se pierde un 5%, filtro de diferencia compra-venta (spread) y espera de 15 min por moneda.
- **Comprobaciones para el modo real**: `--live` + `mode=live` en la configuración + claves de API en el entorno + `LIVE_CONFIRM=YES`.

## Uso
- `./run_forever.sh` (lanzar con `nohup setsid ./run_forever.sh &`): servicio 24/7 que se reinicia solo si se cae.
- `./status.sh`: estado. `./stop.sh`: parar.
- `python3 bot.py --scan`: foto del momento.
- Archivos: `bot.log` (registro del bot), `supervisor.log` (arranques y reinicios), `trades_paper.csv` (operaciones), `summary.json` (resumen).

## v2 (multi-exchange)
See `PLAYBOOK.md`. Binance and Coinbase run as separate processes, each with its own balance. Strategies on: `momentum`, `trend_1h`, `pullback`. Entries are maker limit orders. Walk-forward results are in `bt_results.json`.
