#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
LOG="$ROOT/logs/orderflow_loop_v327.log"
LOCKDIR="$ROOT/runtime/locks"
LOCKFILE="$LOCKDIR/orderflow_loop_v327.lock"
mkdir -p "$ROOT/artifacts" "$ROOT/logs" "$LOCKDIR"

exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "[$(date -Is)] skip: orderflow v327 loop lock busy" >> "$LOG"
  exit 1
fi

echo "[$(date -Is)] start: orderflow loop v327" >> "$LOG"
while true; do
  {
    echo "[$(date -Is)] tick: orderflow v327 generate+upload"
    "$ROOT/bin/run_orderflow_once_v327.sh"
  } >> "$LOG" 2>&1
  sleep 900
done
