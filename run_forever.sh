#!/bin/bash
# 24/7 supervisor: one auto-restarting loop per exchange (+ dashboard + tunnel). Stop all with ./stop.sh
# Per-exchange stop: touch STOP_<ex> (dashboard does this). Live mode: exchanges.<ex>.mode=live AND keys in keys.env.
cd "$(dirname "$0")"
exec 9>".supervisor.lock"; flock -n 9 || { echo "$(date -Is) [supervisor] ya hay un run_forever.sh en marcha (lock); este no arranca" >> supervisor.log; exit 0; }   # single instance, whoever launches it
# 02-nov: every loop below runs with fd 9 CLOSED (9>&-): before, their `sleep 3600` children inherited the lock and, once stop.sh killed the
# supervisor, kept it for up to an hour, so the next supervisor (installer, autostart) refused to start. Only this process holds it now.
rm -f STOP; export PATH="$HOME/bin:$PATH"
for EX in $(python3 -c "import json;print(' '.join(json.load(open('config.json'))['exchanges']))"); do
  ( while [ ! -f STOP ]; do
      if [ -f "STOP_$EX" ]; then sleep 3; continue; fi
      MODE=$(python3 -c "import json;print(json.load(open('config.json'))['exchanges']['$EX'].get('mode','paper'))")
      ARGS=""
      if [ "$MODE" = "live" ] && [ -f keys.env ]; then set -a; . ./keys.env; set +a; export LIVE_CONFIRM=YES; ARGS="--live"; fi
      echo "$(date -Is) [$EX] start mode=$MODE" >> supervisor.log
      T0=$(date +%s); python3 bot.py --exchange "$EX" $ARGS >> "stdout_$EX.log" 2>&1; RC=$?
      echo "$(date -Is) [$EX] exited code $RC" >> supervisor.log
      if [ $(( $(date +%s) - T0 )) -lt 15 ]; then sleep 60; else sleep 5; fi   # died at startup (duplicate, missing module...): do not churn every 5 s
    done ) 9>&- &
done
( while [ ! -f STOP ]; do echo "$(date -Is) [dashboard] start" >> supervisor.log; python3 dashboard.py >> stdout_dashboard.log 2>&1; sleep 5; done ) 9>&- &
( while [ ! -f STOP ]; do echo "$(date -Is) [insider] start" >> supervisor.log; python3 insider.py daemon >> stdout_insider.log 2>&1; sleep 10; done ) 9>&- &
# Insider en tiempo real (insider_ws.py): WebSocket de Solana sobre las wallets seguidas; solo si el paquete websockets está instalado
( while [ ! -f STOP ]; do python3 -c "import websockets" 2>/dev/null || { sleep 3600; continue; }; echo "$(date -Is) [insider_ws] start" >> supervisor.log; python3 insider_ws.py >> stdout_insider_ws.log 2>&1; sleep 10; done ) 9>&- &
# Tendencia sobre tokens líquidos (trend_spot.py): papel; evalúa una vez al día y marca cada 15 min
( while [ ! -f STOP ]; do echo "$(date -Is) [trend] start" >> supervisor.log; python3 trend_spot.py --loop >> stdout_trend.log 2>&1; sleep 30; done ) 9>&- &
# Solana Tracker en sombra (st_shadow_daemon.py, de Grok 1-nov): solo si keys.env tiene SOLANATRACKER_API_KEY
( while [ ! -f STOP ]; do if [ -f keys.env ] && grep -q '^SOLANATRACKER_API_KEY=.' keys.env; then pgrep -f "python3 st_shadow_daemo[n].py" >/dev/null && { sleep 60; continue; }; echo "$(date -Is) [st_shadow] start" >> supervisor.log; SOLANATRACKER_API_KEY="$(grep '^SOLANATRACKER_API_KEY=' keys.env | head -1 | cut -d= -f2-)" python3 st_shadow_daemon.py >> stdout_st_shadow.log 2>&1; fi; sleep 60; done ) 9>&- &   # only this key, not every secret in keys.env
# Operador automático (operador.py): revisión horaria, acciones seguras (rent de ATAs, procesos colgados, Director, logs), DECISIONS.md, alertas
( sleep 120; while [ ! -f STOP ]; do echo "$(date -Is) [operator] review" >> supervisor.log
    ( [ -f keys.env ] && grep -q '^ALERT_CMD=.' keys.env && export ALERT_CMD="$(grep '^ALERT_CMD=' keys.env | head -1 | cut -d= -f2- | sed "s/^'//;s/'$//")"; python3 operador.py --once >> stdout_operator.log 2>&1 )
    sleep 3600; done ) 9>&- &
# Contexto de mercado horario (context.py): SOL/BTC, F&G, riesgo-off, calor de lanzamientos, amplitud -> data/context_now.json (cerebro, Director, operador, panel)
( sleep 30; while [ ! -f STOP ]; do [ -f context.py ] && { echo "$(date -Is) [context] once" >> supervisor.log; timeout 300 python3 context.py --once >> stdout_context.log 2>&1; }; sleep 3600; done ) 9>&- &
# Hyperliquid context logger (Coinversa) - only when keys.env has COINVERSA_API_KEY; never trades
( while [ ! -f STOP ]; do
    if [ -f keys.env ] && grep -q '^COINVERSA_API_KEY=.' keys.env; then
      echo "$(date -Is) [hl_context] start" >> supervisor.log
      COINVERSA_API_KEY="$(grep '^COINVERSA_API_KEY=' keys.env | head -1 | cut -d= -f2-)" python3 -m hl_leg.hl_context >> stdout_hl_context.log 2>&1   # only this key, not every secret in keys.env
    fi; sleep 3600; done ) 9>&- &
[ -f ENABLE_TUNNEL ] && ( while [ ! -f STOP ]; do
    echo "$(date -Is) [tunnel] start" >> supervisor.log
    cloudflared tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8787 > tunnel.log 2>&1 & TP=$!
    for i in $(seq 1 30); do U=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' tunnel.log | head -1); [ -n "$U" ] && break; sleep 2; done
    [ -n "$U" ] && echo "$U" > tunnel_url.txt && echo "$(date -Is) [tunnel] $U" >> supervisor.log
    wait $TP; sleep 5
  done ) 9>&- &
# Tailscale en espacio de usuario: solo en máquinas que lo tengan instalado en ~/bin (la de Grok); en un PC normal no hace nada
[ -x "$HOME/bin/tailscaled" ] && mkdir -p "$HOME/.tailscale" && ( while [ ! -f STOP ]; do pgrep -f "tailscaled --tun=userspace" >/dev/null || (setsid ~/bin/tailscaled --tun=userspace-networking --statedir=$HOME/.tailscale --socket=$HOME/.tailscale/tailscaled.sock >> ~/.tailscale/tailscaled.log 2>&1 &); sleep 60; done ) 9>&- &
wait
