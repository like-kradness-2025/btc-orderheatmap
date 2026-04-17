#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
echo "[send_orderflow.sh] Deprecated: orderflow generation now uploads directly from bin/start_plot.sh -> vendor/orderflow_pack/run_plot.sh. Skipping standalone send to avoid duplicate/missing-file races." >&2
exit 0
