#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEFAULT_CHANNEL_ID="1480537635721314446"
CHANNEL_ID="${DISCORD_CHANNEL_ID:-$DEFAULT_CHANNEL_ID}"
ABS_CFG="${ABSORPTION_CONFIG_PATH:-$ROOT/orderflow/config/absorption_marker_config.json}"
DATA_DIR="${BTC_LIVE_DATA_DIR:-$ROOT/data/live}"
OUT_PNG="$ROOT/artifacts/orderflow_chart_latest.png"
HOURS="${ORDERFLOW_HOURS:-24}"
DISCORD_MESSAGE=""
LOG="$ROOT/logs/orderflow_once.log"
LOCKDIR="$ROOT/runtime/locks"
LOCKFILE="$LOCKDIR/orderflow_once.lock"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --out) OUT_PNG="$2"; shift 2 ;;
    --hours) HOURS="$2"; shift 2 ;;
    --absorption-config) ABS_CFG="$2"; shift 2 ;;
    --discord-channel-id) CHANNEL_ID="${2:-}"; shift 2 ;;
    --discord-message) DISCORD_MESSAGE="${2:-}"; shift 2 ;;
    --no-discord) CHANNEL_ID=""; shift ;;
    -h|--help)
      cat <<USAGE
Usage: $0 [--data-dir DIR] [--out PNG] [--hours N] [--absorption-config JSON] [--discord-channel-id ID] [--discord-message TEXT] [--no-discord]
USAGE
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$ROOT/artifacts" "$ROOT/logs" "$LOCKDIR" "$ROOT/runtime/cache" "$DATA_DIR"

exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "[$(date -Is)] skip: orderflow lock busy" >> "$LOG"
  exit 0
fi

{
  echo "[$(date -Is)] start: orderflow generate+upload data_dir=$DATA_DIR out=$OUT_PNG hours=$HOURS"
  if "$ROOT/scripts/run_plot.sh" "$DATA_DIR" "$OUT_PNG" "$HOURS" "$ABS_CFG" "$CHANNEL_ID" "$DISCORD_MESSAGE"; then
    echo "[$(date -Is)] done: orderflow generate+upload out=$OUT_PNG"
  else
    rc=$?
    echo "[$(date -Is)] fail: orderflow generate+upload rc=$rc"
    exit "$rc"
  fi
} >> "$LOG" 2>&1
