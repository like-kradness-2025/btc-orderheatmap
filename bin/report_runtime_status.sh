#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export PATH="/home/weed420/.nvm/versions/node/v24.14.0/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
ROOM="channel:1484831567569227797"
TS=$(date '+%Y-%m-%d %H:%M:%S')
RECEIVER_PID="-"
TPO_PID="-"
if [ -f "$ROOT/runtime/pids/receiver.pid" ]; then RECEIVER_PID=$(cat "$ROOT/runtime/pids/receiver.pid" 2>/dev/null || echo '-'); fi
if [ -f "$ROOT/runtime/pids/tpo.pid" ]; then TPO_PID=$(cat "$ROOT/runtime/pids/tpo.pid" 2>/dev/null || echo '-'); fi
BOOK_SIZE=$(stat -c %s "$ROOT/data/live/live_book.jsonl" 2>/dev/null || echo 0)
TRADES_SIZE=$(stat -c %s "$ROOT/data/live/live_trades.jsonl" 2>/dev/null || echo 0)
CHART_MTIME=$(date -r "$ROOT/artifacts/orderflow_chart.png" '+%H:%M:%S' 2>/dev/null || echo '-')
TPO_MTIME=$(date -r "$ROOT/artifacts/tpo.png" '+%H:%M:%S' 2>/dev/null || echo '-')
MSG="[$TS] receiver_pid=$RECEIVER_PID | tpo_pid=$TPO_PID | live_book=${BOOK_SIZE}B | live_trades=${TRADES_SIZE}B | chart=${CHART_MTIME} | tpo=${TPO_MTIME}"
/home/weed420/.nvm/versions/node/v24.14.0/bin/openclaw message send --channel discord --target "$ROOM" --message "$MSG" >/dev/null 2>&1 || true
printf '%s\n' "$MSG"
