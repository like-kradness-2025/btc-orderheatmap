#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PACK="$ROOT/vendor/orderflow_pack"
CHANNEL_ID="1480537635721314446"
LOG="$ROOT/logs/orderflow_once.log"
LOCKDIR="$ROOT/runtime/locks"
LOCKFILE="$LOCKDIR/orderflow_once.lock"
mkdir -p "$ROOT/artifacts" "$ROOT/logs" "$LOCKDIR"
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "[$(date -Is)] skip: orderflow lock busy" >> "$LOG"
  exit 0
fi
{
  echo "[$(date -Is)] start: orderflow generate+upload"
  if "$PACK/run_plot.sh" "$ROOT/data/live" "$ROOT/artifacts/orderflow_chart.png" 8 "$CHANNEL_ID" ""; then
    echo "[$(date -Is)] done: orderflow generate+upload"
  else
    rc=$?
    echo "[$(date -Is)] fail: orderflow generate+upload rc=$rc"
    exit "$rc"
  fi
} >> "$LOG" 2>&1
