#!/bin/bash
cd "$(dirname "$0")"; pgrep -af "python3 bot.py --exchange" || echo "NOT RUNNING"
for f in bot_*.log; do echo "== $f"; grep UNIVERSE "$f" | tail -1; grep "equity=" "$f" | tail -1; grep "scanned" "$f" | tail -1; grep -c "ERROR" "$f" | sed 's/^/errors: /'; done
for f in trades_*.csv; do echo "== $f (last 5)"; tail -n +2 "$f" | tail -5; done
