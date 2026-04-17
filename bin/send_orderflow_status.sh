#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
echo "[send_orderflow_status.sh] Deprecated: board delivery is image-only now. Delegating to run_orderflow_once.sh." >&2
exec "$ROOT/bin/run_orderflow_once.sh"
