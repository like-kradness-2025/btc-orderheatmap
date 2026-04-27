#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
LOG="$ROOT/logs/orderflow_loop_v323a.log"
mkdir -p "$ROOT/logs"
echo "[$(date -Is)] deprecated: run_orderflow_loop_v323a.sh delegates to run_orderflow_loop_v327.sh" >> "$LOG"
exec "$ROOT/bin/run_orderflow_loop_v327.sh" "$@"
