#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEFAULT_CHANNEL_ID="1480537635721314446"
CHANNEL_ID="${DISCORD_CHANNEL_ID:-$DEFAULT_CHANNEL_ID}"
ABS_CFG="${ABSORPTION_CONFIG_PATH:-$ROOT/orderflow/config/absorption_marker_config.json}"
DATA_DIR="${BTC_LIVE_DATA_DIR:-$ROOT/data/live}"
OUT_PNG="$ROOT/artifacts/orderflow_chart_latest.png"
LOG="$ROOT/logs/orderflow_once.log"
LOCKDIR="$ROOT/runtime/locks"
LOCKFILE="$LOCKDIR/orderflow_once.lock"

choose_data_dir() {
  local receiver_dir="$DATA_DIR"
  if [ ! -d "$receiver_dir" ]; then
    echo "data dir missing: $receiver_dir" >&2
    exit 1
  fi
  if ! find "$receiver_dir" -maxdepth 1 -type f -name 'live_*.jsonl' -size +0c -print -quit | grep -q .; then
    echo "data dir is empty: $receiver_dir" >&2
    exit 1
  fi
  printf '%s\n' "$receiver_dir"
}

DATA_DIR=$(choose_data_dir)
mkdir -p "$ROOT/artifacts" "$ROOT/logs" "$LOCKDIR" "$ROOT/runtime/cache"

exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "[$(date -Is)] skip: orderflow lock busy" >> "$LOG"
  exit 0
fi

{
  echo "[$(date -Is)] start: orderflow generate+upload"
  if "$ROOT/scripts/run_plot.sh" "$DATA_DIR" "$OUT_PNG" 24 "$ABS_CFG" "$CHANNEL_ID" ""; then
    echo "[$(date -Is)] done: orderflow generate+upload out=$OUT_PNG"
  else
    rc=$?
    echo "[$(date -Is)] fail: orderflow generate+upload rc=$rc"
    exit "$rc"
  fi
} >> "$LOG" 2>&1
