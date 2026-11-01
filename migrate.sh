#!/bin/bash
# Migra una instalación existente del bot (p. ej. /workspace/ai-trading-bot) a esta versión SIN perder estado, claves, wallet ni CSV.
# Un solo comando en la máquina del bot:
#   curl -fsSL https://raw.githubusercontent.com/angelmartinezcalzada/ai-trading-bot/main/migrate.sh | bash -s -- /workspace/ai-trading-bot
# Seguro por construcción: prepara la versión nueva en <dir>.new con una copia del estado, instala dependencias y pasa los tests
# MIENTRAS el bot viejo sigue corriendo; solo si todo pasa lo para, sincroniza el estado escrito entre tanto, deja el viejo en
# <dir>.bak_<fecha> y arranca el nuevo. Si algo falla antes del cambio, el viejo ni se ha tocado.
set -e
DST="${1:-/workspace/ai-trading-bot}"; REPO="${REPO:-https://github.com/angelmartinezcalzada/ai-trading-bot.git}"; BR="${BR:-main}"
NOSTART="${NOSTART:-0}"; TMP="$(mktemp -d)"; STAGE="${DST}.new"
echo "== clonando $BR"; git clone -q -b "$BR" --depth 1 "$REPO" "$TMP/repo"; SRC="$TMP/repo"; [ -d "$SRC/ai-trading-bot" ] && SRC="$SRC/ai-trading-bot"
rm -rf "$STAGE"; if [ -d "$DST" ]; then cp -a "$DST" "$STAGE"; else mkdir -p "$STAGE"; fi
cd "$STAGE"
echo "== código nuevo sobre la copia (config.json, keys.env, wallet, estado y CSV se conservan)"
for f in "$SRC"/*.py "$SRC"/*.sh "$SRC"/*.html "$SRC"/*.txt "$SRC"/*.md; do
  b="$(basename "$f")"; [ "$b" = "DECISIONS.md" ] && continue; cp "$f" "$b"; done
rm -rf hyperliquid hl_leg tests tools; cp -r "$SRC/hl_leg" "$SRC/tests" "$SRC/tools" .
mkdir -p research data state; cp -r "$SRC/research/coinversa_study.py" "$SRC/research/coinversa_study.json" research/ 2>/dev/null || true; [ -d "$SRC/research/data" ] && cp -r "$SRC/research/data" research/ || true
[ -f config.json ] || cp "$SRC/config.json" config.json
if [ -f DECISIONS.md ]; then grep -q '^## 2026-11-01 19:00' DECISIONS.md || sed -n '/^## 2026-10-31 20:05/,$p' "$SRC/DECISIONS.md" >> DECISIONS.md; else cp "$SRC/DECISIONS.md" DECISIONS.md; fi
rm -f STOP STOP_* 2>/dev/null || true
echo "== dependencias y tests en $STAGE (el bot viejo sigue corriendo)"; ./install.sh
if [ -d "$DST" ]; then
  echo "== parando la instalación actual"; (cd "$DST" && cp "$SRC/stop.sh" ./stop.sh && ./stop.sh) || true
  for i in $(seq 1 20); do pgrep -f "python3 bot.p[y] --exchange" >/dev/null || break; sleep 2; done
  echo "== sincronizando el estado escrito entre tanto"
  for f in state_*.json trades_*.csv equity_*.csv candidates_solana.jsonl ohlcv_cache.json replay_cache.json brain_state.json insider_wallets.json insider_status.json insider_promoted.json news_state.json news.jsonl levels_solana.jsonl control_*.json tunnel_url.txt DECISIONS.md keys.env solana_wallet.json dashboard_password.txt .flask_secret; do
    [ -f "$DST/$f" ] && cp -p "$DST/$f" "$STAGE/$f" || true; done
  for d in data state research; do [ -d "$DST/$d" ] && cp -rp "$DST/$d/." "$STAGE/$d/" || true; done
  grep -q '^## 2026-11-01 19:00' "$STAGE/DECISIONS.md" || sed -n '/^## 2026-10-31 20:05/,$p' "$SRC/DECISIONS.md" >> "$STAGE/DECISIONS.md"
  BK="${DST}.bak_$(date +%F_%H%M)"; mv "$DST" "$BK"; echo "== instalación anterior en $BK"
fi
mv "$STAGE" "$DST"; cd "$DST"; rm -f STOP
if [ "$NOSTART" = "1" ]; then echo "== NOSTART=1: no se arranca"; exit 0; fi
nohup setsid ./run_forever.sh >/dev/null 2>&1 &
sleep 10; ./status.sh 2>/dev/null | head -12 || true
echo "== listo. Panel: http://127.0.0.1:8787/  (contraseña en dashboard_password.txt)  Operador: python3 operador.py --once --dry-run"
