#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEFAULT_CHANNEL_ID="1480537635721314446"
CHANNEL_ID="${DISCORD_CHANNEL_ID:-$DEFAULT_CHANNEL_ID}"
ABS_CFG="${ABSORPTION_CONFIG_PATH:-$ROOT/orderflow/config/absorption_marker_config.json}"
DATA_DIR="${BTC_LIVE_DATA_DIR:-$ROOT/data/live}"
FEATURE_JSONL="${ORDERFLOW_FEATURE_JSONL:-$DATA_DIR/live_features_1s.jsonl}"
SCORED_FEATURE_JSONL="${ORDERFLOW_SCORED_FEATURE_JSONL:-$DATA_DIR/live_features_with_scores.jsonl}"
OUT_PNG="$ROOT/artifacts/orderflow_chart_latest.png"
HOURS="${ORDERFLOW_HOURS:-24}"
DISCORD_MESSAGE=""
LOG="$ROOT/logs/orderflow_once.log"
LOCKDIR="$ROOT/runtime/locks"
LOCKFILE="$LOCKDIR/orderflow_once.lock"
FEATURE_JSONL=""
SCORED_FEATURE_JSONL=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --out) OUT_PNG="$2"; shift 2 ;;
    --hours) HOURS="$2"; shift 2 ;;
    --absorption-config) ABS_CFG="$2"; shift 2 ;;
    --discord-channel-id) CHANNEL_ID="${2:-}"; shift 2 ;;
    --discord-message) DISCORD_MESSAGE="${2:-}"; shift 2 ;;
    --no-discord) CHANNEL_ID=""; shift ;;
    -h|--help)
      cat <<USAGE
Usage: $0 [--data-dir DIR] [--out PNG] [--hours N] [--absorption-config JSON] [--discord-channel-id ID] [--discord-message TEXT] [--no-discord]
USAGE
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

FEATURE_JSONL="${ORDERFLOW_FEATURE_JSONL:-$DATA_DIR/live_features_1s.jsonl}"
SCORED_FEATURE_JSONL="${ORDERFLOW_SCORED_FEATURE_JSONL:-$DATA_DIR/live_features_with_scores.jsonl}"

mkdir -p "$ROOT/artifacts" "$ROOT/logs" "$LOCKDIR" "$ROOT/runtime/cache" "$DATA_DIR"

exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "[$(date -Is)] skip: orderflow lock busy" >> "$LOG"
  exit 0
fi

{
  echo "[$(date -Is)] start: orderflow score+generate+upload data_dir=$DATA_DIR features=$FEATURE_JSONL scored=$SCORED_FEATURE_JSONL out=$OUT_PNG hours=$HOURS"

  # Absorption score 計算: features が存在する場合のみ実行。欠損時はスキップして
  # renderer 側の fallback に任せる（engine は features 空でも動作可能）。
  if [ -f "$FEATURE_JSONL" ] && [ -s "$FEATURE_JSONL" ]; then
    if python3 "$ROOT/scripts/calculate_absorption_scores.py" --config "$ABS_CFG" --input "$FEATURE_JSONL" --output "$SCORED_FEATURE_JSONL"; then
      scored_rows=$(python3 - <<'PY' "$SCORED_FEATURE_JSONL"
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
count = 0
if path.exists():
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    count += 1
print(count)
PY
)
      echo "[$(date -Is)] score: orderflow scored_rows=$scored_rows output=$SCORED_FEATURE_JSONL"
      marker_count=$(python3 - <<'PY' "$ROOT" "$DATA_DIR" "$ABS_CFG" 2>/dev/null || echo "0"
import importlib.util
import sys
from pathlib import Path
import pandas as pd

root = Path(sys.argv[1])
data_dir = Path(sys.argv[2])
abs_cfg = Path(sys.argv[3])
vendor = root / 'vendor' / 'orderflow_pack' / 'orderflow'

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod

runtime = load('orderflow_runtime', vendor / 'runtime.py')
absorption = load('orderflow_absorption', vendor / 'absorption.py')
data = load('orderflow_data', vendor / 'data.py')
cfg = runtime.load_absorption_config(abs_cfg)
cfg = {**cfg, 'minimum_trade_imbalance_notional': -1.0, 'minimum_score': 1.0}
inputs = data.resolve_inputs(data_dir)
feature_df = runtime.load_feature_rows(inputs['feature_jsonl'], None)
ohlcv = data.load_ohlcv_cache(root / 'runtime' / 'cache' / 'ohlcv_cache.pkl', ttl_sec=None)
if ohlcv is None:
    ohlcv = pd.DataFrame()
if feature_df.empty or ohlcv.empty:
    print(0)
    raise SystemExit(0)
bar_df = absorption.aggregate_feature_bars(feature_df, ohlcv, cfg)
markers = absorption.compute_absorption_markers(bar_df, cfg)
print(len(markers))
PY
)
      echo "[$(date -Is)] verify: orderflow markers=$marker_count"
    else
      rc=$?
      echo "[$(date -Is)] warn: orderflow score calculation rc=$rc, continuing without pre-scored features" >&2
    fi
  else
    echo "[$(date -Is)] skip: orderflow score calculation (features file missing: $FEATURE_JSONL)" >&2
  fi
  if "$ROOT/scripts/run_plot.sh" "$DATA_DIR" "$OUT_PNG" "$HOURS" "$ABS_CFG" "$CHANNEL_ID" "$DISCORD_MESSAGE"; then
    echo "[$(date -Is)] done: orderflow score+generate+upload out=$OUT_PNG"
  else
    rc=$?
    echo "[$(date -Is)] fail: orderflow score+generate+upload rc=$rc"
    exit "$rc"
  fi
  FP_DIR="$HOME/btc-footprint"
  if python3 "$FP_DIR/scripts/run_footprint_once.py" --data-dir "$DATA_DIR"; then
    echo "[$(date -Is)] done: footprint generate+upload"
  else
    rc=$?
    echo "[$(date -Is)] warn: footprint generate+upload rc=$rc"
  fi
} >> "$LOG" 2>&1
