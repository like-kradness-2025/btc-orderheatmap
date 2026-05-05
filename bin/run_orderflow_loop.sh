#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
LOG="$ROOT/logs/orderflow_loop.log"
LOCKDIR="$ROOT/runtime/locks"
LOCKFILE="$LOCKDIR/orderflow_loop.lock"
INTERVAL_SEC="${ORDERFLOW_LOOP_INTERVAL_SEC:-900}"
mkdir -p "$ROOT/artifacts" "$ROOT/logs" "$LOCKDIR" "$ROOT/runtime/cache"

exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "[$(date -Is)] skip: orderflow loop lock busy" >> "$LOG"
  exit 1
fi

echo "[$(date -Is)] start: orderflow loop interval=${INTERVAL_SEC}s" >> "$LOG"
while true; do
  {
    echo "[$(date -Is)] tick: orderflow generate+upload"
    "$ROOT/bin/run_orderflow_once.sh" "$@"
  } >> "$LOG" 2>&1
  sleep "$INTERVAL_SEC"
done
