#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PACK="$ROOT/vendor/orderflow_pack"
ABS_CFG="${ABSORPTION_CONFIG_PATH:-$PACK/orderflow/absorption_marker_config.json}"
DATA_DIR="${BTC_LIVE_DATA_DIR:-$ROOT/../btc-receiver/data/live}"
OUT="${ORDERHEATMAP_V323A_OUT:-$ROOT/artifacts/orderflow_chart_v323a.png}"
HOURS="${ORDERHEATMAP_V323A_HOURS:-${ORDERHEATMAP_V323_HOURS:-${ORDERHEATMAP_V322_HOURS:-${ORDERHEATMAP_V321_HOURS:-${ORDERHEATMAP_V3_HOURS:-12}}}}}"
mkdir -p "$ROOT/artifacts" "$ROOT/logs"
"$PACK/run_plot_v323a.sh" "$DATA_DIR" "$OUT" "$HOURS" "$ABS_CFG"
