# Mantiene el bot corriendo dentro de WSL (Ubuntu) aunque cierres la ventana, y lo arranca solo al iniciar sesión en Windows.
# PowerShell como administrador:
#   irm https://raw.githubusercontent.com/angelmartinezcalzada/ai-trading-bot/main/windows/tarea.ps1 | iex
$ErrorActionPreference = "Stop"
$user = (wsl.exe -d Ubuntu -e whoami).Trim()
if (-not $user) { throw "No encuentro la distribucion Ubuntu en WSL (wsl --install -d Ubuntu)" }
$cmd = "cd ~/ai-trading-bot && rm -f STOP && exec tools/keepalive.sh"   # vigilante: mantiene viva la distro y relanza el supervisor
$action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d Ubuntu -u $user -e bash -lc `"$cmd`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Unregister-ScheduledTask -TaskName "TradingBot" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "TradingBot" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest | Out-Null
Start-ScheduledTask -TaskName "TradingBot"
Start-Sleep -Seconds 15
wsl.exe -d Ubuntu -u $user -e bash -lc "cd ~/ai-trading-bot && ./status.sh | head -6"
Write-Host ""
Write-Host "Tarea 'TradingBot' registrada: el bot arranca al iniciar sesion y sigue corriendo con la ventana cerrada."
Write-Host "Panel: http://localhost:8787/   Parar: Stop-ScheduledTask -TaskName TradingBot   Arrancar: Start-ScheduledTask -TaskName TradingBot"
