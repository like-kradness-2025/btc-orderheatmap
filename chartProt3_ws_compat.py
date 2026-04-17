# -*- coding: utf-8 -*-
"""
chartProt3_orig互換ラッパー
- ローソク足ロジック: できるだけ chartProt3_orig をそのまま利用
- 板/約定データ: いま収集中の WebSocket JSONL (live_book/live_trades) を使用
"""

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytz
import aiohttp

BASE = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BASE.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.discord_uploader import upload_file, DiscordUploadError
ORDERFLOW_DIR = BASE / 'orderflow'
CP_PATH = BASE / 'chartProt3_orig.py'

DEFAULT_DATA_DIR = BASE / 'data/live'
DEFAULT_OUT_PNG = ORDERFLOW_DIR / 'chartProt3_ws_compat.png'
DEFAULT_OHLCV_CACHE_PATH = ORDERFLOW_DIR / 'ohlcv_cache.pkl'

# 板ヒートマップ閾値の自動調整（OFFでchartProt3_origの固定値を使用）
AUTO_OB_THRESHOLD = False
OB_THRESHOLD_PERCENTILE = 99.7
OB_THRESHOLD_K = 0.9
OB_THRESHOLD_MIN = 1.5
OB_THRESHOLD_MAX = 100.0

# bucket化データ（旧ロジック）利用時は分布が重くなるため別係数
# ガチャつき抑制のため、bucket側はしきい値を高めに設定
OB_THRESHOLD_PERCENTILE_BUCKETED = 92.0
OB_THRESHOLD_K_BUCKETED = 0.65
OB_THRESHOLD_MAX_BUCKETED = 160.0

# ヒートマップの見た目を落ち着かせる
HEATMAP_TONE_DOWN = False
HEATMAP_VMAX_PERCENTILE = 99
HEATMAP_POWER_GAMMA = 0.5
HEATMAP_THRESHOLD_RELAX = 1.0

# display settings for current heatmap ops
HOURS_TO_PLOT_OVERRIDE = 24
OB_TIME_RESOLUTION_OVERRIDE = '5min'
OB_Y_AXIS_RANGE_OVERRIDE = 8000
HIDE_LOWER_SUBPLOTS = True
SKIP_HIDDEN_CALCS = False
OHLCV_INTERVAL_OVERRIDE = '5m'
OHLCV_INTERVAL_MIN_OVERRIDE = 5
OHLCV_CACHE_TTL_SEC = 60
SAVEFIG_DPI_OVERRIDE = 85

TRADE_AGGREGATION_RESOLUTION = '1min'
TRADE_PRICE_BUCKET_USD = 10.0
TRADE_PLOT_MIN_QTY_THRESHOLD_OVERRIDE = {'Futures': 250.0}
TRADE_RECENT_CHUNK_BYTES = 64 * 1024 * 1024
TRADE_RECENT_MAX_BYTES = 512 * 1024 * 1024
BOOK_RECENT_CHUNK_BYTES = 32 * 1024 * 1024
BOOK_RECENT_MAX_BYTES = 512 * 1024 * 1024


