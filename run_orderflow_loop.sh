#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PACK="$ROOT/vendor/orderflow_pack"
CHANNEL_ID="1480537635721314446"
LOG="$ROOT/logs/orderflow_loop.log"
LOCKDIR="$ROOT/runtime/locks"
LOCKFILE="$LOCKDIR/orderflow_loop.lock"
mkdir -p "$ROOT/artifacts" "$ROOT/logs" "$LOCKDIR"
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "[$(date -Is)] skip: orderflow loop lock busy" >> "$LOG"
  exit 1
fi
echo "[$(date -Is)] start: orderflow loop" >> "$LOG"
while true; do
  {
    echo "[$(date -Is)] tick: orderflow generate+upload"
    "$PACK/run_plot.sh" "$ROOT/data/live" "$ROOT/artifacts/orderflow_chart.png" 8 "$CHANNEL_ID" ""
  } >> "$LOG" 2>&1
  sleep 900
done
