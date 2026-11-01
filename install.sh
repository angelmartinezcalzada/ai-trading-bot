#!/bin/bash
# Instalación idempotente en una máquina nueva: dependencias, ficheros locales que no van en git, tests y arranque.
#   git clone -b claude/trading-bot-mvp https://github.com/angelmartinezcalzada/Angel-proyectos.git && cd Angel-proyectos/ai-trading-bot && ./install.sh
set -e; cd "$(dirname "$0")"
echo "== dependencias"; python3 -m pip install -q -r requirements.txt 2>/dev/null || python3 -m pip install -q --break-system-packages -r requirements.txt
mkdir -p data state research
if [ ! -f keys.env ]; then
  cat > keys.env <<'K'
# Claves locales (nunca en git). Solo las que uses. SOLANA_PRIVATE_KEY no hace falta: el bot lee solana_wallet.json.
BINANCE_API_KEY=
BINANCE_API_SECRET=
COINBASE_API_KEY=
COINBASE_API_SECRET=
COINVERSA_API_KEY=
# ALERT_CMD: comando que recibe el texto de cada alerta por stdin (webhook, Telegram...). Ejemplo: ALERT_CMD='curl -s -X POST -d @- https://...'
K
  chmod 600 keys.env; echo "== keys.env creado (vacío): rellena las claves que uses"
fi
if [ ! -f dashboard_password.txt ]; then python3 -c 'import secrets; print(secrets.token_urlsafe(12))' > dashboard_password.txt; chmod 600 dashboard_password.txt; echo "== contraseña del panel generada en dashboard_password.txt"; fi
if [ ! -f solana_wallet.json ]; then echo "== AVISO: sin solana_wallet.json -> Solana solo en papel hasta que copies el wallet (chmod 600)"; fi
echo "== tests"; python3 -m pytest -q tests/
echo "== modo actual por exchange:"; python3 -c "import json; c=json.load(open('config.json'))['exchanges']; print({k: v.get('mode','paper') for k, v in c.items()})"
echo
echo "Listo. Arranque 24/7:   nohup setsid ./run_forever.sh >/dev/null 2>&1 &"
echo "Estado:                 ./status.sh      Panel: http://127.0.0.1:8787/   (contraseña en dashboard_password.txt)"
echo "Parar todo:             ./stop.sh        Operador manual: python3 operador.py --once --dry-run"
echo "Modo real de Solana:    config.json exchanges.solana.mode = \"live\" + solana_wallet.json (decisión del dueño, nunca automática)"
