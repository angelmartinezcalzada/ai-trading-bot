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
TASK="TradingBotVigilante"
ka_args() { printf -- '-d "%s" -u %s -e bash -lc "cd %s && exec tools/keepalive.sh"' "$DISTRO" "$U" "$DIR"; }
make_task() {   # $1 = with_conhost (1: hidden through conhost --headless; 0: plain wsl.exe, visible console) -> registers + starts the task
  local exe arg
  if [ "$1" = 1 ]; then exe="\$env:SystemRoot\\System32\\conhost.exe"; arg="--headless wsl.exe $(ka_args)"   # inside the single-quoted -Argument nothing expands: plain wsl.exe (PATH)
  else exe="\$env:SystemRoot\\System32\\wsl.exe"; arg="$(ka_args)"; fi
  arg="${arg//\'/\'\'}"   # single quotes doubled for the PowerShell literal
  ps_run "\$ErrorActionPreference='Stop'; \$a=New-ScheduledTaskAction -Execute \"$exe\" -Argument '$arg'; \$t=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration ([TimeSpan]::FromDays(3650)); \$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew; Register-ScheduledTask -TaskName '$TASK' -Action \$a -Trigger \$t -Settings \$s -Force | Out-Null; Start-ScheduledTask -TaskName '$TASK'; 'TASK_OK'"
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
    SD="$(startup_dir 2>/dev/null)"; [ -n "$SD" ] && rm -f "$SD/TradingBot.lnk" "$SD/TradingBot.vbs"   # v2/v3 entries went through PowerShell Start-Process, which fails on some PCs
    keeper && { printf 'task:%s\n' "$TASK" > "$MARK"; echo "autostart: el vigilante ya corre"; exit 0; }
    # 1) Windows scheduled task (no admin): Task Scheduler starts it now, after every logon and every 10 min if it died; hidden via conhost --headless
    for hidden in 1 0; do
      out="$(make_task "$hidden")"
      if printf '%s' "$out" | grep -q TASK_OK; then
        if wait_keeper 45; then printf 'task:%s\n' "$TASK" > "$MARK"
          [ "$hidden" = 1 ] && echo "autostart: vigilante arrancado por una tarea programada de Windows (oculta)" \
                            || echo "autostart: vigilante arrancado por una tarea programada de Windows; verás una ventana negra 'wsl': no la cierres (si la cierras, vuelve en 10 min)"
          echo "autostart: listo; puedes cerrar la ventana de Ubuntu"; exit 0
        fi
        echo "autostart: la tarea programada se creó pero el vigilante no apareció ($([ "$hidden" = 1 ] && echo oculta || echo visible))"
      else echo "autostart: no pude crear la tarea programada: $(printf '%s' "$out" | ps_err)$(printf '%s' "$out" | grep -v '^#<\|<Objs\|TASK_OK' | head -c 200)"; fi
    done
    ps_run "Unregister-ScheduledTask -TaskName '$TASK' -Confirm:\$false -ErrorAction SilentlyContinue" >/dev/null
    # 2) last resort: start it straight from this window (proven to work here, P1 of the probe); may die when this window closes
    (setsid nohup wsl.exe -d "$DISTRO" -u "$U" -e bash -lc "cd $DIR && exec tools/keepalive.sh" </dev/null >/dev/null 2>&1 &)
    if wait_keeper 30; then printf 'direct\n' > "$MARK"; echo "autostart: vigilante arrancado desde esta ventana; puede pararse al cerrarla (pega estas líneas a Claude)"; exit 0; fi
    echo "autostart: el vigilante no arrancó. Últimas líneas de supervisor.log:"; tail -n 5 supervisor.log 2>/dev/null | sed 's/^/  /'; exit 1 ;;
  start)
    keeper && { echo "autostart: el vigilante ya corre"; exit 0; }
    E="$(head -n 1 "$MARK" 2>/dev/null)"
    case "$E" in task:*) ps_run "Start-ScheduledTask -TaskName '${E#task:}'" >/dev/null; wait_keeper 45 && { echo "autostart: vigilante arrancado"; exit 0; }; echo "autostart: no arrancó"; exit 1 ;;
                 "") echo "autostart: no instalado (tools/autostart.sh on)"; exit 1 ;;
                 *) [ -f "$E" ] && launch "$E" || { echo "autostart: no instalado (tools/autostart.sh on)"; exit 1; } ;; esac ;;
  off)
    SD="$(startup_dir 2>/dev/null)"; [ -n "$SD" ] && rm -f "$SD/TradingBot.lnk" "$SD/TradingBot.vbs"
    E="$(head -n 1 "$MARK" 2>/dev/null)"; case "$E" in task:*|direct|"") ;; *) rm -f "$E" ;; esac; rm -f "$MARK"
    ps_run "Unregister-ScheduledTask -TaskName '$TASK' -Confirm:\$false -ErrorAction SilentlyContinue" >/dev/null; pkill -f "keepaliv[e].sh" 2>/dev/null
    echo "autostart: quitado y vigilante parado (el bot sigue corriendo hasta que cierres la ventana o ejecutes ./stop.sh)" ;;
  status)
    E="$(head -n 1 "$MARK" 2>/dev/null)"
    case "$E" in task:*) echo "autostart: tarea programada de Windows '${E#task:}': $(ps_run "(Get-ScheduledTask -TaskName '${E#task:}' -ErrorAction SilentlyContinue).State" | grep -v '^#<\|<Objs' | head -n 1)" ;;
                 direct) echo "autostart: vigilante lanzado desde una ventana (sin tarea programada)" ;;
                 *) if [ -n "$E" ] && [ -f "$E" ]; then echo "autostart: instalado ($E)"; else echo "autostart: NO instalado"; fi ;; esac
    keeper && echo "vigilante: corriendo" || echo "vigilante: parado"
    running && echo "supervisor: corriendo" || echo "supervisor: parado" ;;
  probe)   # 02-nov: which piece of the Windows-side launch fails on this PC (each step writes a marker file inside this distro)
    [ -n "$DISTRO" ] || { echo "probe: no estoy dentro de WSL"; exit 2; }
    echo "probe: distro=$DISTRO usuario=$U dir=$DIR"
    echo "probe: distribuciones de WSL:"; (cd /mnt/c && wsl.exe -l -v) 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\r\000' | sed '/^\s*$/d; s/^/  /'
    chk() { for _ in $(seq 1 "${2:-15}"); do [ -f "/tmp/ka_$1" ] && return 0; sleep 1; done; return 1; }
    rm -f /tmp/ka_p1 /tmp/ka_p2 /tmp/ka_p3 /tmp/ka_p4 /tmp/ka_p5
    e="$(win wsl.exe -d "$DISTRO" -u "$U" -e bash -c 'echo ok > /tmp/ka_p1')"
    chk p1 5 && echo "P1 wsl.exe desde Ubuntu: OK" || echo "P1 wsl.exe desde Ubuntu: FALLA ${e:0:200}"
    arg() { printf -- "-d \"%s\" -u %s -e bash -c \"%s\"" "$DISTRO" "$U" "$1"; }
    e="$(ps_run "Start-Process wsl.exe -Wait -ArgumentList '$(arg 'echo ok > /tmp/ka_p2')'" | ps_err)"
    chk p2 && echo "P2 PowerShell, ventana normal: OK" || echo "P2 PowerShell, ventana normal: FALLA $e"
    e="$(ps_run "Start-Process wsl.exe -Wait -WindowStyle Hidden -ArgumentList '$(arg 'echo ok > /tmp/ka_p3')'" | ps_err)"
    chk p3 && echo "P3 PowerShell, oculto: OK" || echo "P3 PowerShell, oculto: FALLA $e"
    e="$(ps_run "Start-Process wsl.exe -WindowStyle Hidden -ArgumentList '$(arg 'sleep 3; echo ok > /tmp/ka_p4')'" | ps_err)"
    chk p4 20 && echo "P4 PowerShell, oculto y sin esperar (sobrevive a PowerShell): OK" || echo "P4 PowerShell, oculto y sin esperar: FALLA (el proceso muere al salir PowerShell) $e"
    b="$(printf '%s' "Start-Process wsl.exe -WindowStyle Hidden -ArgumentList '$(arg 'sleep 3; echo ok > /tmp/ka_p5')'" | iconv -f UTF-8 -t UTF-16LE | base64 -w0)"
    L="$(ps_run "\$l=Join-Path \$env:TEMP 'ka_probe.lnk'; \$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\$l); \$s.TargetPath=Join-Path \$env:SystemRoot 'System32\\WindowsPowerShell\\v1.0\\powershell.exe'; \$s.Arguments='-NoProfile -WindowStyle Hidden -EncodedCommand $b'; \$s.WindowStyle=7; \$s.Save(); [Console]::Out.Write(\$l)" | grep -o '[A-Za-z]:\\.*ka_probe\.lnk' | tail -n 1)"
    if [ -n "$L" ]; then win explorer.exe "$L" >/dev/null; chk p5 30 && echo "P5 acceso directo vía explorador: OK" || echo "P5 acceso directo vía explorador: FALLA"; win cmd.exe /c del "$L" >/dev/null
    else echo "P5 acceso directo vía explorador: no se pudo crear el acceso de prueba"; fi
    for hidden in 1 0; do
      e="$(ps_run "\$ErrorActionPreference='Stop'; \$a=New-ScheduledTaskAction -Execute \"\$env:SystemRoot\\System32\\$([ $hidden = 1 ] && echo conhost.exe || echo wsl.exe)\" -Argument '$([ $hidden = 1 ] && echo '--headless wsl.exe ')$(arg "echo ok > /tmp/ka_p6$hidden" | sed "s/'/''/g")'; Register-ScheduledTask -TaskName 'TradingBotProbe' -Action \$a -Force | Out-Null; Start-ScheduledTask -TaskName 'TradingBotProbe'; 'TASK_OK'")"
      chk "p6$hidden" 25 && echo "P6.$hidden tarea programada $([ $hidden = 1 ] && echo oculta || echo visible): OK" || echo "P6.$hidden tarea programada $([ $hidden = 1 ] && echo oculta || echo visible): FALLA $(printf '%s' "$e" | ps_err)"
      ps_run "Unregister-ScheduledTask -TaskName 'TradingBotProbe' -Confirm:\$false -ErrorAction SilentlyContinue" >/dev/null; rm -f "/tmp/ka_p6$hidden"
    done
    echo "probe: líneas del vigilante en supervisor.log: $(grep -c '\[keepalive\]' supervisor.log 2>/dev/null)"; grep '\[keepalive\]' supervisor.log 2>/dev/null | tail -n 3 | sed 's/^/  /'
    d="$(ps_run "Get-MpThreatDetection | Sort-Object InitialDetectionTime -Descending | Select-Object -First 3 | ForEach-Object { [string]\$_.InitialDetectionTime + ' ' + \$_.ProcessName + ' ' + (\$_.Resources -join ',') }" 2>/dev/null | grep -v '^#<\|<Objs' | head -n 3)"
    echo "probe: últimas detecciones de Windows Defender: ${d:-ninguna o sin permiso para verlas}"
    rm -f /tmp/ka_p1 /tmp/ka_p2 /tmp/ka_p3 /tmp/ka_p4 /tmp/ka_p5 ;;
  *) echo "uso: tools/autostart.sh on | off | start | status | probe"; exit 2 ;;
esac
