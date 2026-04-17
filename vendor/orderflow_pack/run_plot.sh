#!/usr/bin/env bash
set -euo pipefail
DATADIR=${1:-./data/live}
OUT=${2:-./tmp/chart.png}
HOURS=${3:-8}
DISCORD_CHANNEL_ID=${4:-}
DISCORD_MESSAGE=${5:-}
PACK=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$(dirname "$OUT")"
mkdir -p "$PACK/orderflow"
python3 "$PACK/orderflow/chartProt3_ws_compat.py" \
  --hours "$HOURS" \
  --data-dir "$DATADIR" \
  --out "$OUT" \
  --ohlcv-cache "$PACK/orderflow/ohlcv_cache.pkl" \
  --discord-channel-id "$DISCORD_CHANNEL_ID" \
  --discord-message "$DISCORD_MESSAGE"
