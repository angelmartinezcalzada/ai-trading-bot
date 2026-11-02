# Operación del bot autosuficiente (para Àngel)

Desde el 1-nov-2026 el bot se opera solo. No hay operador externo: lo que hacía la revisión horaria (salud, patrimonio,
escaneos, errores, registro en `DECISIONS.md`, cierre de cuentas de token, informe diario) lo hace `operador.py` desde
`run_forever.sh`. Tú solo tomas las decisiones que son tuyas (abajo) y miras el panel cuando quieras.

## 1. Arranque en una máquina nueva (3 comandos)

```bash
git clone -b claude/trading-bot-mvp https://github.com/angelmartinezcalzada/Angel-proyectos.git
cd Angel-proyectos/ai-trading-bot && ./install.sh          # dependencias, keys.env vacío, contraseña del panel, tests
nohup setsid ./run_forever.sh >/dev/null 2>&1 &            # 24/7: bots, insider, panel, operador, (túnel y Coinversa si hay claves)
```

Antes de arrancar en real: copia `solana_wallet.json` (chmod 600) y pon `exchanges.solana.mode` a `"live"` en `config.json`.
Sin wallet el bot de Solana corre en papel. Las claves de Binance/Coinbase/Coinversa van en `keys.env`.

Migración desde la instalación actual (`/workspace/ai-trading-bot`): `./stop.sh` en la vieja, copia `solana_wallet.json`,
`keys.env`, `dashboard_password.txt`, `config.json`, `state_*.json`, `trades_*.csv`, `equity_*.csv`, `candidates_solana.jsonl`,
`ohlcv_cache.json`, `brain_state.json`, `insider_*.json`, `DECISIONS.md` y la carpeta `data/` a la nueva, y arranca.

## 1b. En tu PC con Windows (WSL), tres pasos

1. PowerShell **como administrador** (botón derecho sobre PowerShell → "Ejecutar como administrador"):
   ```powershell
   wsl --install -d Ubuntu
   ```
   Reinicia cuando lo pida. Al abrir "Ubuntu" por primera vez te pedirá un nombre de usuario y una contraseña (invéntalos y apúntalos).
2. En la ventana de **Ubuntu** (no en PowerShell), pega:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/angelmartinezcalzada/ai-trading-bot/main/wsl_bootstrap.sh | bash
   ```
   Instala lo necesario, pasa los tests y arranca el bot. Al final imprime la contraseña del panel.
3. **Para que siga corriendo con la ventana cerrada y arranque solo con Windows** (si no, WSL mata los procesos al cerrar Ubuntu):
   PowerShell **como administrador**:
   ```powershell
   irm https://raw.githubusercontent.com/angelmartinezcalzada/ai-trading-bot/main/windows/tarea.ps1 | iex
   ```
   Crea la tarea "TradingBot" del Programador de tareas. Parar: `Stop-ScheduledTask -TaskName TradingBot`; arrancar: `Start-ScheduledTask -TaskName TradingBot`.
4. Abre en el navegador de Windows `http://localhost:8787/`.

Sin `solana_wallet.json` el bot de Solana opera en **papel** (sin dinero). Cuando recuperes el wallet de la máquina de Grok,
cópialo a `~/ai-trading-bot/solana_wallet.json` dentro de Ubuntu (`chmod 600`), pon `"mode": "live"` en `config.json` y reinicia
(`./stop.sh` y `nohup setsid ./run_forever.sh >/dev/null 2>&1 &`). Para que opere 24/7 el PC no puede suspenderse.
Repetir el comando del paso 2 más adelante actualiza el bot a la última versión sin perder nada.

## 2. Qué hace solo y qué no

| Cada | Qué | Dónde se ve |
|---|---|---|
| 8-45 s | escanea, veta (RugCheck/GoPlus/Jupiter), decide con el cerebro y el Director, compra/vende, cierra la cuenta de token tras vender | `bot_solana.log`, panel |
| 1 h | reentrena el cerebro (walk-forward purgado), recalcula el Director (jugadas, umbrales, tamaño, horas, salida, tope diario) | `brain_state.json`, `director_state.json`, panel |
| 1 h | **operador**: revisión de salud, equity, escaneo, errores; acciones seguras; entrada en `DIARIO.md`; alertas | tarjeta "Operador automático" del panel, `alerts.jsonl` |
| 1 día (08:00) | informe diario con lo que queda por decidir | `DIARIO.md` |
| 1 h | contexto Coinversa de Hyperliquid (si hay `COINVERSA_API_KEY`) | `data/hl_risk.json`, panel |
| diario | **tendencia sobre tokens líquidos** (`trend_spot.py`, papel): la regla validada en Keel (SuperTrend + Bollinger + ATR) sobre los tokens de Solana con más volumen; evalúa tras el cierre UTC, marca cada 15 min; el Director la apaga si pierde; a real solo con `trend_live: true` tras 20 cierres con PF > 1,3 | tarjeta "Tendencia", `trades_solana_trend_paper.csv` |
| continuo | **agente insider**: `insider.py` mina y puntúa wallets (elite/good), `insider_ws.py` las escucha por WebSocket (segundos en vez de 70-130 s), convergencia de compras → alerta → entrada solo si pasa todos los vetos; validación forward de cada alerta | tarjeta Insiders del panel (`tiempo real: ● socket`), `insider_status.json` |

