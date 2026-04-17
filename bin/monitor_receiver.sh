#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
LOG="$ROOT/logs/monitor_receiver.log"
PID_FILE="$ROOT/runtime/pids/receiver.pid"
HEALTH_FILE="$ROOT/runtime/health/receiver.json"
DATA_DIR="$ROOT/data/live"
STALE_HEALTH_SEC=${STALE_HEALTH_SEC:-30}
STALE_DATA_SEC=${STALE_DATA_SEC:-30}
SYMBOL_RE="orderflow_monitor\\.mjs --symbol=btcusdt"

mkdir -p "$ROOT/logs" "$ROOT/runtime/pids" "$ROOT/runtime/health"

ts() { date '+%F %T'; }
log() { printf '[%s] %s\n' "$(ts)" "$*" >> "$LOG"; }

running_pid() {
  pgrep -fo "$SYMBOL_RE" 2>/dev/null || true
}

restart_receiver() {
  local pid="$1"
  if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
    log "restarting receiver (pid=$pid)"
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
  else
    log "starting receiver (no pid)"
  fi
  "$ROOT/bin/start_receiver.sh" >/dev/null 2>&1 || log "start_receiver failed"
}

pid=$(running_pid)
if [ -n "${pid:-}" ]; then
  echo "$pid" > "$PID_FILE"
else
  restart_receiver ""
  exit 0
fi

# health file check (preferred)
if [ -f "$HEALTH_FILE" ]; then
  python3 - <<'PY' "$HEALTH_FILE" "$STALE_HEALTH_SEC" >/dev/null || {
import json, sys, time, datetime
path=sys.argv[1]
threshold=int(sys.argv[2])
now=time.time()
try:
    with open(path,'r') as f:
        data=json.load(f)
except Exception:
    sys.exit(0)

def age(iso):
    if not iso:
        return None
    try:
        dt=datetime.datetime.fromisoformat(iso.replace('Z','+00:00'))
        return now - dt.timestamp()
    except Exception:
        return None

last_depth=age(data.get('lastDepthMsgAt'))
last_trade=age(data.get('lastTradeMsgAt'))
reason=(data.get('reason') or '')
# trigger if health timestamps are too old or reason indicates stale depth
if (last_depth is not None and last_depth > threshold) or (last_trade is not None and last_trade > threshold) or ('stale' in reason):
    sys.exit(2)
PY
    status=$?
    if [ "$status" -eq 2 ]; then
      log "health stale detected (threshold=${STALE_HEALTH_SEC}s)"
      restart_receiver "$pid"
      exit 0
    fi
  }
fi

# fallback to data file mtimes
latest_mtime=0
for f in "$DATA_DIR/live_book.jsonl" "$DATA_DIR/live_trades.jsonl"; do
  if [ -f "$f" ]; then
    m=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    if [ "$m" -gt "$latest_mtime" ]; then
      latest_mtime=$m
    fi
  fi
done
now=$(date +%s)
if [ "$latest_mtime" -gt 0 ] && [ $((now - latest_mtime)) -gt "$STALE_DATA_SEC" ]; then
  log "data stale detected (age=$((now - latest_mtime))s threshold=${STALE_DATA_SEC}s)"
  restart_receiver "$pid"
fi
