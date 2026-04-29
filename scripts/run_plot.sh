#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DATA_DIR=${1:-$ROOT/data/live}
OUT_PNG=${2:-$ROOT/artifacts/orderflow_chart_latest.png}
HOURS=${3:-24}
ABS_CFG=${4:-$ROOT/orderflow/config/absorption_marker_config.json}
DISCORD_CHANNEL_ID=${5:-}
DISCORD_MESSAGE=${6:-}

mkdir -p "$(dirname "$OUT_PNG")" "$ROOT/runtime/cache"
cd "$ROOT"

python3 -m orderflow.renderer \
  --hours "$HOURS" \
  --data-dir "$DATA_DIR" \
  --out "$OUT_PNG" \
  --ohlcv-cache "$ROOT/runtime/cache/ohlcv_cache.pkl" \
  --absorption-config "$ABS_CFG" \
  --discord-channel-id "$DISCORD_CHANNEL_ID" \
  --discord-message "$DISCORD_MESSAGE"
