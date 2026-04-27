#!/usr/bin/env bash
set -euo pipefail
PACK=$(cd "$(dirname "$0")" && pwd)
echo "deprecated: run_plot_v323a.sh delegates to run_plot_v327.sh" >&2
exec "$PACK/run_plot_v327.sh" "$@"
