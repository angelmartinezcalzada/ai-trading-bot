#!/bin/bash
# Arranque 24/7 en Windows + WSL SIN permisos de administrador (02-nov).
# Problema que resuelve: un bot lanzado desde la ventana de Ubuntu muere cuando cierras la ventana (WSL apaga la distro) y no vuelve
# tras reiniciar. Solución: un .vbs en la carpeta Inicio de Windows lanza, oculta, una sesión de WSL que ejecuta run_forever.sh y la
# mantiene abierta (run_forever.sh termina en `wait`). El bot sigue vivo con la ventana cerrada y arranca solo al iniciar sesión.
# Uso: tools/autostart.sh on | off | start | status        (on = instalar + arrancar ahora; off = quitar el arranque automático)
set -u
cd "$(dirname "$0")/.." || exit 1
DIR="$(pwd)"; NAME="TradingBot.vbs"; MARK=".autostart"
win_env() { (cd /mnt/c 2>/dev/null; cmd.exe /c "echo %$1%" 2>/dev/null) | tr -d '\r'; }
startup_dir() {
  command -v cmd.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1 || return 1
  local ad; ad="$(win_env APPDATA)"; [ -n "$ad" ] && [ "$ad" != "%APPDATA%" ] || return 1
  local p; p="$(wslpath -u "$ad")/Microsoft/Windows/Start Menu/Programs/Startup"; [ -d "$p" ] || return 1; printf '%s' "$p"
}
running() { pgrep -f "run_foreve[r].sh" >/dev/null 2>&1; }
start_hidden() {   # $1 = linux path of the .vbs
  (cd /mnt/c 2>/dev/null; wscript.exe "$(wslpath -w "$1")" >/dev/null 2>&1) || return 1
  for _ in $(seq 1 20); do running && return 0; sleep 1; done; return 1
}
case "${1:-status}" in
  on)
    [ -n "${WSL_DISTRO_NAME:-}" ] || { echo "autostart: no estoy dentro de WSL; en Linux usa systemd o cron @reboot"; exit 2; }
    SD="$(startup_dir)" || { echo "autostart: no puedo acceder a Windows desde WSL (interop desactivado); alternativa: windows/tarea.ps1 como administrador"; exit 2; }
    U="$(id -un)"; V="$SD/$NAME"
    printf "' Bot de trading: arranca oculto dentro de WSL al iniciar sesion (lo instalo %s/tools/autostart.sh; quitar: tools/autostart.sh off)\r\nCreateObject(\"WScript.Shell\").Run \"wsl.exe -d \"\"%s\"\" -u %s -e bash -lc \"\"cd '%s' && exec ./run_forever.sh\"\"\", 0, False\r\n" \
      "$DIR" "$WSL_DISTRO_NAME" "$U" "$DIR" > "$V" || { echo "autostart: no pude escribir $V"; exit 1; }
    printf '%s\n' "$V" > "$MARK"
    echo "autostart: instalado en la carpeta Inicio de Windows ($NAME)"
    if running; then echo "autostart: run_forever.sh ya corre (si cuelga de esta ventana, para todo con ./stop.sh y vuelve a ejecutar: tools/autostart.sh start)"; exit 0; fi
    start_hidden "$V" && { echo "autostart: bot arrancado en segundo plano; puedes cerrar la ventana de Ubuntu"; exit 0; }
    echo "autostart: el .vbs no arrancó el bot (¿wscript bloqueado?)"; exit 1 ;;
  start)
    V="$(cat "$MARK" 2>/dev/null)"; [ -n "$V" ] && [ -f "$V" ] || { echo "autostart: no instalado (tools/autostart.sh on)"; exit 1; }
    running && { echo "autostart: run_forever.sh ya corre"; exit 0; }
    start_hidden "$V" && { echo "autostart: bot arrancado en segundo plano"; exit 0; }; echo "autostart: no arrancó"; exit 1 ;;
  off)
    V="$(cat "$MARK" 2>/dev/null)"; [ -n "$V" ] && rm -f "$V"; rm -f "$MARK"
    echo "autostart: quitado (el bot actual sigue corriendo; para pararlo: ./stop.sh)" ;;
  status)
    V="$(cat "$MARK" 2>/dev/null)"
    if [ -n "$V" ] && [ -f "$V" ]; then echo "autostart: instalado ($V)"; else echo "autostart: NO instalado"; fi
    running && echo "supervisor: corriendo" || echo "supervisor: parado" ;;
  *) echo "uso: tools/autostart.sh on | off | start | status"; exit 2 ;;
esac
