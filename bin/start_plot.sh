#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BOARD_CHANNEL_ID="${DISCORD_CHANNEL_ID:-1480537635721314446}"

choose_data_dir() {
  local receiver_dir="${BTC_LIVE_DATA_DIR:-$ROOT/../btc-receiver/data/live}"
  if [ ! -d "$receiver_dir" ]; then
    echo "receiver live dir missing: $receiver_dir" >&2
    exit 1
  fi
  if ! find "$receiver_dir" -maxdepth 1 -type f -name 'live_*.jsonl' -size +0c -print -quit | grep -q .; then
    echo "receiver live dir is empty: $receiver_dir" >&2
    exit 1
  fi
  printf '%s\n' "$receiver_dir"
}

DATA_DIR=$(choose_data_dir)
mkdir -p "$ROOT/logs" "$ROOT/runtime/pids"
BTC_LIVE_DATA_DIR="$DATA_DIR" DISCORD_CHANNEL_ID="$BOARD_CHANNEL_ID" \
  nohup "$ROOT/bin/run_orderflow_loop.sh" > "$ROOT/logs/plot.log" 2>&1 &
PID=$!
echo "$PID" > "$ROOT/runtime/pids/plot.pid"
echo "plot loop pid=$PID"