def load_cp_module(path: Path):
    spec = importlib.util.spec_from_file_location('chartProt3_orig_ws_compat', str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_jsonl_sampled(path: Path, n: int = 20000, step: int = 1):
    rows = []
    if not path.exists():
        return rows
    try:
        size = path.stat().st_size
        if size == 0:
            return []

        with open(path, 'rb') as f:
            is_raw = 'raw' in path.name
            est_line_len = 2500 if is_raw else 45000
            max_read_bytes = 400 * 1024 * 1024 if is_raw else 1024 * 1024 * 1024
            offset = min(size, min(n * step * est_line_len, max_read_bytes))
            f.seek(size - offset)
            raw = f.read().decode('utf-8', errors='ignore')
            lines = raw.splitlines()
            if len(lines) > 1:
                lines = lines[1:]

            target_lines = lines[::step][-n:]
            for ln in target_lines:
                if not ln.strip():
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
    except Exception as e:
        print(f"Error reading {path}: {e}")
    return rows


def read_jsonl_recent_until(path: Path, start_ts: pd.Timestamp | None, chunk_bytes: int, max_bytes: int):
    rows = []
    if not path.exists():
        return rows

    try:
        size = path.stat().st_size
        if size == 0:
            return rows

        read_bytes = 0
        with open(path, 'rb') as f:
            pos = size
            carry = b''

            while pos > 0 and read_bytes < max_bytes:
                chunk_size = min(chunk_bytes, pos)
                pos -= chunk_size
                f.seek(pos)
                chunk = f.read(chunk_size)
                read_bytes += chunk_size

                data = chunk + carry
                lines = data.splitlines()
                if pos > 0 and lines:
                    carry = lines.pop(0)
                else:
                    carry = b''

                parsed_rows = []
                for ln in lines:
                    if not ln.strip():
                        continue
                    try:
                        parsed_rows.append(json.loads(ln.decode('utf-8', errors='ignore')))
                    except Exception:
                        pass

                if parsed_rows:
                    rows = parsed_rows + rows
                    if start_ts is not None:
                        oldest_ts = pd.to_datetime(parsed_rows[0].get('ts'), utc=True, errors='coerce')
                        if pd.notna(oldest_ts) and oldest_ts <= start_ts:
                            break

            if carry.strip():
                try:
                    rows.insert(0, json.loads(carry.decode('utf-8', errors='ignore')))
                except Exception:
                    pass
    except Exception as e:
        print(f'Error reading recent JSONL {path}: {e}')

    return rows


def load_ohlcv_cache(path: Path, ttl_sec: int):
    if not path.exists():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age > ttl_sec:
            return None
        df = pd.read_pickle(path)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df
    except Exception:
        return None
    return None


def save_ohlcv_cache(path: Path, df: pd.DataFrame):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(path)
    except Exception:
        pass


def resolve_inputs(data_dir: Path):
    return {
        'book_jsonl': data_dir / 'live_book.jsonl',
        'book_raw_jsonl': data_dir / 'live_book_raw.jsonl',
        'book_bucket_jsonl': data_dir / 'live_book_bucketed.jsonl',
        'trade_jsonl': data_dir / 'live_trades.jsonl',
        'trade_compact_jsonl': data_dir / 'live_trades_compact.jsonl',
    }


def load_book_data_with_stats_ws(market: str, hours: int, inputs: dict):
    # ??collector?Futures?????Spot??????
    if market != 'Futures':
        return pd.DataFrame()

    book_jsonl = inputs['book_jsonl']
    book_raw_jsonl = inputs['book_raw_jsonl']
    book_bucket_jsonl = inputs['book_bucket_jsonl']
    src = book_bucket_jsonl if book_bucket_jsonl.exists() else (book_jsonl if book_jsonl.exists() else book_raw_jsonl)

    start_ts = None
    if hours is not None and hours > 0:
        start_ts = pd.Timestamp.now(tz='UTC') - pd.Timedelta(hours=hours)

    # ??????????????????
    rows = read_jsonl_recent_until(src, start_ts, chunk_bytes=BOOK_RECENT_CHUNK_BYTES, max_bytes=BOOK_RECENT_MAX_BYTES)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df['timestamp'] = pd.to_datetime(df['ts'], utc=True, errors='coerce', format='mixed')
    df.dropna(subset=['timestamp'], inplace=True)

    if hours is not None and hours > 0:
        end_ts = df['timestamp'].max()
        start_ts = end_ts - pd.Timedelta(hours=hours)
        df = df[df['timestamp'] >= start_ts]

    def list_to_dict(v):
        if not isinstance(v, list):
            return {}
        out = {}
        for item in v:
            try:
                p, q = item[0], item[1]
                out[float(p)] = float(q)
            except Exception:
                pass
        return out

    def dict_to_float_dict(v):
        if not isinstance(v, dict):
            return {}
        out = {}
        for k, q in v.items():
            try:
                out[float(k)] = float(q)
            except Exception:
                pass
        return out

    out = pd.DataFrame(index=df['timestamp'])
    out['mid_price'] = pd.to_numeric(df.get('mid', np.nan), errors='coerce').to_numpy()

    if 'bids_bucketed' in df.columns and 'asks_bucketed' in df.columns:
        out['bids_json'] = df['bids_bucketed'].apply(dict_to_float_dict).to_numpy()
        out['asks_json'] = df['asks_bucketed'].apply(dict_to_float_dict).to_numpy()
    else:
        out['bids_json'] = df.get('bids', pd.Series([[]] * len(df))).apply(list_to_dict).to_numpy()
        out['asks_json'] = df.get('asks', pd.Series([[]] * len(df))).apply(list_to_dict).to_numpy()

    is_bucket_src = (src == book_bucket_jsonl)

    def sanitize_book_levels(row):
        mid = row.get('mid_price', np.nan)
        bids = row.get('bids_json', {}) if isinstance(row.get('bids_json', {}), dict) else {}
        asks = row.get('asks_json', {}) if isinstance(row.get('asks_json', {}), dict) else {}

        clean_bids = {}
        clean_asks = {}
        for p, q in bids.items():
            try:
                pf, qf = float(p), float(q)
                if np.isfinite(pf) and np.isfinite(qf) and qf > 0:
                    clean_bids[pf] = qf
            except Exception:
                pass
        for p, q in asks.items():
            try:
                pf, qf = float(p), float(q)
                if np.isfinite(pf) and np.isfinite(qf) and qf > 0:
                    clean_asks[pf] = qf
            except Exception:
                pass

        if np.isfinite(mid):
            guard = 5.0 if is_bucket_src else 0.0
            clean_bids = {p: q for p, q in clean_bids.items() if p <= (mid - guard)}
            clean_asks = {p: q for p, q in clean_asks.items() if p >= (mid + guard)}

        return pd.Series({'bids_json': clean_bids, 'asks_json': clean_asks})

    out[['bids_json', 'asks_json']] = out.apply(sanitize_book_levels, axis=1)
    out = out[~out.index.duplicated(keep='last')].sort_index()
    return out

    def dict_to_float_dict(v):
        if not isinstance(v, dict):
            return {}
        out = {}
        for k, q in v.items():
            try:
                out[float(k)] = float(q)
            except Exception:
                pass
        return out

    out = pd.DataFrame(index=df['timestamp'])
    out['mid_price'] = pd.to_numeric(df.get('mid', np.nan), errors='coerce').to_numpy()

    # 旧ロジック互換データがあれば優先利用（bids_bucketed/asks_bucketed）
    if 'bids_bucketed' in df.columns and 'asks_bucketed' in df.columns:
        out['bids_json'] = df['bids_bucketed'].apply(dict_to_float_dict).to_numpy()
        out['asks_json'] = df['asks_bucketed'].apply(dict_to_float_dict).to_numpy()
    else:
        out['bids_json'] = df.get('bids', pd.Series([[]] * len(df))).apply(list_to_dict).to_numpy()
        out['asks_json'] = df.get('asks', pd.Series([[]] * len(df))).apply(list_to_dict).to_numpy()

    # ノイズ対策: サイド逆転レベルを除去（bucket時はミッド近傍にガードバンドを設ける）
    is_bucket_src = (src == book_bucket_jsonl)

    def sanitize_book_levels(row):
        mid = row.get('mid_price', np.nan)
        bids = row.get('bids_json', {}) if isinstance(row.get('bids_json', {}), dict) else {}
        asks = row.get('asks_json', {}) if isinstance(row.get('asks_json', {}), dict) else {}

        # 数値化 + 正値のみ
        clean_bids = {}
        clean_asks = {}
        for p, q in bids.items():
            try:
                pf, qf = float(p), float(q)
                if np.isfinite(pf) and np.isfinite(qf) and qf > 0:
                    clean_bids[pf] = qf
            except Exception:
                pass
        for p, q in asks.items():
            try:
                pf, qf = float(p), float(q)
                if np.isfinite(pf) and np.isfinite(qf) and qf > 0:
                    clean_asks[pf] = qf
            except Exception:
                pass

        if np.isfinite(mid):
            guard = 5.0 if is_bucket_src else 0.0
            clean_bids = {p: q for p, q in clean_bids.items() if p <= (mid - guard)}
            clean_asks = {p: q for p, q in clean_asks.items() if p >= (mid + guard)}

        return pd.Series({'bids_json': clean_bids, 'asks_json': clean_asks})

    out[['bids_json', 'asks_json']] = out.apply(sanitize_book_levels, axis=1)

    out = out[~out.index.duplicated(keep='last')].sort_index()
    return out


def load_aggregated_trade_data_ws(market: str, hours: int, inputs: dict):
    if market != 'Futures':
        return pd.DataFrame()

    start_ts = None
    if hours is not None and hours > 0:
        start_ts = pd.Timestamp.now(tz='UTC') - pd.Timedelta(hours=hours)

    compact_path = inputs.get('trade_compact_jsonl')
    if compact_path and compact_path.exists():
        rows = read_jsonl_recent_until(
            compact_path,
            start_ts,
            chunk_bytes=TRADE_RECENT_CHUNK_BYTES,
            max_bytes=TRADE_RECENT_MAX_BYTES,
        )
        if rows:
            df = pd.DataFrame(rows)
            df['timestamp'] = pd.to_datetime(df['ts'], utc=True, errors='coerce', format='mixed')
            df.dropna(subset=['timestamp'], inplace=True)
            if hours is not None and hours > 0 and not df.empty:
                end_ts = df['timestamp'].max()
                start_ts = end_ts - pd.Timedelta(hours=hours)
                df = df[df['timestamp'] >= start_ts]

            if not df.empty:
                df['price_bucket'] = pd.to_numeric(df.get('price_bucket', np.nan), errors='coerce')
                df['qty_sum'] = pd.to_numeric(df.get('qty_sum', np.nan), errors='coerce')
                df['notional_sum'] = pd.to_numeric(df.get('notional_sum', np.nan), errors='coerce')
                df['trade_count'] = pd.to_numeric(df.get('trade_count', np.nan), errors='coerce')
                df['max_qty'] = pd.to_numeric(df.get('max_qty', np.nan), errors='coerce')
                df['vwap_price'] = pd.to_numeric(df.get('vwap_price', np.nan), errors='coerce')
                df['high_price'] = pd.to_numeric(df.get('high_price', np.nan), errors='coerce')
                df['low_price'] = pd.to_numeric(df.get('low_price', np.nan), errors='coerce')
                df['side'] = df.get('side', 'unknown').astype(str).str.lower()
                df.dropna(subset=['price_bucket', 'qty_sum', 'trade_count'], inplace=True)

                if not df.empty:
                    grp = df.groupby('timestamp', sort=True)
                    out = pd.DataFrame(index=sorted(df['timestamp'].unique()))
                    out['open_price'] = grp['vwap_price'].first()
                    out['high_price'] = grp['high_price'].max()
                    out['low_price'] = grp['low_price'].min()
                    out['close_price'] = grp['vwap_price'].last()
                    out['vwap_price'] = grp['notional_sum'].sum() / grp['qty_sum'].sum()
                    out['total_quantity'] = grp['qty_sum'].sum()
                    out['max_trade_quantity'] = grp['max_qty'].max()
                    out['number_of_trades'] = grp['trade_count'].sum().astype(float)
                    out['buy_sum_quantity'] = grp.apply(lambda g: g.loc[g['side'] == 'buy', 'qty_sum'].sum())
                    out['sell_sum_quantity'] = grp.apply(lambda g: g.loc[g['side'] == 'sell', 'qty_sum'].sum())
                    out['buy_max_quantity'] = grp.apply(lambda g: g.loc[g['side'] == 'buy', 'max_qty'].max())
                    out['sell_max_quantity'] = grp.apply(lambda g: g.loc[g['side'] == 'sell', 'max_qty'].max())
                    out['buy_trade_count'] = grp.apply(lambda g: float(g.loc[g['side'] == 'buy', 'trade_count'].sum()))
                    out['sell_trade_count'] = grp.apply(lambda g: float(g.loc[g['side'] == 'sell', 'trade_count'].sum()))
                    out = out.replace([np.inf, -np.inf], np.nan)
                    out[['buy_sum_quantity', 'sell_sum_quantity', 'buy_max_quantity', 'sell_max_quantity', 'buy_trade_count', 'sell_trade_count']] = out[[
                        'buy_sum_quantity', 'sell_sum_quantity', 'buy_max_quantity', 'sell_max_quantity', 'buy_trade_count', 'sell_trade_count'
                    ]].fillna(0.0)

                    def _plot_weight(sum_qty, max_qty, trade_count):
                        cluster_boost = 1.0 + 0.35 * np.log1p(np.clip(trade_count - 1.0, 0.0, None))
                        return np.sqrt(np.maximum(sum_qty, 0.0) * np.maximum(max_qty, 0.0)) * cluster_boost

                    out['buy_quantity'] = _plot_weight(out['buy_sum_quantity'], out['buy_max_quantity'], out['buy_trade_count'])
                    out['sell_quantity'] = _plot_weight(out['sell_sum_quantity'], out['sell_max_quantity'], out['sell_trade_count'])
                    out['close_price'] = out['vwap_price'].fillna(out['close_price'])

                    bucket_rows = []
                    for ts, g in grp:
                        bucket_rows.append((ts, g[['side', 'price_bucket', 'qty_sum', 'max_qty', 'trade_count', 'vwap_price', 'high_price', 'low_price']].rename(columns={'max_qty':'qty_max'}).to_dict('records')))
                    out['price_bucket_rows'] = pd.Series(index=out.index, dtype=object)
                    for ts, rows_at_ts in bucket_rows:
                        out.at[ts, 'price_bucket_rows'] = rows_at_ts
                    out['price_bucket_rows'] = out['price_bucket_rows'].apply(lambda v: v if isinstance(v, list) else [])
                    out.index = pd.to_datetime(out.index, utc=True)
                    return out.sort_index()

    rows = read_jsonl_recent_until(
        inputs['trade_jsonl'],
        start_ts,
        chunk_bytes=TRADE_RECENT_CHUNK_BYTES,
        max_bytes=TRADE_RECENT_MAX_BYTES,
    )
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df['timestamp'] = pd.to_datetime(df['ts'], utc=True, errors='coerce', format='mixed')
    df.dropna(subset=['timestamp'], inplace=True)

    if hours is not None and hours > 0:
        end_ts = df['timestamp'].max()
        start_ts = end_ts - pd.Timedelta(hours=hours)
        df = df[df['timestamp'] >= start_ts]

    df['price'] = pd.to_numeric(df.get('price', np.nan), errors='coerce')
    df['qty'] = pd.to_numeric(df.get('qty', np.nan), errors='coerce')
    df['notional'] = pd.to_numeric(df.get('notional', np.nan), errors='coerce')
    df['side'] = df.get('side', 'unknown').astype(str).str.lower()
    df.dropna(subset=['price', 'qty'], inplace=True)

    if df.empty:
        return pd.DataFrame()

    df['notional'] = df['notional'].where(np.isfinite(df['notional']), df['price'] * df['qty'])
    df['bucket_price'] = (np.round(df['price'] / TRADE_PRICE_BUCKET_USD) * TRADE_PRICE_BUCKET_USD).astype(float)
    df['ts_min'] = df['timestamp'].dt.floor(TRADE_AGGREGATION_RESOLUTION)

    grp = df.groupby('ts_min', sort=True)
    out = pd.DataFrame({
        'open_price': grp['price'].first(),
        'high_price': grp['price'].max(),
        'low_price': grp['price'].min(),
        'close_price': grp['price'].last(),
        'vwap_price': grp['notional'].sum() / grp['qty'].sum(),
        'total_quantity': grp['qty'].sum(),
        'max_trade_quantity': grp['qty'].max(),
        'number_of_trades': grp.size().astype(float),
        'buy_sum_quantity': grp.apply(lambda g: g.loc[g['side'] == 'buy', 'qty'].sum()),
        'sell_sum_quantity': grp.apply(lambda g: g.loc[g['side'] == 'sell', 'qty'].sum()),
        'buy_max_quantity': grp.apply(lambda g: g.loc[g['side'] == 'buy', 'qty'].max()),
        'sell_max_quantity': grp.apply(lambda g: g.loc[g['side'] == 'sell', 'qty'].max()),
        'buy_trade_count': grp.apply(lambda g: float((g['side'] == 'buy').sum())),
        'sell_trade_count': grp.apply(lambda g: float((g['side'] == 'sell').sum())),
    }).replace([np.inf, -np.inf], np.nan)

    out[['buy_sum_quantity', 'sell_sum_quantity', 'buy_max_quantity', 'sell_max_quantity', 'buy_trade_count', 'sell_trade_count']] = out[[
        'buy_sum_quantity', 'sell_sum_quantity', 'buy_max_quantity', 'sell_max_quantity', 'buy_trade_count', 'sell_trade_count'
    ]].fillna(0.0)

    def _plot_weight(sum_qty, max_qty, trade_count):
        cluster_boost = 1.0 + 0.35 * np.log1p(np.clip(trade_count - 1.0, 0.0, None))
        return np.sqrt(np.maximum(sum_qty, 0.0) * np.maximum(max_qty, 0.0)) * cluster_boost

    out['buy_quantity'] = _plot_weight(out['buy_sum_quantity'], out['buy_max_quantity'], out['buy_trade_count'])
    out['sell_quantity'] = _plot_weight(out['sell_sum_quantity'], out['sell_max_quantity'], out['sell_trade_count'])
    out['close_price'] = out['vwap_price'].fillna(out['close_price'])

    bucket_rows = []
    bucket_grp = df.groupby(['ts_min', 'side', 'bucket_price'], sort=True)
    for (ts_min, side, bucket_price), g in bucket_grp:
        qty_sum = float(g['qty'].sum())
        bucket_rows.append({
            'timestamp': ts_min,
            'side': side,
            'price_bucket': float(bucket_price),
            'qty_sum': qty_sum,
            'qty_max': float(g['qty'].max()),
            'trade_count': int(len(g)),
            'vwap_price': float(g['notional'].sum() / qty_sum) if qty_sum > 0 else np.nan,
            'high_price': float(g['price'].max()),
            'low_price': float(g['price'].min()),
        })
    out['price_bucket_rows'] = pd.Series(index=out.index, dtype=object)
    if bucket_rows:
        bucket_df = pd.DataFrame(bucket_rows)
        bucket_map = bucket_df.groupby('timestamp').apply(lambda g: g.to_dict('records'))
        out.loc[bucket_map.index, 'price_bucket_rows'] = bucket_map
    out['price_bucket_rows'] = out['price_bucket_rows'].apply(lambda v: v if isinstance(v, list) else [])

    out.index = pd.to_datetime(out.index, utc=True)
    return out.sort_index()


def upload_output_if_needed(out_png: Path, discord_channel_id: str | None, discord_message: str = ''):
    if not discord_channel_id:
        return None
    response = upload_file(discord_channel_id, out_png, discord_message)
    print(f"UPLOAD_OK channel={discord_channel_id} message_id={response.get('id')} file={out_png}")
    return response


async def run_once(hours_to_plot: int = 8, data_dir: Path | None = None, out_png: Path | None = None, ohlcv_cache_path: Path | None = None, discord_channel_id: str | None = None, discord_message: str = ''):
    cp = load_cp_module(CP_PATH)
    cp.HOURS_TO_PLOT = HOURS_TO_PLOT_OVERRIDE if HOURS_TO_PLOT_OVERRIDE else hours_to_plot
    cp.OB_TIME_RESOLUTION = OB_TIME_RESOLUTION_OVERRIDE
    cp.OB_Y_AXIS_RANGE = OB_Y_AXIS_RANGE_OVERRIDE
    cp.OHLCV_API_INTERVAL = OHLCV_INTERVAL_OVERRIDE
    cp.OHLCV_API_INTERVAL_MINUTES = OHLCV_INTERVAL_MIN_OVERRIDE
    cp.OI_FETCH_INTERVAL = OHLCV_INTERVAL_OVERRIDE
    # 1分足化に合わせてVWAP必要本数も再計算
    cp.VWAP_PERIODS = {
        "12H": (int(12 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FFFFFF'),
        "24H": (int(24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FFD700'),
        "7D":  (int(7 * 24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FFA500'),
        "14D": (int(14 * 24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#87CEEB'),
        "30D": (int(30 * 24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FF00FF'),
    }
    try:
        cp.plt.rcParams['savefig.dpi'] = SAVEFIG_DPI_OVERRIDE
    except Exception:
        pass
    if HIDE_LOWER_SUBPLOTS:
        cp.GRIDSPEC_HEIGHT_RATIOS_MAIN = [8.5, 0.001, 0.001]
        cp.MAIN_SUBPLOT_HSPACE = 0.0

    if HEATMAP_TONE_DOWN:
        cp.OB_VMAX_PERCENTILE = HEATMAP_VMAX_PERCENTILE
        cp.OB_POWER_GAMMA = HEATMAP_POWER_GAMMA

    # 自動調整OFF時は固定しきい値を少しだけ緩める
    if not AUTO_OB_THRESHOLD:
        try:
            base_th = float(cp.OB_MIN_QTY_THRESHOLD_HEATMAP.get('Futures', 100.0))
            cp.OB_MIN_QTY_THRESHOLD_HEATMAP['Futures'] = max(1.0, base_th * HEATMAP_THRESHOLD_RELAX)
        except Exception:
            pass

    try:
        cp.TRADE_PLOT_MIN_QTY_THRESHOLD.update(TRADE_PLOT_MIN_QTY_THRESHOLD_OVERRIDE)
    except Exception:
        pass

    market = 'Futures'
    symbol = cp.SYMBOL
    now_utc = pd.Timestamp.now(tz=pytz.utc)
    data_dir = (data_dir or DEFAULT_DATA_DIR)
    out_png = (out_png or DEFAULT_OUT_PNG)
    ohlcv_cache_path = (ohlcv_cache_path or DEFAULT_OHLCV_CACHE_PATH)
    inputs = resolve_inputs(data_dir)

    # 板・約定はWS JSONL（互換形式へ変換）
    book_df = load_book_data_with_stats_ws(market, cp.HOURS_TO_PLOT, inputs)
    agg_df = pd.DataFrame() if SKIP_HIDDEN_CALCS else load_aggregated_trade_data_ws(market, cp.HOURS_TO_PLOT, inputs)

    # 元描画ロジックはそのままに、閾値だけWS分布へ合わせる
    if AUTO_OB_THRESHOLD and not book_df.empty:
        qty_vals = []
        if 'bids_json' in book_df.columns:
            for d in book_df['bids_json']:
                if isinstance(d, dict):
                    qty_vals.extend([float(v) for v in d.values()])
        if 'asks_json' in book_df.columns:
            for d in book_df['asks_json']:
                if isinstance(d, dict):
                    qty_vals.extend([float(v) for v in d.values()])

        q = np.array(qty_vals, dtype=float)
        q = q[np.isfinite(q) & (q > 0)]
        if q.size > 0:
            # bucket化データは数量分布が大きくなるため係数を切替
            uses_bucketed_like = np.percentile(q, 95) > 20
            pct = OB_THRESHOLD_PERCENTILE_BUCKETED if uses_bucketed_like else OB_THRESHOLD_PERCENTILE
            k = OB_THRESHOLD_K_BUCKETED if uses_bucketed_like else OB_THRESHOLD_K
            max_th = OB_THRESHOLD_MAX_BUCKETED if uses_bucketed_like else OB_THRESHOLD_MAX
            dyn_ob_th = float(np.clip(np.percentile(q, pct) * k, OB_THRESHOLD_MIN, max_th))
            cp.OB_MIN_QTY_THRESHOLD_HEATMAP[market] = dyn_ob_th

    # ローソク足はキャッシュ優先（TTL内はAPI再取得しない）
    ohlcv_start = now_utc - pd.Timedelta(hours=cp.HOURS_TO_PLOT + 1)
    ohlcv_df = load_ohlcv_cache(ohlcv_cache_path, OHLCV_CACHE_TTL_SEC)
    ohlcv_cache_hit = ohlcv_df is not None
    if ohlcv_df is None:
        async with aiohttp.ClientSession() as session:
            ohlcv_df = await cp.fetch_binance_ohlcv_from_api(
                session,
                market,
                cp.FUTURES_SYMBOL_API,
                cp.OHLCV_API_INTERVAL,
                ohlcv_start,
                now_utc,
            )
        if isinstance(ohlcv_df, pd.DataFrame) and not ohlcv_df.empty:
            save_ohlcv_cache(ohlcv_cache_path, ohlcv_df)

    if not ohlcv_df.empty and 'volume' in ohlcv_df.columns and cp.VOLUME_EMA_HOURS > 0:
        interval_seconds = cp.OHLCV_API_INTERVAL_MINUTES * 60
        ema_span = max(1, int(cp.VOLUME_EMA_HOURS * 3600 / interval_seconds))
        if len(ohlcv_df) > ema_span:
            ohlcv_df['volume_ema'] = ohlcv_df['volume'].ewm(span=ema_span, adjust=False).mean()
        else:
            ohlcv_df['volume_ema'] = np.nan

    # OIは今回は未使用（ローソク足最優先）
    oi_df = pd.DataFrame()

    img = cp.plot_depth_chart_with_indicators(
        cp.EXCHANGE_NAME,
        market,
        symbol,
        book_df,
        agg_df,
        ohlcv_df,
        oi_df,
    )

    if img is None:
        raise RuntimeError('chart generation failed (img is None)')

    out_png.parent.mkdir(parents=True, exist_ok=True)
    with open(out_png, 'wb') as f:
        f.write(img.getvalue())

    q95_for_mode = None
    try:
        qv = []
        for d in book_df.get('bids_json', pd.Series(dtype=object)):
            if isinstance(d, dict):
                qv.extend(list(d.values()))
        for d in book_df.get('asks_json', pd.Series(dtype=object)):
            if isinstance(d, dict):
                qv.extend(list(d.values()))
        if qv:
            q95_for_mode = float(np.percentile(np.array(qv, dtype=float), 95))
    except Exception:
        pass

    mode_label = 'bucketed' if (q95_for_mode is not None and q95_for_mode > 20) else 'raw'

    print(
        f"OK out={out_png} rows(book={len(book_df)}, agg={len(agg_df)}, ohlcv={len(ohlcv_df)}) "
        f"ob_heatmap_th={cp.OB_MIN_QTY_THRESHOLD_HEATMAP.get(market)} mode={mode_label} "
        f"hours={cp.HOURS_TO_PLOT} ob_res={cp.OB_TIME_RESOLUTION} dpi={SAVEFIG_DPI_OVERRIDE} ohlcv_cache_hit={ohlcv_cache_hit}"
    )

    if discord_channel_id:
        upload_output_if_needed(out_png, discord_channel_id, discord_message)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='WS chart renderer (legacy/candidate selectable)')
    ap.add_argument('--data-dir', default=str(DEFAULT_DATA_DIR), help='directory containing live_book/live_trades jsonl set')
    ap.add_argument('--out', default=str(DEFAULT_OUT_PNG), help='output png path')
    ap.add_argument('--ohlcv-cache', default=str(DEFAULT_OHLCV_CACHE_PATH), help='ohlcv cache pickle path')
    ap.add_argument('--hours', type=int, default=8, help='hours to plot')
    ap.add_argument('--discord-channel-id', default='', help='Discord channel id for direct upload after rendering')
    ap.add_argument('--discord-message', default='', help='Optional Discord message content for upload')
    args = ap.parse_args()
    try:
        asyncio.run(run_once(
            args.hours,
            Path(args.data_dir),
            Path(args.out),
            Path(args.ohlcv_cache),
            args.discord_channel_id or None,
            args.discord_message,
        ))
    except DiscordUploadError as exc:
        raise SystemExit(f'Discord upload failed: {exc}')
