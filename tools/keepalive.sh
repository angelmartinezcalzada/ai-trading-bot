#!/bin/bash
# Vigilante (02-nov): corre dentro de una sesión de WSL oculta que lanza Windows (acceso directo de Inicio, tools/autostart.sh).
# Mientras esta sesión exista, WSL no apaga la distro al cerrar la ventana de Ubuntu, así que el bot sigue vivo. Además, cada 30 s
# relanza el supervisor (run_forever.sh) si no corre y no hay fichero STOP (./stop.sh lo crea: un paro manual se respeta).
cd "$(dirname "$0")/.." || exit 1
exec 8>".keepalive.lock"; flock -n 8 || exit 0                    # un solo vigilante por máquina
echo "$(date -Is) [keepalive] activo (pid $$)" >> supervisor.log
while true; do
  if [ ! -f STOP ] && ! pgrep -f "run_foreve[r].sh" >/dev/null 2>&1; then
    echo "$(date -Is) [keepalive] supervisor parado: lo arranco" >> supervisor.log
    (setsid ./run_forever.sh >/dev/null 2>&1 < /dev/null &) 8>&-   # el supervisor no hereda el candado del vigilante
  fi
  sleep 30
done
