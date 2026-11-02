#!/bin/bash
# Arranque del bot en Ubuntu dentro de WSL (Windows). Un solo comando dentro de Ubuntu:
#   curl -fsSL https://raw.githubusercontent.com/angelmartinezcalzada/ai-trading-bot/main/wsl_bootstrap.sh | bash
# Instala git/python, clona (o actualiza) el bot en ~/ai-trading-bot, instala dependencias, pasa los tests y lo arranca 24/7:
# instala un arranque automático en la carpeta Inicio de Windows (tools/autostart.sh, sin administrador) para que el bot siga vivo
# aunque cierres la ventana de Ubuntu y vuelva solo al iniciar sesión. Si falta la clave de Solana Tracker, la pide (no se ve al escribir).
# Sin solana_wallet.json el bot de Solana corre en PAPEL; con él y >= 0,05 SOL pasa a REAL solo. Panel: http://localhost:8787/ desde Windows.
set -e
REPO="${REPO:-https://github.com/angelmartinezcalzada/ai-trading-bot.git}"; DIR="${DIR:-$HOME/ai-trading-bot}"
if ! command -v git >/dev/null || ! command -v python3 >/dev/null || ! python3 -m pip --version >/dev/null 2>&1; then
  echo "== instalando git y python (pide tu contraseña de Ubuntu)"; sudo apt-get update -qq; sudo apt-get install -y -qq git python3 python3-pip curl >/dev/null
fi
if [ -d "$DIR/.git" ]; then
  echo "== actualizando $DIR (tus ajustes de config.json se conservan)"
  cd "$DIR"; [ -f config.json ] && cp config.json config.local.json
  # revisiones que una versión anterior del operador escribió en DECISIONS.md -> se conservan en DIARIO.md (diario local)
  if ! git diff --quiet -- DECISIONS.md 2>/dev/null; then git diff -- DECISIONS.md | grep '^+' | grep -v '^+++' | sed 's/^+//' >> DIARIO.md; echo "== revisiones locales movidas a DIARIO.md"; fi
  git checkout -q -- . 2>/dev/null || true        # ficheros del repo vuelven a su versión (el estado, el wallet y los CSV no están en git; config.json se fusiona después)
  git pull -q
  [ -f config.local.json ] && python3 tools/config_merge.py config.local.json config.json && rm -f config.local.json
else echo "== clonando en $DIR"; git clone -q "$REPO" "$DIR"; fi
cd "$DIR"; chmod +x *.sh tools/*.py tools/*.sh 2>/dev/null || true
echo "== parando cualquier instancia anterior (bots y supervisores)"; ./stop.sh >/dev/null 2>&1 || true; sleep 3
pkill -f "run_foreve[r].sh" 2>/dev/null || true; pkill -f "python3 bot.p[y] --exchange" 2>/dev/null || true; pkill -f "python3 dashboar[d].py" 2>/dev/null || true; sleep 1
./install.sh
# clave de Solana Tracker: sin ella el bot no compra en real (la puerta ALT exige su veredicto). Se pide sin mostrarla y va a keys.env (chmod 600).
if ! grep -q '^SOLANATRACKER_API_KEY=.' keys.env 2>/dev/null && [ -r /dev/tty ]; then
  echo "== Falta la clave de Solana Tracker: sin ella el bot NO compra en real (gratis en solanatracker.io, apartado Data API)."
  printf "   Pégala y pulsa Enter (no se verá), o pulsa Enter para seguir sin ella: " > /dev/tty
  K=""; IFS= read -rs K < /dev/tty || K=""; echo > /dev/tty
  K="$(printf '%s' "$K" | tr -d '[:space:]')"
  if [ -n "$K" ]; then
    printf '%s' "$K" | python3 -c 'import os,sys; k=sys.stdin.read().strip(); p="keys.env"; L=[l for l in (open(p).read().splitlines() if os.path.exists(p) else []) if not l.startswith("SOLANATRACKER_API_KEY=")]; open(p,"w").write("\n".join(L+["SOLANATRACKER_API_KEY="+k])+"\n"); os.chmod(p,0o600)'
    echo "== clave guardada en keys.env (no se muestra)"
  else echo "== sin clave de Solana Tracker: el bot escanea y aprende, pero no compra en real"; fi
  K=""
fi
rm -f STOP
if ./tools/autostart.sh on; then echo "== el bot corre en segundo plano y arrancará solo al iniciar sesión en Windows"
else nohup setsid ./run_forever.sh >/dev/null 2>&1 & echo "== AVISO: sin arranque automático; el bot se parará si cierras esta ventana de Ubuntu"; fi
echo "== arrancado; esperando 40 s para el diagnóstico"; sleep 40
python3 tools/diagnostico.py 2>/dev/null || ./status.sh 2>/dev/null | head -8 || true
echo; echo "== listo. Panel desde Windows: http://localhost:8787/   (contraseña: cat ~/ai-trading-bot/dashboard_password.txt; no la pegues en chats)"
echo "== Solana pasa a REAL sola en cuanto solana_wallet.json tiene >= 0,05 SOL (para impedirlo: touch ~/ai-trading-bot/KILL_solana)"
echo "== diagnóstico cuando quieras: cd ~/ai-trading-bot && python3 tools/diagnostico.py"
echo "== para que opere 24/7 el PC no debe suspenderse (Configuración > Sistema > Energía > Suspender: nunca) ni apagarse"
echo "== arranque automático: tools/autostart.sh status | off (quitarlo)"
