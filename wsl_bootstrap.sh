#!/bin/bash
# Arranque del bot en Ubuntu dentro de WSL (Windows). Un solo comando dentro de Ubuntu:
#   curl -fsSL https://raw.githubusercontent.com/angelmartinezcalzada/ai-trading-bot/main/wsl_bootstrap.sh | bash
# Instala git/python, clona (o actualiza) el bot en ~/ai-trading-bot, instala dependencias, pasa los tests y lo arranca 24/7.
# Sin solana_wallet.json el bot de Solana corre en PAPEL (no mueve dinero); el panel queda en http://localhost:8787/ desde Windows.
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
cd "$DIR"; chmod +x *.sh tools/*.py 2>/dev/null || true
./install.sh
echo "== parando cualquier instancia anterior (bots y supervisores)"; ./stop.sh >/dev/null 2>&1 || true; sleep 3
pkill -f "run_foreve[r].sh" 2>/dev/null || true; pkill -f "python3 bot.p[y] --exchange" 2>/dev/null || true; sleep 1
rm -f STOP; nohup setsid ./run_forever.sh >/dev/null 2>&1 &
sleep 8; ./status.sh 2>/dev/null | head -8 || true
echo; echo "== listo. Panel desde Windows: http://localhost:8787/   contraseña: $(cat dashboard_password.txt)"
echo "== Solana en $(python3 -c "import json;print(json.load(open('config.json'))['exchanges']['solana'].get('mode','paper'))") (real solo cuando copies solana_wallet.json y pongas mode=live)"
echo "== para que opere 24/7 el PC no debe suspenderse (Configuración > Sistema > Energía > Suspender: nunca)"
