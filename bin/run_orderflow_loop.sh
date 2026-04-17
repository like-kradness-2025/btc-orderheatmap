source /data/data/com.termux/files/home/btc-tools/PJs/btc-orderheatmap/.venv/bin/activate
#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PACK="$ROOT/vendor/orderflow_pack"
CHANNEL_ID="1480537635721314446"
choose_data_dir() {
  local receiver_dir="${BTC_LIVE_DATA_DIR:-$ROOT/../btc-receiver/data/live}"
  if [ ! -d "$receiver_dir" ]; then
    echo "receiver live dir missing: $receiver_dir" >&2
    exit 1
  fi
  if ! find "$receiver_dir" -maxdepth 1 -type f -name 'live_*.jsonl' -size +0c -print -quit | grep -q .; then
    echo "receiver live dir is empty: $receiver_dir" >&2
    exit 1
  fi
  printf '%s\n' "$receiver_dir"
}
DATA_DIR=$(choose_data_dir)
LOG="$ROOT/logs/orderflow_loop.log"
LOCKDIR="$ROOT/runtime/locks"
LOCKFILE="$LOCKDIR/orderflow_loop.lock"
mkdir -p "$ROOT/artifacts" "$ROOT/logs" "$LOCKDIR"
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "[$(date -Is)] skip: orderflow loop lock busy" >> "$LOG"
  exit 1
fi
echo "[$(date -Is)] start: orderflow loop" >> "$LOG"
while true; do
  {
    echo "[$(date -Is)] tick: orderflow generate+upload"
    "$PACK/run_plot.sh" "$DATA_DIR" "$ROOT/artifacts/orderflow_chart.png" 24 "$CHANNEL_ID" ""
  } >> "$LOG" 2>&1
  sleep 900
done
