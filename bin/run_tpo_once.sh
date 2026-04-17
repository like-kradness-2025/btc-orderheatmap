#!/usr/bin/env bash
# Legacy compatibility wrapper.
ROOT=$(cd "$(dirname "$0")/.." && pwd)
exec "$ROOT/run/run_chart_once.sh"
