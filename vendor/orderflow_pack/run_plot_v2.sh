#!/usr/bin/env bash
set -euo pipefail
DATADIR=${1:-./data/live}
OUT=${2:-./tmp/chart_v2.png}
HOURS=${3:-8}
ABS_CFG=${4:-$(cd "$(dirname "$0")" && pwd)/orderflow/absorption_marker_config.json}
DISCORD_CHANNEL_ID=${5:-}
DISCORD_MESSAGE=${6:-}
PACK=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$(dirname "$OUT")"
mkdir -p "$PACK/orderflow"
python3 "$PACK/orderflow/chartProt3_ws_compat_v2.py" \
  --hours "$HOURS" \
  --data-dir "$DATADIR" \
  --out "$OUT" \
  --ohlcv-cache "$PACK/orderflow/ohlcv_cache.pkl" \
  --absorption-config "$ABS_CFG" \
  --discord-channel-id "$DISCORD_CHANNEL_ID" \
  --discord-message "$DISCORD_MESSAGE"
