#!/bin/bash
cd "$(dirname "$0")"; pgrep -af "python3 bot.p[y] --exchange" || echo "NOT RUNNING"
for f in bot_*.log; do [ -f "$f" ] || continue; echo "== $f"; grep UNIVERSE "$f" | tail -1; grep "equity=" "$f" | tail -1; grep "scanned" "$f" | tail -1; echo "errors: $(grep -c ERROR "$f")"; done
for f in trades_*.csv; do [ -f "$f" ] || continue; echo "== $f (last 5)"; tail -n +2 "$f" | tail -5; done
[ -f supervisor.log ] && { echo "== supervisor.log"; tail -3 supervisor.log; }
