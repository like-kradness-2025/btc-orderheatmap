#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PACK="$ROOT/vendor/orderflow_pack"
ABS_CFG="${ABSORPTION_CONFIG_PATH:-$PACK/orderflow/absorption_marker_config.json}"
DATA_DIR="${BTC_LIVE_DATA_DIR:-$ROOT/../btc-receiver/data/live}"
OUT="${ORDERHEATMAP_V322_OUT:-$ROOT/artifacts/orderflow_chart_v322.png}"
HOURS="${ORDERHEATMAP_V322_HOURS:-${ORDERHEATMAP_V321_HOURS:-${ORDERHEATMAP_V3_HOURS:-24}}}"
mkdir -p "$ROOT/artifacts" "$ROOT/logs"
"$PACK/run_plot_v322.sh" "$DATA_DIR" "$OUT" "$HOURS" "$ABS_CFG"