Acciones que el operador toma solo (todas reversibles): cerrar cuentas de token vacías (rent de vuelta al wallet, máx. cada 6 h),
reiniciar un proceso vivo pero mudo > 10 min (una vez por hora, nunca si hay `STOP_<ex>`), recalcular el Director si falta o
tiene > 2 h, recortar logs > 50 MB. El Director solo **endurece**: menos jugadas, más umbral, menos tamaño, stop más cerrado,
menos horas, tope diario. Las primeras 24 h va en sombra.

Lo que **nunca** hace nada automático: relajar vetos, tamaños o stops; cambiar papel↔real; activar el pump real; tocar
`config.json`; mover fondos; pasar la pata Hyperliquid a real en Keel.

## 3. Decisiones que siguen siendo tuyas

1. **Rent de las cuentas de token** (~4,7 $ bloqueados en ~24 cuentas): el operador las cierra solo en modo real y con wallet.
   Si prefieres hacerlo tú: `python3 tools/close_atas.py` (lista) y `python3 tools/close_atas.py --yes`.
2. **Memebot a papel** si el PF real a 30 días sigue por debajo de 1 (el informe diario lo propone, no lo aplica):
   `config.json` → `exchanges.solana.mode: "paper"`.
3. **Director al mando o en sombra**: sale de la sombra a las 24 h; `director_enabled: false` lo deja en sombra para siempre.
4. **Hyperliquid real**: solo en la web de Keel, con ≥150 $ y ≥21 días / ≥20 evaluaciones de paper con paridad (ver `hl_leg/hl_paper.json`).
5. **Clave expuesta** (pegada en un chat, guardada en otra máquina): rota el wallet. Con el bot parado y sin posiciones:
   `python3 tools/wallet_rotar.py --nuevo` (crea uno que solo existe en tu PC), `python3 tools/wallet_rotar.py --mover` (dry run)
   y `--mover --yes` (cierra cuentas vacías, mueve todo el SOL al nuevo y lo activa). La clave vieja deja de valer nada.
6. **Alertas**: pon en `keys.env` `ALERT_CMD='curl -s -X POST --data-binary @- https://…'` (o un bot de Telegram) y recibirás cada aviso.

## 4. Mirar el bot

- Panel: `http://127.0.0.1:8787/` (o la URL de `tunnel_url.txt` si `ENABLE_TUNNEL` existe). Contraseña en `dashboard_password.txt`.
  Cada tarjeta lleva la hora de su dato; "sin datos" u "obsoleto" significa exactamente eso, nunca un número inventado.
- `./status.sh` (procesos y últimas operaciones) · `python3 operador.py --once --dry-run` (revisión manual sin escribir)
  · `python3 director.py --report` (qué está decidiendo el Director y por qué) · `tail -f bot_solana.log`.
- Parar todo: `./stop.sh`. Parar solo una pata: `touch STOP_solana` (y borrarlo para reanudar). Kill switch: desde el panel (escribir KILL).

## 5. Si algo va mal

| Síntoma | Qué mirar | Qué hacer |
|---|---|---|
| Tarjeta Operador en rojo "sin proceso" | `supervisor.log`, `stdout_<ex>.log` | `run_forever` relanza solo; si se repite, `./stop.sh` y `nohup setsid ./run_forever.sh …` |
| "SOL insuficiente para comisiones" | wallet < `live_min_sol` | ingresar SOL o pasar a papel |
| Posición con `sellfail`/`noroute` | panel, posiciones | el bot reintenta con back-off; tras evidencia de token muerto la da de baja (write-off) |
| Escaneos lentos / RugCheck caído | tarjeta Escaneo | el presupuesto de 150 s y el fallback GoPlus ya limitan el daño; nada que hacer salvo esperar |
| El Director apaga la jugada `scanner` | `director_log.jsonl`, `--report` | es la evidencia (PF < 1 con n ≥ 15): el bot no compra; decide si pasar a papel |

