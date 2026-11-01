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
| 1 h | **operador**: revisión de salud, equity, escaneo, errores; acciones seguras; entrada en `DECISIONS.md`; alertas | tarjeta "Operador automático" del panel, `alerts.jsonl` |
| 1 día (08:00) | informe diario con lo que queda por decidir | `DECISIONS.md` |
| 1 h | contexto Coinversa de Hyperliquid (si hay `COINVERSA_API_KEY`) | `data/hl_risk.json`, panel |
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

Historial y razones de todo: `DECISIONS.md` (lo escribe el operador cada hora), `director_log.jsonl`, `operator_log.jsonl`.
