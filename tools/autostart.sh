#!/bin/bash
# Arranque 24/7 en Windows + WSL SIN permisos de administrador (02-nov, v2).
# Problema: un bot lanzado desde la ventana de Ubuntu muere al cerrarla (WSL apaga la distro) y no vuelve tras reiniciar.
# Solución (v3): un acceso directo "TradingBot" en la carpeta Inicio de Windows que lanza, oculta, una sesión de WSL con el vigilante
# tools/keepalive.sh: mientras esa sesión exista la distro sigue viva con la ventana cerrada, y el vigilante relanza el supervisor si no
# corre. El instalador arranca el supervisor al momento por su cuenta, así que el vigilante puede tardar (PowerShell la primera vez
# tarda en "preparar módulos") sin carreras. El acceso directo se crea con PowerShell (sin VBScript; .vbs solo de respaldo).
# Uso: tools/autostart.sh on | off | start | status
set -u
cd "$(dirname "$0")/.." || exit 1
DIR="$(pwd)"; MARK=".autostart"; U="$(id -un)"; DISTRO="${WSL_DISTRO_NAME:-}"
running() { pgrep -f "run_foreve[r].sh" >/dev/null 2>&1; }
keeper() { pgrep -f "keepaliv[e].sh" >/dev/null 2>&1; }
wait_keeper() { for i in $(seq 1 "${1:-90}"); do keeper && return 0; [ $((i % 15)) -eq 0 ] && echo "  … esperando al vigilante ($i s)"; sleep 1; done; return 1; }
win() { (cd /mnt/c 2>/dev/null && "$@") 2>&1 | tr -d '\r'; }
ps_run() { local b; b="$(printf '%s' "\$ProgressPreference='SilentlyContinue'; $1" | iconv -f UTF-8 -t UTF-16LE | base64 -w0)"; win powershell.exe -NoProfile -NonInteractive -EncodedCommand "$b"; }
ps_err() { sed -e 's/_x000D__x000A_/ /g' | grep -o '<S S="Error">[^<]*' | sed 's/<S S="Error">//' | tr -s ' ' | head -c 300; }   # readable error out of CLIXML
startup_dir() {
  local ad; ad="$(win cmd.exe /c 'echo %APPDATA%')"; [ -n "$ad" ] && [ "$ad" != "%APPDATA%" ] || return 1
  local p; p="$(wslpath -u "$ad")/Microsoft/Windows/Start Menu/Programs/Startup"; [ -d "$p" ] || return 1; printf '%s' "$p"
}
start_ps() { printf "Start-Process wsl.exe -WindowStyle Hidden -ArgumentList '-d \"%s\" -u %s -e bash -lc \"cd %s && exec tools/keepalive.sh\"'" "$DISTRO" "$U" "$DIR"; }
launch() {   # $1 = linux path of the startup entry (.lnk or .vbs): starts the hidden keepalive session; each way verified
  local w e; w="$(wslpath -w "$1")"
  win explorer.exe "$w" >/dev/null; wait_keeper 90 && { echo "autostart: vigilante arrancado vía explorador de Windows"; return 0; }
  echo "autostart: el explorador no lo arrancó; pruebo con PowerShell"
  e="$(ps_run "$(start_ps)" | ps_err)"; [ -n "$e" ] && echo "  powershell: $e"
  wait_keeper 90 && { echo "autostart: vigilante arrancado vía PowerShell"; return 0; }
  if [ "${1##*.}" = "vbs" ]; then e="$(win wscript.exe "$w")"; [ -n "$e" ] && echo "  wscript: ${e:0:300}"; wait_keeper 60 && { echo "autostart: vigilante arrancado vía wscript"; return 0; }; fi
  echo "autostart: el vigilante no arrancó. Últimas líneas de supervisor.log:"; tail -n 5 supervisor.log 2>/dev/null | sed 's/^/  /'
  return 1
}
make_lnk() {   # -> prints the linux path of the created TradingBot.lnk
  local b; b="$(start_ps | iconv -f UTF-8 -t UTF-16LE | base64 -w0)"
  local ps="\$ErrorActionPreference='Stop'; \$l=Join-Path ([Environment]::GetFolderPath('Startup')) 'TradingBot.lnk'; \$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\$l); \$s.TargetPath=Join-Path \$env:SystemRoot 'System32\\WindowsPowerShell\\v1.0\\powershell.exe'; \$s.Arguments='-NoProfile -WindowStyle Hidden -EncodedCommand $b'; \$s.WindowStyle=7; \$s.Description='Bot de trading (WSL): arranca run_forever.sh oculto'; \$s.Save(); [Console]::Out.Write(\$l)"
  local out w; out="$(ps_run "$ps")"; w="$(printf '%s\n' "$out" | grep -o '[A-Za-z]:\\.*TradingBot\.lnk' | tail -n 1)"   # path among any PowerShell noise (CLIXML, warnings)
  if [ -n "$w" ]; then local p; p="$(wslpath -u "$w")"; [ -f "$p" ] && { printf '%s' "$p"; return 0; }; fi
  echo "autostart: PowerShell no creó el acceso directo: $(printf '%s' "$out" | ps_err)" >&2; return 1
}
make_vbs() {   # $1 = startup dir -> prints the linux path of TradingBot.vbs
  local v="$1/TradingBot.vbs"
  printf "' Bot de trading: arranca oculto dentro de WSL al iniciar sesion (quitar: tools/autostart.sh off)\r\nCreateObject(\"WScript.Shell\").Run \"wsl.exe -d \"\"%s\"\" -u %s -e bash -lc \"\"cd %s && exec tools/keepalive.sh\"\"\", 0, False\r\n" "$DISTRO" "$U" "$DIR" > "$v" && printf '%s' "$v"
}
case "${1:-status}" in
  on)
    [ -n "$DISTRO" ] || { echo "autostart: no estoy dentro de WSL; en Linux usa systemd o cron @reboot"; exit 2; }
    command -v cmd.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1 || { echo "autostart: no puedo usar Windows desde WSL (interop desactivado); alternativa: windows/tarea.ps1 como administrador"; exit 2; }
    [[ "$DIR" =~ ^[A-Za-z0-9_./-]+$ && "$DISTRO" =~ ^[A-Za-z0-9._-]+$ && "$U" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "autostart: ruta, usuario o distro con caracteres raros ($DIR / $U / $DISTRO); usa windows/tarea.ps1"; exit 2; }
    SD="$(startup_dir)" || { echo "autostart: no encuentro la carpeta Inicio de Windows"; exit 2; }
    if E="$(make_lnk)"; then rm -f "$SD/TradingBot.vbs"; echo "autostart: acceso directo 'TradingBot' creado en la carpeta Inicio de Windows"
    else E="$(make_vbs "$SD")" || { echo "autostart: no pude escribir en la carpeta Inicio"; exit 1; }; echo "autostart: creado TradingBot.vbs en la carpeta Inicio (PowerShell no disponible)"; fi
    printf '%s\n' "$E" > "$MARK"
    keeper && { echo "autostart: el vigilante ya corre"; exit 0; }
    launch "$E" && { echo "autostart: listo; puedes cerrar la ventana de Ubuntu"; exit 0; }; exit 1 ;;
  start)
    E="$(head -n 1 "$MARK" 2>/dev/null)"; [ -n "$E" ] && [ -f "$E" ] || { echo "autostart: no instalado (tools/autostart.sh on)"; exit 1; }
    keeper && { echo "autostart: el vigilante ya corre"; exit 0; }
    launch "$E" ;;
  off)
    SD="$(startup_dir 2>/dev/null)"; [ -n "$SD" ] && rm -f "$SD/TradingBot.lnk" "$SD/TradingBot.vbs"
    E="$(head -n 1 "$MARK" 2>/dev/null)"; [ -n "$E" ] && rm -f "$E"; rm -f "$MARK"; pkill -f "keepaliv[e].sh" 2>/dev/null
    echo "autostart: quitado y vigilante parado (el bot sigue corriendo hasta que cierres la ventana o ejecutes ./stop.sh)" ;;
  status)
    E="$(head -n 1 "$MARK" 2>/dev/null)"
    if [ -n "$E" ] && [ -f "$E" ]; then echo "autostart: instalado ($E)"; else echo "autostart: NO instalado"; fi
    keeper && echo "vigilante: corriendo" || echo "vigilante: parado"
    running && echo "supervisor: corriendo" || echo "supervisor: parado" ;;
  *) echo "uso: tools/autostart.sh on | off | start | status"; exit 2 ;;
esac
