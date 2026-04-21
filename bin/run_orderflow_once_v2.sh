#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PACK="$ROOT/vendor/orderflow_pack"
CHANNEL_ID="1480537635721314446"
ABS_CFG="${ABSORPTION_CONFIG_PATH:-$PACK/orderflow/absorption_marker_config.json}"
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
LOG="$ROOT/logs/orderflow_once_v2.log"
LOCKDIR="$ROOT/runtime/locks"
LOCKFILE="$LOCKDIR/orderflow_once_v2.lock"
mkdir -p "$ROOT/artifacts" "$ROOT/logs" "$LOCKDIR"
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "[$(date -Is)] skip: orderflow_v2 lock busy" >> "$LOG"
  exit 0
fi
{
  echo "[$(date -Is)] start: orderflow_v2 generate+upload"
  if "$PACK/run_plot_v2.sh" "$DATA_DIR" "$ROOT/artifacts/orderflow_chart_v2.png" 24 "$ABS_CFG" "$CHANNEL_ID" ""; then
    echo "[$(date -Is)] done: orderflow_v2 generate+upload"
  else
    rc=$?
    echo "[$(date -Is)] fail: orderflow_v2 generate+upload rc=$rc"
    exit "$rc"
  fi
} >> "$LOG" 2>&1
