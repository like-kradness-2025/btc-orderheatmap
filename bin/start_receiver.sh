#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PACK="$ROOT/vendor/orderflow_pack"
mkdir -p "$ROOT/data/live" "$ROOT/logs" "$ROOT/runtime/pids" "$ROOT/runtime/health"
if pgrep -f "orderflow_monitor\\.mjs --symbol=btcusdt" >/dev/null 2>&1; then
  PID=$(pgrep -fo "orderflow_monitor\\.mjs --symbol=btcusdt" || true)
  if [ -n "${PID:-}" ]; then
    echo "$PID" > "$ROOT/runtime/pids/receiver.pid"
    echo "receiver already running pid=$PID"
    exit 0
  fi
fi
nohup bash -lc "cd '$PACK' && ./run_receiver.sh btcusdt '$ROOT/data/live' 0 '$ROOT/runtime/health/receiver.json'" >> "$ROOT/logs/receiver.log" 2>&1 < /dev/null &
sleep 1
PID=$(pgrep -fo "orderflow_monitor\\.mjs --symbol=btcusdt" || true)
if [ -z "${PID:-}" ]; then
  echo "receiver failed to start" >&2
  exit 1
fi
echo "$PID" > "$ROOT/runtime/pids/receiver.pid"
echo "receiver pid=$PID"
