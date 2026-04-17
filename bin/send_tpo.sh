#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
echo "[send_tpo.sh] Deprecated: tpo/tpo_sender_wsl.py now generates and uploads in one step. Skipping standalone send to avoid duplicate posts." >&2
exit 0
