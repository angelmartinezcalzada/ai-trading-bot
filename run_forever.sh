#!/bin/bash
# 24/7 supervisor: one auto-restarting loop per exchange (+ dashboard + tunnel). Stop all with ./stop.sh
# Per-exchange stop: touch STOP_<ex> (dashboard does this). Live mode: exchanges.<ex>.mode=live AND keys in keys.env.
cd "$(dirname "$0")"; rm -f STOP; export PATH="$HOME/bin:$PATH"
for EX in $(python3 -c "import json;print(' '.join(json.load(open('config.json'))['exchanges']))"); do
  ( while [ ! -f STOP ]; do
      if [ -f "STOP_$EX" ]; then sleep 3; continue; fi
      MODE=$(python3 -c "import json;print(json.load(open('config.json'))['exchanges']['$EX'].get('mode','paper'))")
      ARGS=""
      if [ "$MODE" = "live" ] && [ -f keys.env ]; then set -a; . ./keys.env; set +a; export LIVE_CONFIRM=YES; ARGS="--live"; fi
      echo "$(date -Is) [$EX] start mode=$MODE" >> supervisor.log
      python3 bot.py --exchange "$EX" $ARGS >> "stdout_$EX.log" 2>&1; RC=$?
      echo "$(date -Is) [$EX] exited code $RC" >> supervisor.log; sleep 5
    done ) &
done
( while [ ! -f STOP ]; do echo "$(date -Is) [dashboard] start" >> supervisor.log; python3 dashboard.py >> stdout_dashboard.log 2>&1; sleep 5; done ) &
( while [ ! -f STOP ]; do echo "$(date -Is) [insider] start" >> supervisor.log; python3 insider.py daemon >> stdout_insider.log 2>&1; sleep 10; done ) &
# Operador automático (operador.py): revisión horaria, acciones seguras (rent de ATAs, procesos colgados, Director, logs), DECISIONS.md, alertas
( sleep 120; while [ ! -f STOP ]; do echo "$(date -Is) [operator] review" >> supervisor.log
    ( [ -f keys.env ] && grep -q '^ALERT_CMD=.' keys.env && export ALERT_CMD="$(grep '^ALERT_CMD=' keys.env | head -1 | cut -d= -f2- | sed "s/^'//;s/'$//")"; python3 operador.py --once >> stdout_operator.log 2>&1 )
    sleep 3600; done ) &
# Hyperliquid context logger (Coinversa) - only when keys.env has COINVERSA_API_KEY; never trades
( while [ ! -f STOP ]; do
    if [ -f keys.env ] && grep -q '^COINVERSA_API_KEY=.' keys.env; then
      echo "$(date -Is) [hl_context] start" >> supervisor.log
      COINVERSA_API_KEY="$(grep '^COINVERSA_API_KEY=' keys.env | head -1 | cut -d= -f2-)" python3 -m hl_leg.hl_context >> stdout_hl_context.log 2>&1   # only this key, not every secret in keys.env
    fi; sleep 3600; done ) &
[ -f ENABLE_TUNNEL ] && ( while [ ! -f STOP ]; do
    echo "$(date -Is) [tunnel] start" >> supervisor.log
    cloudflared tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8787 > tunnel.log 2>&1 & TP=$!
    for i in $(seq 1 30); do U=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' tunnel.log | head -1); [ -n "$U" ] && break; sleep 2; done
    [ -n "$U" ] && echo "$U" > tunnel_url.txt && echo "$(date -Is) [tunnel] $U" >> supervisor.log
    wait $TP; sleep 5
  done ) &
( while [ ! -f STOP ]; do pgrep -f "tailscaled --tun=userspace" >/dev/null || (setsid ~/bin/tailscaled --tun=userspace-networking --statedir=$HOME/.tailscale --socket=$HOME/.tailscale/tailscaled.sock >> ~/.tailscale/tailscaled.log 2>&1 &); sleep 60; done ) &
wait
