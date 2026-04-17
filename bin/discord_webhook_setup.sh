#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
export BTC_WEBHOOK_DEFAULT_NAME="btc-orderheatmap"
export BTC_WEBHOOK_DEFAULT_FILE="$ROOT/../../webhook/Orderheatmap"
exec python3 "$ROOT/../shared/bin/discord_webhook_setup.py" "$@"