Historial y razones de todo: `DIARIO.md` (lo escribe el operador cada hora, solo en tu máquina), `DECISIONS.md` (decisiones de diseño, en el repo), `director_log.jsonl`, `operator_log.jsonl`.

## Solana Tracker: imprescindible para comprar en real
Mientras el cerebro está en sombra (las primeras semanas), la única puerta de compra real es la ALT, que exige el veredicto de Solana Tracker. **Sin `SOLANATRACKER_API_KEY` en `keys.env` el bot real escanea y aprende, pero no compra nunca.** Crea una cuenta en solanatracker.io, genera una clave de la Data API (el plan gratuito, ~10k peticiones/mes, basta: el bot gasta como mucho 300/día) y guárdala así, sin pegarla nunca en chats ni en el repositorio:

```bash
cd ~/ai-trading-bot && read -r -p "Pega la clave de Solana Tracker: " K && sed -i "s|^SOLANATRACKER_API_KEY=.*|SOLANATRACKER_API_KEY=$K|" keys.env && chmod 600 keys.env && echo "guardada ($(grep -c '^SOLANATRACKER_API_KEY=.' keys.env) clave)"
```

No hace falta reiniciar: el bot lee `keys.env` en cada consulta y el supervisor arranca el daemon de sombra de Solana Tracker en menos de un minuto. En `bot_solana.log` dejarás de ver "ALT gate ... skipped: Solana Tracker verdict neutral/missing" en los candidatos con puntuación ≥ 45.

## Insiders fiables, cerebro v3 y contexto de mercado (02-nov)
Tres piezas nuevas, todas solo añaden información o endurecen; ninguna puede abrir una operación por sí sola.

- **Ranking de fiabilidad de wallets** (`insider_rank.py` → `insider_rank.json`, se recalcula en cada construcción del daemon de insiders, cada 20 min). Mide cada wallet con prior informativo, decaimiento de 7 días, cota inferior (percentil 20) de su tasa de acierto, filtro de bots/francotiradores (una wallet presente en más del 10 % de los lanzamientos es un bot, no un insider), colapso por clúster de financiación, historial real de PnL (Solana Tracker, tope `ST_INSIDER_CAP` 40 consultas/día) y la pista en vivo a 1 h. Elite exige que la cota inferior supere la tasa base de acierto de los compradores tempranos en 2 puntos (con tasa base 0,6: unos 7-8 aciertos recientes y como mucho 1 fallo); dos aciertos sueltos solo dan "watch". Subir más de un nivel de golpe (o una wallet nueva) espera una construcción más; bajar es inmediato. El seguidor en vivo y el WebSocket siguen el orden de este ranking, y la convergencia cuenta clústeres distintos, no direcciones. Ver la tabla: `python3 insider_rank.py --top 20` o la tarjeta Insiders del panel.
- **Cerebro v3** (`brain.py`): archivo de etiquetas que ya no se olvida (`data/labels_solana.jsonl`, una etiqueta por candidato, pesos con vida media de 10 días), etiquetado con la configuración base (no la endurecida por el Director), rasgos continuos y de contexto para los modelos logístico y de retorno (ridge con cota inferior), validación en 3 cortes temporales sin mezclar mints y con embargo de 3 h, voto solo con 25 filas nuevas y cambio de modelo solo tras dos victorias seguidas. La puerta de activación no se ha aflojado: sigue necesitando batir a la regla base fuera de muestra, en todos los cortes, tres veces seguidas.
- **Contexto horario** (`context.py --once`, lo lanza el supervisor cada hora → `data/context_now.json` y `data/context.jsonl`): SOL y BTC (retornos 1 h/4 h/24 h, volatilidad), régimen de BTC, noticias y Fear & Greed, lanzamientos y graduaciones por hora con "calor" frente a la mediana de 7 días, amplitud de tendencia de los tokens líquidos, salud de los módulos. Lo consumen el memebot (cada candidato queda sellado con su contexto; solo endurece: si el contexto dice riesgo-off, se respeta), el cerebro (rasgos), el Director (puerta de régimen: un régimen con ≥ 10 filas y retorno medio negativo se cierra; sin contexto fresco, cerrado), el operador (línea "Mercado" y avisos `context_stale`, `news_riskoff_6h`, `market_dead`) y el panel (tarjeta "Contexto de mercado"). Ver: `python3 context.py --show`.

Nada de esto cambia tamaños, stops ni vetos. Lo que cambia es que cada decisión queda registrada con su contexto y que, con el tiempo, el cerebro y el Director tienen más evidencia propia para abrir o cerrar jugadas.
