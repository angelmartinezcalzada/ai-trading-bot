#!/bin/bash
# Para todo de forma ordenada: STOP hace salir a los bucles de run_forever; los procesos reciben SIGTERM (guardan estado al salir).
cd "$(dirname "$0")"; touch STOP
for pat in "python3 bot.p[y] --exchange" "python3 dashboar[d].py" "python3 inside[r].py daemon" "python3 insider_w[s].py" "python3 operado[r].py" "hl_leg.hl_contex[t]" "cloudflare[d] tunnel"; do pkill -f "$pat" 2>/dev/null || true; done
sleep 2; pgrep -af "python3 bot.p[y] --exchange" >/dev/null && echo "aún vivos (esperando):" && pgrep -af "python3 bot.p[y] --exchange" || echo "todo parado"
