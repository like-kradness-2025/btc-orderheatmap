import argparse
import asyncio
import importlib.util
import io
import json
import sys
from pathlib import Path

import aiohttp
import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import pytz
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

BASE = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BASE.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.discord_uploader import DiscordUploadError, upload_file

CP_PATH = BASE / 'chartProt3_orig.py'
WS_COMPAT_PATH = BASE / 'orderflow' / 'chartProt3_ws_compat.py'
DEFAULT_DATA_DIR = BASE / 'data/live'
DEFAULT_OUT_PNG = BASE / 'orderflow' / 'chartProt3_ws_layered_v3.png'
DEFAULT_OHLCV_CACHE_PATH = BASE / 'orderflow' / 'ohlcv_cache.pkl'
DEFAULT_ABSORPTION_CFG_PATH = BASE / 'orderflow' / 'absorption_marker_config.json'

VERSION_LABEL = 'v3.21'
SAVEFIG_DPI_OVERRIDE = 85
OHLCV_CACHE_TTL_SEC = 60
HOURS_TO_PLOT_OVERRIDE = 8
OB_TIME_RESOLUTION_OVERRIDE = '5min'
OB_Y_AXIS_RANGE_OVERRIDE = 8000
OHLCV_INTERVAL_OVERRIDE = '5m'
OHLCV_INTERVAL_MIN_OVERRIDE = 5
TRADE_MARKER_SIZE_MIN = 20
TRADE_MARKER_SIZE_MAX = 2000
TRADE_MARKER_SIZE_POWER = 0.6
TRADE_LIMIT_PER_SIDE = 20
JST = pytz.timezone('Asia/Tokyo')


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cp = load_module('chartProt3_orig_layered_v321', CP_PATH)
ws = load_module('chartProt3_ws_compat_layered_v321', WS_COMPAT_PATH)


def y_fmt(y, pos):
    if abs(y) >= 1e9:
        return f'{y/1e9:.1f}G'
    if abs(y) >= 1e6:
        return f'{y/1e6:.1f}M'
    if abs(y) >= 1e3:
        return f'{y/1e3:.1f}k'
    if abs(y) >= 1:
        return f'{y:.0f}'
    if abs(y) > 1e-9:
        return f'{y:.2f}'
    return '0'


def price_fmt(y, pos):
    return f'{y:.0f}'


y_formatter = FuncFormatter(y_fmt)
price_formatter = FuncFormatter(price_fmt)


def resolve_inputs_v3(data_dir: Path):
    inputs = ws.resolve_inputs(data_dir)
    inputs['feature_jsonl'] = data_dir / 'live_features_1s.jsonl'
    inputs['oi_jsonl'] = data_dir / 'live_oi.jsonl'
    return inputs


def load_absorption_config(path: Path) -> dict:
    default_cfg = {
        'enabled': True,
        'feature_file_name': 'live_features_1s.jsonl',
        'minimum_score': 1.75,
        'medium_score': 2.5,
        'large_score': 3.6,
        'minimum_trade_imbalance_notional': 0.0,
        'buy_trade_weight': 1.0,
        'sell_trade_weight': 1.0,
        'ask_replenish_weight': 1.0,
        'bid_replenish_weight': 1.0,
        'best_ask_delta_weight': 0.6,
        'best_bid_delta_weight': 0.6,
        'depth_ask_delta_weight': 0.6,
        'depth_bid_delta_weight': 0.6,
        'buy_stall_weight': 0.8,
        'sell_stall_weight': 0.8,
        'normalize_quantile': 0.95,
        'normalize_floor': 1.0,
        'mid_move_quantile': 0.9,
        'mid_move_floor': 0.25,
        'bar_interval': '5min',
        'plot': {
            'buy_color': '#3b82f6',
            'sell_color': '#ef4444',
            'edge_color': '#ffffff',
            'alpha': 0.95,
            'marker_linewidth': 0.7,
            'small_size': 80.0,
            'medium_size': 120.0,
            'large_size': 340.0,
            'buy_marker': 'o',
            'sell_marker': 'o',
            'y_offset_ratio': 0.12,
            'keep_strongest_per_bar': True,
            'min_bars_between_same_side': 0,
        },
    }
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                custom = json.load(f)
            for k, v in custom.items():
                if isinstance(v, dict) and isinstance(default_cfg.get(k), dict):
                    default_cfg[k].update(v)
                else:
                    default_cfg[k] = v
        except Exception:
            pass
    return default_cfg


def normalize_series(s: pd.Series, q: float = 0.95, floor: float = 1.0) -> pd.Series:
    s = pd.to_numeric(s, errors='coerce').fillna(0.0)
    scale = float(max(s.abs().quantile(q), floor))
    return (s / scale).clip(-2.5, 2.5)


def _positive(x):
    try:
        return max(float(x), 0.0)
    except Exception:
        return 0.0


def _negative_abs(x):
    try:
        return max(-float(x), 0.0)
    except Exception:
        return 0.0


def load_feature_rows(feature_path: Path, start_ts: pd.Timestamp | None) -> pd.DataFrame:
    rows = ws.read_jsonl_recent_until(feature_path, start_ts, chunk_bytes=16 * 1024 * 1024, max_bytes=256 * 1024 * 1024)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df['ts'] = pd.to_datetime(df['ts'], utc=True, errors='coerce')
    df = df.dropna(subset=['ts']).sort_values('ts').reset_index(drop=True)
    if start_ts is not None:
        df = df[df['ts'] >= start_ts]
    return df


def aggregate_feature_bars(feature_df: pd.DataFrame, ohlc_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    if feature_df.empty or ohlc_df.empty:
        return pd.DataFrame()
    feature_df = feature_df.copy()
    interval = cfg.get('bar_interval', '5min')
    feature_df['bar_ts'] = feature_df['ts'].dt.floor(interval)
    cols = [
        'trade_imbalance_notional_window',
        'mid_move_window_bps',
        'net_ask_add_cancel_notional_window',
        'net_bid_add_cancel_notional_window',
        'best_ask_qty_delta_window',
        'best_bid_qty_delta_window',
        'depth_ask_notional_5bps_delta_window',
        'depth_bid_notional_5bps_delta_window',
    ]
    for col in cols:
        feature_df[col] = pd.to_numeric(feature_df.get(col), errors='coerce').fillna(0.0)
    grouped = feature_df.groupby('bar_ts')[cols].sum()
    out = ohlc_df[['open', 'high', 'low', 'close']].copy()
    out.index = pd.to_datetime(out.index, utc=True)
    out = out.join(grouped, how='left')
    return out.fillna(0.0)


def compute_absorption_markers(bar_df: pd.DataFrame, cfg: dict):
    if bar_df.empty or not cfg.get('enabled', True):
        return []
    plot_cfg = cfg.get('plot', {})
    work = bar_df.copy().reset_index()
    if 'ts' not in work.columns:
        work = work.rename(columns={work.columns[0]: 'ts'})
    work['ts'] = pd.to_datetime(work['ts'], utc=True, errors='coerce')
    work = work.dropna(subset=['ts'])

    norm_q = float(cfg.get('normalize_quantile', 0.95))
    norm_floor = float(cfg.get('normalize_floor', 1.0))
    move_q = float(cfg.get('mid_move_quantile', 0.90))
    move_floor = float(cfg.get('mid_move_floor', 0.25))

    work['ti_norm'] = normalize_series(work['trade_imbalance_notional_window'], q=norm_q, floor=norm_floor)
    work['mid_move_norm'] = normalize_series(work['mid_move_window_bps'], q=move_q, floor=move_floor)
    work['ask_replenish_norm'] = normalize_series(work['net_ask_add_cancel_notional_window'], q=norm_q, floor=norm_floor)
    work['bid_replenish_norm'] = normalize_series(work['net_bid_add_cancel_notional_window'], q=norm_q, floor=norm_floor)
    work['best_ask_delta_norm'] = normalize_series(work['best_ask_qty_delta_window'], q=norm_q, floor=norm_floor)
    work['best_bid_delta_norm'] = normalize_series(work['best_bid_qty_delta_window'], q=norm_q, floor=norm_floor)
    work['depth_ask_delta_norm'] = normalize_series(work['depth_ask_notional_5bps_delta_window'], q=norm_q, floor=norm_floor)
    work['depth_bid_delta_norm'] = normalize_series(work['depth_bid_notional_5bps_delta_window'], q=norm_q, floor=norm_floor)

    price_range = max(float(work['high'].max() - work['low'].min()), 1.0)
    y_offset = price_range * float(plot_cfg.get('y_offset_ratio', 0.06))
    min_score = float(cfg.get('minimum_score', 1.75))
    medium_score = float(cfg.get('medium_score', 2.5))
    large_score = float(cfg.get('large_score', 3.6))
    min_ti_abs = float(cfg.get('minimum_trade_imbalance_notional', 0.0))

    def score_to_size(score: float) -> float:
        if score >= large_score:
            return float(plot_cfg.get('large_size', 340.0))
        if score >= medium_score:
            return float(plot_cfg.get('medium_size', 120.0))
        return float(plot_cfg.get('small_size', 80.0))

    markers = []
    for _, row in work.iterrows():
        ti = float(row['ti_norm'])
        move = float(row['mid_move_norm'])
        raw_ti = float(row['trade_imbalance_notional_window'])
        buy_score = (
            float(cfg.get('buy_trade_weight', 1.0)) * _positive(ti)
            + float(cfg.get('ask_replenish_weight', 1.0)) * _positive(row['ask_replenish_norm'])
            + float(cfg.get('best_ask_delta_weight', 0.6)) * _positive(row['best_ask_delta_norm'])
            + float(cfg.get('depth_ask_delta_weight', 0.6)) * _positive(row['depth_ask_delta_norm'])
            + float(cfg.get('buy_stall_weight', 0.8)) * _negative_abs(move)
        )
        sell_score = (
            float(cfg.get('sell_trade_weight', 1.0)) * _negative_abs(ti)
            + float(cfg.get('bid_replenish_weight', 1.0)) * _positive(row['bid_replenish_norm'])
            + float(cfg.get('best_bid_delta_weight', 0.6)) * _positive(row['best_bid_delta_norm'])
            + float(cfg.get('depth_bid_delta_weight', 0.6)) * _positive(row['depth_bid_delta_norm'])
            + float(cfg.get('sell_stall_weight', 0.8)) * _positive(move)
        )
        buy_trigger = raw_ti > min_ti_abs and buy_score >= min_score
        sell_trigger = raw_ti < -min_ti_abs and sell_score >= min_score
        if buy_trigger and (not sell_trigger or buy_score >= sell_score):
            markers.append({
                'ts': row['ts'],
                'side': 'buy_absorption',
                'score': buy_score,
                'price': float(row['high']) + y_offset,
                'size': score_to_size(buy_score),
                'color': plot_cfg.get('buy_color', '#3b82f6'),
                'symbol': plot_cfg.get('buy_marker', 'o'),
            })
        elif sell_trigger:
            markers.append({
                'ts': row['ts'],
                'side': 'sell_absorption',
                'score': sell_score,
                'price': float(row['low']) - y_offset,
                'size': score_to_size(sell_score),
                'color': plot_cfg.get('sell_color', '#ef4444'),
                'symbol': plot_cfg.get('sell_marker', 'o'),
            })
    if plot_cfg.get('keep_strongest_per_bar', True):
        strongest = {}
        for ev in markers:
            key = (ev['ts'], ev['side'])
            if key not in strongest or ev['score'] > strongest[key]['score']:
                strongest[key] = ev
        markers = sorted(strongest.values(), key=lambda x: x['ts'])
    return markers


def compute_plot_window(book_df: pd.DataFrame, aggregated_trade_df: pd.DataFrame, ohlc_data: pd.DataFrame, hours: int):
    all_times = []
    if not book_df.empty:
        all_times.extend(book_df.index.tolist())
    if not aggregated_trade_df.empty:
        all_times.extend(aggregated_trade_df.index.tolist())
    if not ohlc_data.empty:
        latest_data_time = ohlc_data.index.max()
        if not book_df.empty and book_df.index.max() > latest_data_time:
            latest_data_time = book_df.index.max()
        if not aggregated_trade_df.empty and aggregated_trade_df.index.max() > latest_data_time:
            latest_data_time = aggregated_trade_df.index.max()
        effective_plot_end_time = latest_data_time
        effective_plot_start_time = effective_plot_end_time - pd.Timedelta(hours=hours)
        ohlc_for_plot_window = ohlc_data[(ohlc_data.index >= effective_plot_start_time) & (ohlc_data.index <= effective_plot_end_time)]
        all_times.extend(ohlc_for_plot_window.index.tolist())
    if all_times:
        valid_times = [t for t in all_times if pd.notna(t)]
        if valid_times:
            return min(valid_times), max(valid_times)
    time_max = pd.Timestamp.now(tz=pytz.utc)
    time_min = time_max - pd.Timedelta(hours=hours)
    return time_min, time_max


def compute_center_price(book_df: pd.DataFrame, aggregated_trade_df: pd.DataFrame, ohlc_data: pd.DataFrame) -> float:
    if not ohlc_data.empty and 'close' in ohlc_data.columns:
        vals = ohlc_data['close'].dropna().tolist()
        if vals:
            return float(vals[-1])
    if not book_df.empty and 'mid_price' in book_df.columns:
        vals = book_df['mid_price'].dropna()
        if not vals.empty:
            return float(vals.iloc[-1])
    if not aggregated_trade_df.empty and 'close_price' in aggregated_trade_df.columns:
        vals = aggregated_trade_df['close_price'].dropna()
        if not vals.empty:
            return float(vals.iloc[-1])
    return 65000.0


def build_regular_time_index(start_ts: pd.Timestamp, end_ts: pd.Timestamp, freq: str) -> pd.DatetimeIndex:
    start_ts = pd.Timestamp(start_ts).tz_convert('UTC') if pd.Timestamp(start_ts).tzinfo else pd.Timestamp(start_ts).tz_localize('UTC')
    end_ts = pd.Timestamp(end_ts).tz_convert('UTC') if pd.Timestamp(end_ts).tzinfo else pd.Timestamp(end_ts).tz_localize('UTC')
    start_floor = start_ts.floor(freq)
    end_floor = end_ts.floor(freq)
    if end_floor < start_floor:
        end_floor = start_floor
    return pd.date_range(start=start_floor, end=end_floor, freq=freq, tz='UTC')


def draw_heatmap_layer(ax_main_price, ax_cbar_left, book_df: pd.DataFrame, price_min: float, price_max: float, cp_mod, time_min_dt_plot: pd.Timestamp, time_max_dt_plot: pd.Timestamp):
    num_price_bins_hm = int(np.ceil((price_max - price_min) / cp_mod.OB_PRICE_RESOLUTION))
    price_bins_hm = np.linspace(price_min, price_max, num_price_bins_hm + 1)
    if book_df.empty:
        return None, None

    book_df_unique = book_df[~book_df.index.duplicated(keep='last')] if not book_df.index.is_unique else book_df
    cols = [c for c in ['bids_json', 'asks_json'] if c in book_df_unique.columns]
    if not cols:
        return None, None

    book_resampled = book_df_unique[cols].resample(cp_mod.OB_TIME_RESOLUTION).last()
    regular_index = build_regular_time_index(time_min_dt_plot, time_max_dt_plot, cp_mod.OB_TIME_RESOLUTION)
    if len(regular_index) == 0:
        return None, None
    book_resampled = book_resampled.reindex(regular_index)

    freq_delta = pd.Timedelta(cp_mod.OB_TIME_RESOLUTION)
    time_coords_dt_hm = book_resampled.index
    time_edges_dt_hm_list = list(time_coords_dt_hm) + [time_coords_dt_hm[-1] + freq_delta]
    time_edges_num_hm = mdates.date2num(time_edges_dt_hm_list)
    num_time_bins_hm = len(time_coords_dt_hm)
    bid_grid_hm = np.zeros((num_price_bins_hm, num_time_bins_hm))
    ask_grid_hm = np.zeros((num_price_bins_hm, num_time_bins_hm))
    populated_cols = np.zeros(num_time_bins_hm, dtype=bool)

    for t_idx, timestamp in enumerate(time_coords_dt_hm):
        row = book_resampled.loc[timestamp]
        bids = row.get('bids_json', {})
        asks = row.get('asks_json', {})
        if isinstance(bids, dict) and bids:
            populated_cols[t_idx] = True
            for p, q in bids.items():
                i = np.searchsorted(price_bins_hm, p, side='right') - 1
                if 0 <= i < num_price_bins_hm:
                    bid_grid_hm[i, t_idx] += q
        if isinstance(asks, dict) and asks:
            populated_cols[t_idx] = True
            for p, q in asks.items():
                i = np.searchsorted(price_bins_hm, p, side='right') - 1
                if 0 <= i < num_price_bins_hm:
                    ask_grid_hm[i, t_idx] += q

    qty_thresh = cp_mod.OB_MIN_QTY_THRESHOLD_HEATMAP.get('Futures', 0.0)
    missing_mask = np.broadcast_to(~populated_cols, bid_grid_hm.shape)
    bid_mask = np.ma.masked_where((bid_grid_hm < qty_thresh) | missing_mask, bid_grid_hm)
    ask_mask = np.ma.masked_where((ask_grid_hm < qty_thresh) | missing_mask, ask_grid_hm)
    all_valid = []
    for grid in [bid_mask, ask_mask]:
        if np.ma.count(grid) > 0:
            all_valid.extend(grid[~grid.mask].flatten())
    common_vmax = max(np.percentile(all_valid, cp_mod.OB_VMAX_PERCENTILE), qty_thresh * 1.01) if all_valid else qty_thresh * 1.01
    effective_vmin = max(cp_mod.OB_LOG_VMIN, qty_thresh if qty_thresh > 0 else cp_mod.OB_LOG_VMIN)
    cmap_bid = plt.get_cmap(cp_mod.OB_BID_CMAP_NAME)
    cmap_ask = plt.get_cmap(cp_mod.OB_ASK_CMAP_NAME)
    if cp_mod.OB_COLOR_NORM == 'log':
        vmax = max(common_vmax, effective_vmin * 1.01)
        norm_bid = mcolors.LogNorm(vmin=effective_vmin, vmax=vmax, clip=True)
        norm_ask = mcolors.LogNorm(vmin=effective_vmin, vmax=vmax, clip=True)
    elif cp_mod.OB_COLOR_NORM == 'power':
        vmax = max(common_vmax, effective_vmin * 1.01)
        norm_bid = mcolors.PowerNorm(gamma=cp_mod.OB_POWER_GAMMA, vmin=effective_vmin, vmax=vmax, clip=True)
        norm_ask = mcolors.PowerNorm(gamma=cp_mod.OB_POWER_GAMMA, vmin=effective_vmin, vmax=vmax, clip=True)
    else:
        norm_bid = mcolors.Normalize(vmin=qty_thresh, vmax=common_vmax, clip=True)
        norm_ask = mcolors.Normalize(vmin=qty_thresh, vmax=common_vmax, clip=True)

    bid_pc_hm = ax_main_price.pcolormesh(time_edges_num_hm, price_bins_hm, bid_mask, cmap=cmap_bid, norm=norm_bid, shading='flat', zorder=1, alpha=0.8)
    ask_pc_hm = ax_main_price.pcolormesh(time_edges_num_hm, price_bins_hm, ask_mask, cmap=cmap_ask, norm=norm_ask, shading='flat', zorder=1, alpha=0.8)

    cbar_formatter = mticker.LogFormatterSciNotation(base=10) if cp_mod.OB_COLOR_NORM == 'log' else None
    gs_cbar_inner = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=ax_cbar_left.get_subplotspec(), hspace=0.1)
    ax_cbar_left.remove()
    fig = ax_main_price.figure
    if ask_pc_hm is not None:
        cax_ask = fig.add_subplot(gs_cbar_inner[0])
        cbar_ask = fig.colorbar(ask_pc_hm, cax=cax_ask, orientation='vertical', format=cbar_formatter)
        cbar_ask.set_label('Ask Quantity', fontsize=cp_mod.COLORBAR_LABEL_FONTSIZE, color='white')
        cbar_ask.ax.tick_params(labelsize=cp_mod.TICK_LABEL_FONTSIZE, colors='white')
        cax_ask.yaxis.set_ticks_position('left')
        cax_ask.yaxis.set_label_position('left')
    if bid_pc_hm is not None:
        cax_bid = fig.add_subplot(gs_cbar_inner[1])
        cbar_bid = fig.colorbar(bid_pc_hm, cax=cax_bid, orientation='vertical', format=cbar_formatter)
        cbar_bid.set_label('Bid Quantity', fontsize=cp_mod.COLORBAR_LABEL_FONTSIZE, color='white')
        cbar_bid.ax.tick_params(labelsize=cp_mod.TICK_LABEL_FONTSIZE, colors='white')
        cax_bid.yaxis.set_ticks_position('left')
        cax_bid.yaxis.set_label_position('left')
    return bid_pc_hm, ask_pc_hm


def scale_trade_sizes(qtys_plot: pd.Series, min_q_all: float, max_q_all: float):
    if len(qtys_plot) == 0:
        return pd.Series(dtype='float64')
    if np.isfinite(min_q_all) and np.isfinite(max_q_all) and max_q_all > min_q_all + 1e-9:
        scaled = TRADE_MARKER_SIZE_MIN + (np.power((qtys_plot - min_q_all) / (max_q_all - min_q_all), TRADE_MARKER_SIZE_POWER)) * (TRADE_MARKER_SIZE_MAX - TRADE_MARKER_SIZE_MIN)
    else:
        scaled = pd.Series([(TRADE_MARKER_SIZE_MIN + TRADE_MARKER_SIZE_MAX) / 2.0] * len(qtys_plot), index=qtys_plot.index)
    return np.nan_to_num(scaled.clip(lower=TRADE_MARKER_SIZE_MIN), nan=TRADE_MARKER_SIZE_MIN)


def draw_trade_circle_layer(ax_main_price, aggregated_trade_df: pd.DataFrame, cp_mod):
    if aggregated_trade_df.empty:
        return
    current_trade_threshold = cp_mod.TRADE_PLOT_MIN_QTY_THRESHOLD.get('Futures', 0.0)
    buy_df = aggregated_trade_df[aggregated_trade_df['buy_quantity'] >= current_trade_threshold].copy()
    sell_df = aggregated_trade_df[aggregated_trade_df['sell_quantity'] >= current_trade_threshold].copy()
    if not buy_df.empty:
        buy_df = buy_df.nlargest(TRADE_LIMIT_PER_SIDE, 'buy_quantity').sort_index()
    if not sell_df.empty:
        sell_df = sell_df.nlargest(TRADE_LIMIT_PER_SIDE, 'sell_quantity').sort_index()
    combined = pd.concat([
        buy_df['buy_quantity'] if not buy_df.empty else pd.Series(dtype='float64'),
        sell_df['sell_quantity'] if not sell_df.empty else pd.Series(dtype='float64'),
    ])
    min_q_all = combined.min() if not combined.empty else np.nan
    max_q_all = combined.max() if not combined.empty else np.nan

    if not buy_df.empty:
        sizes = scale_trade_sizes(buy_df['buy_quantity'], min_q_all, max_q_all)
        plot_df = pd.DataFrame({
            'time_num': mdates.date2num(buy_df.index.to_pydatetime()),
            'price': buy_df['close_price'],
            'size': sizes,
        }, index=buy_df.index).sort_values('size', ascending=True)
        ax_main_price.scatter(plot_df['time_num'], plot_df['price'], s=plot_df['size'], color=cp_mod.TRADE_BUY_COLOR, alpha=0.5, marker='o', edgecolors='w', linewidths=0.2, zorder=3.1, label='Buy Volume')
    if not sell_df.empty:
        sizes = scale_trade_sizes(sell_df['sell_quantity'], min_q_all, max_q_all)
        plot_df = pd.DataFrame({
            'time_num': mdates.date2num(sell_df.index.to_pydatetime()),
            'price': sell_df['close_price'],
            'size': sizes,
        }, index=sell_df.index).sort_values('size', ascending=True)
        ax_main_price.scatter(plot_df['time_num'], plot_df['price'], s=plot_df['size'], color=cp_mod.TRADE_SELL_COLOR, alpha=0.3, marker='o', edgecolors='w', linewidths=0.2, zorder=3.2, label='Sell Volume')


def draw_candle_layer(ax_main_price, ohlc_df: pd.DataFrame, cp_mod):
    if ohlc_df.empty:
        return
    width_days = (cp_mod.OHLCV_API_INTERVAL_MINUTES * 60 / (24 * 60 * 60)) * 0.9
    up = ohlc_df[ohlc_df['close'] >= ohlc_df['open']]
    down = ohlc_df[ohlc_df['close'] < ohlc_df['open']]
    up_idx_num = mdates.date2num(up.index.to_pydatetime())
    down_idx_num = mdates.date2num(down.index.to_pydatetime())
    ax_main_price.bar(up_idx_num, up['close'] - up['open'], width_days, bottom=up['open'], color=cp_mod.CANDLE_UP_BODY_COLOR, alpha=cp_mod.CANDLE_ALPHA, zorder=4.2, edgecolor=cp_mod.CANDLE_UP_BODY_COLOR, linewidth=max(cp_mod.CANDLE_EDGE_LW, 0.35))
    ax_main_price.bar(down_idx_num, down['close'] - down['open'], width_days, bottom=down['open'], color=cp_mod.CANDLE_DOWN_BODY_COLOR, alpha=cp_mod.CANDLE_ALPHA, zorder=4.2, edgecolor=cp_mod.CANDLE_DOWN_BODY_COLOR, linewidth=max(cp_mod.CANDLE_EDGE_LW, 0.35))
    ax_main_price.vlines(up_idx_num, up['low'], up['high'], color=cp_mod.CANDLE_UP_WICK_COLOR, linewidth=max(cp_mod.CANDLE_WICK_LW, 0.85), alpha=cp_mod.CANDLE_ALPHA, zorder=4.1)
    ax_main_price.vlines(down_idx_num, down['low'], down['high'], color=cp_mod.CANDLE_DOWN_WICK_COLOR, linewidth=max(cp_mod.CANDLE_WICK_LW, 0.85), alpha=cp_mod.CANDLE_ALPHA, zorder=4.1)


def draw_vwap_layer(ax_main_price, ohlc_df: pd.DataFrame, cp_mod):
    if ohlc_df.empty or 'volume' not in ohlc_df.columns or ohlc_df['volume'].isnull().all():
        return
    typical_price = (ohlc_df['high'] + ohlc_df['low'] + ohlc_df['close']) / 3
    pv = typical_price * ohlc_df['volume']
    idx_num = mdates.date2num(ohlc_df.index.to_pydatetime())
    for label, (period_val, color_val) in cp_mod.VWAP_PERIODS_CONFIG.items():
        if len(ohlc_df) >= period_val:
            rolling_pv_sum = pv.rolling(window=period_val, min_periods=1).sum()
            rolling_volume_sum = ohlc_df['volume'].rolling(window=period_val, min_periods=1).sum()
            vwap_series = np.where(rolling_volume_sum != 0, rolling_pv_sum / rolling_volume_sum, np.nan)
            ax_main_price.scatter(idx_num, vwap_series, s=cp_mod.VWAP_MARKER_SIZE, color=color_val, label=f'VWAP({label})', marker='o', edgecolors='none', zorder=2.5, alpha=cp_mod.VWAP_MARKER_ALPHA)


def draw_absorption_marker_layer(ax_main_price, markers, cfg):
    plot_cfg = cfg.get('plot', {})
    edge = plot_cfg.get('edge_color', '#ffffff')
    alpha = float(plot_cfg.get('alpha', 0.95))
    lw = float(plot_cfg.get('marker_linewidth', 0.7))
    for ev in markers:
        x = mdates.date2num(pd.Timestamp(ev['ts']).to_pydatetime())
        ax_main_price.scatter([x], [ev['price']], s=ev['size'], marker=ev['symbol'], color=ev['color'], edgecolors=edge, linewidths=lw, alpha=alpha, zorder=6)


def draw_orderbook_bar_layer(ax_ob_bars, book_df: pd.DataFrame, price_min: float, price_max: float, cp_mod):
    ax_ob_bars.set_ylim(price_min, price_max)
    ax_ob_bars.yaxis.tick_right()
    ax_ob_bars.yaxis.set_label_position('right')
    ax_ob_bars.yaxis.set_major_locator(mticker.MultipleLocator(200))
    ax_ob_bars.tick_params(axis='y', colors='white', labelsize=cp_mod.TICK_LABEL_FONTSIZE)
    ax_ob_bars.grid(True, axis='y', linestyle=':', linewidth=0.5, color='gray', alpha=0.3, zorder=0)

    max_bar_qty_abs = 1.0
    if not book_df.empty:
        latest = book_df.iloc[-1]
        latest_bids = latest.get('bids_json', {}) if isinstance(latest.get('bids_json', {}), dict) else {}
        latest_asks = latest.get('asks_json', {}) if isinstance(latest.get('asks_json', {}), dict) else {}
        num_price_bins_bar = int(np.ceil((price_max - price_min) / cp_mod.OB_BAR_AGGREGATION_PRICE))
        price_bins_bar_edges = np.linspace(price_min, price_max, num_price_bins_bar + 1)
        price_centers_bar = price_bins_bar_edges[:-1] + cp_mod.OB_BAR_AGGREGATION_PRICE / 2.0
        bid_qtys_bar = np.zeros(num_price_bins_bar)
        ask_qtys_bar = np.zeros(num_price_bins_bar)
        for p, q in latest_bids.items():
            if price_min <= p < price_max:
                i = int(np.floor((p - price_min) / cp_mod.OB_BAR_AGGREGATION_PRICE))
                if 0 <= i < num_price_bins_bar:
                    bid_qtys_bar[i] += q
        for p, q in latest_asks.items():
            if price_min <= p < price_max:
                i = int(np.floor((p - price_min) / cp_mod.OB_BAR_AGGREGATION_PRICE))
                if 0 <= i < num_price_bins_bar:
                    ask_qtys_bar[i] += q
        current_bid_max = bid_qtys_bar.max() if bid_qtys_bar.size > 0 else 0
        current_ask_max = ask_qtys_bar.max() if ask_qtys_bar.size > 0 else 0
        max_bar_qty_abs = max(1.0, current_bid_max, current_ask_max)
        bid_width = (bid_qtys_bar / max_bar_qty_abs) * cp_mod.OB_BAR_MAX_WIDTH_RATIO
        ask_width = (ask_qtys_bar / max_bar_qty_abs) * cp_mod.OB_BAR_MAX_WIDTH_RATIO
        ob_bid_color = plt.get_cmap(cp_mod.OB_BID_CMAP_NAME)(0.8)
        ob_ask_color = plt.get_cmap(cp_mod.OB_ASK_CMAP_NAME)(0.8)
        ax_ob_bars.barh(price_centers_bar, bid_width, height=cp_mod.OB_BAR_AGGREGATION_PRICE * 0.9, color=ob_bid_color, alpha=0.7, align='center', zorder=1)
        ax_ob_bars.barh(price_centers_bar, ask_width, height=cp_mod.OB_BAR_AGGREGATION_PRICE * 0.9, color=ob_ask_color, alpha=0.7, align='center', zorder=1)
        top_n = 5
        top_bids = np.argsort(bid_qtys_bar)[::-1][:top_n]
        top_asks = np.argsort(ask_qtys_bar)[::-1][:top_n]
        for i, p_center in enumerate(price_centers_bar):
            if i in top_bids and bid_qtys_bar[i] > 0.01:
                ax_ob_bars.text(bid_width[i] + cp_mod.OB_BAR_MAX_WIDTH_RATIO * 0.015, p_center, f'{bid_qtys_bar[i]:.1f}', ha='left', va='center', color='lightblue', fontsize=cp_mod.ORDER_BOOK_QTY_FONTSIZE, zorder=1.1)
            if i in top_asks and ask_qtys_bar[i] > 0.01:
                ax_ob_bars.text(ask_width[i] + cp_mod.OB_BAR_MAX_WIDTH_RATIO * 0.015, p_center, f'{ask_qtys_bar[i]:.1f}', ha='left', va='center', color='lightcoral', fontsize=cp_mod.ORDER_BOOK_QTY_FONTSIZE, zorder=1.1)
    ax_ob_bars.set_xlim(0, cp_mod.OB_BAR_MAX_WIDTH_RATIO * 1.1)
    ax_ob_bars.tick_params(axis='x', colors='white', labelsize=cp_mod.TICK_LABEL_FONTSIZE, pad=1)
    ax_ob_bars.xaxis.set_ticks_position('top')
    ax_ob_bars.xaxis.set_label_position('top')
    ax_ob_bars.set_xlabel('Order Book Qty (BTC)', color='white', fontsize=cp_mod.AXIS_LABEL_FONTSIZE, labelpad=3)

    def qty_formatter_func(x, pos):
        actual_qty = (x / cp_mod.OB_BAR_MAX_WIDTH_RATIO) * max_bar_qty_abs
        return y_fmt(actual_qty, pos)

    ax_ob_bars.xaxis.set_major_formatter(FuncFormatter(qty_formatter_func))
    ax_ob_bars.set_xticks(np.linspace(0, cp_mod.OB_BAR_MAX_WIDTH_RATIO, 3))
    ax_ob_bars.grid(True, axis='x', linestyle=':', alpha=0.2, color='gray', zorder=0)


def render_layered_chart(book_df: pd.DataFrame, aggregated_trade_df: pd.DataFrame, ohlc_data: pd.DataFrame, markers, cfg, market: str = 'Futures', symbol: str = 'BTC/USDT') -> io.BytesIO:
    center_price = compute_center_price(book_df, aggregated_trade_df, ohlc_data)
    price_min = center_price - (cp.OB_Y_AXIS_RANGE / 2.0)
    price_max = center_price + (cp.OB_Y_AXIS_RANGE / 2.0)
    time_min_dt_plot, time_max_dt_plot = compute_plot_window(book_df, aggregated_trade_df, ohlc_data, cp.HOURS_TO_PLOT)

    with plt.style.context('dark_background'):
        fig = plt.figure(figsize=(cp.FIG_WIDTH * 1.5, cp.FIG_HEIGHT))
        fig.patch.set_facecolor('#121212')
        gs_outer = gridspec.GridSpec(3, 1, height_ratios=[6.5, 0.001, 0.001], hspace=0.0, left=0.06, right=0.94, bottom=0.12, top=0.92)
        current_grid_ratios = cp.GRIDSPEC_WIDTH_RATIOS_WITH_BAR.copy()
        gs_top_outer = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_outer[0], width_ratios=[current_grid_ratios[0], current_grid_ratios[1] + current_grid_ratios[2]], wspace=0.054)
        ax_cbar_left = fig.add_subplot(gs_top_outer[0])
        gs_top_inner = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_top_outer[1], width_ratios=[current_grid_ratios[1], current_grid_ratios[2]], wspace=0)
        ax_main_price = fig.add_subplot(gs_top_inner[0])
        ax_ob_bars = fig.add_subplot(gs_top_inner[1])
        for ax_ in [ax_cbar_left, ax_main_price, ax_ob_bars]:
            ax_.set_facecolor(cp.BG_COLOR)

        ax_main_price.set_ylim(price_min, price_max)
        ax_main_price.yaxis.tick_right()
        ax_main_price.yaxis.set_label_position('right')
        ax_main_price.yaxis.set_major_locator(mticker.MultipleLocator(200))
        ax_main_price.tick_params(axis='y', colors='white', labelsize=cp.TICK_LABEL_FONTSIZE, labelright=False)
        ax_main_price.yaxis.set_major_formatter(price_formatter)
        ax_main_price.set_xlim(mdates.date2num(time_min_dt_plot), mdates.date2num(time_max_dt_plot))
        ax_main_price.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))
        ax_main_price.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M', tz=JST))
        ax_main_price.tick_params(axis='x', colors='white', labelsize=cp.TICK_LABEL_FONTSIZE, bottom=True, labelbottom=True)
        ax_main_price.xaxis.get_offset_text().set_visible(False)
        ax_main_price.grid(True, axis='x', linestyle=':', alpha=0.3, color='gray', zorder=0)

        draw_heatmap_layer(ax_main_price, ax_cbar_left, book_df, price_min, price_max, cp, time_min_dt_plot, time_max_dt_plot)
        visible_ohlc = ohlc_data[(ohlc_data.index >= time_min_dt_plot) & (ohlc_data.index <= time_max_dt_plot)] if not ohlc_data.empty else pd.DataFrame()
        draw_candle_layer(ax_main_price, visible_ohlc, cp)
        draw_vwap_layer(ax_main_price, visible_ohlc, cp)
        draw_trade_circle_layer(ax_main_price, aggregated_trade_df, cp)
        draw_absorption_marker_layer(ax_main_price, markers, cfg)
        draw_orderbook_bar_layer(ax_ob_bars, book_df, price_min, price_max, cp)

        latest_ohlc_visible = visible_ohlc.iloc[-1] if not visible_ohlc.empty else None
        if latest_ohlc_visible is not None:
            latest_plot_price = latest_ohlc_visible['close']
            latest_price_color = cp.CANDLE_UP_BODY_COLOR if latest_ohlc_visible['close'] >= latest_ohlc_visible['open'] else cp.CANDLE_DOWN_BODY_COLOR
            ax_ob_bars.text(0.38, latest_plot_price, f'{latest_plot_price:.2f}', transform=ax_ob_bars.get_yaxis_transform(), fontsize=max(cp.TICK_LABEL_FONTSIZE * 2.2, 18), fontweight='bold', color=latest_price_color, va='center', ha='left', bbox=dict(boxstyle='round,pad=0.28', fc='black', ec=latest_price_color, lw=1.0, alpha=0.82), zorder=6)
            ax_ob_bars.axhline(latest_plot_price, color=latest_price_color, linestyle='--', linewidth=0.8, alpha=0.7, zorder=4)

        main_handles, main_labels = ax_main_price.get_legend_handles_labels()
        if markers:
            main_handles.append(Line2D([0], [0], marker=cfg['plot'].get('buy_marker', 'o'), color='none', label='Buy absorption', markerfacecolor=cfg['plot'].get('buy_color', '#3b82f6'), markeredgecolor='white', markersize=8))
            main_handles.append(Line2D([0], [0], marker=cfg['plot'].get('sell_marker', 'o'), color='none', label='Sell absorption', markerfacecolor=cfg['plot'].get('sell_color', '#ef4444'), markeredgecolor='white', markersize=8))
            main_labels.extend(['Buy absorption', 'Sell absorption'])
        if main_handles:
            ax_main_price.legend(handles=main_handles, labels=main_labels, fontsize=cp.LEGEND_FONTSIZE, loc='upper left', bbox_to_anchor=(0.01, 0.99), framealpha=0.7, labelcolor='white').get_frame().set_facecolor('black')

        title_time_str = time_max_dt_plot.astimezone(JST).strftime('%Y-%m-%d %H:%M') if pd.notna(time_max_dt_plot) else 'N/A'
        fig.suptitle(f"{cp.EXCHANGE_NAME} {symbol.replace('/', '_')} [{market}] Layered Flow Chart {VERSION_LABEL} ({cp.OHLCV_API_INTERVAL} Candle) - {title_time_str} JST", color='white', fontsize=cp.TITLE_FONTSIZE, y=0.96)
        try:
            fig.canvas.draw()
            fig.tight_layout(rect=[0.03, 0.04, 0.97, 0.95])
        except Exception:
            pass
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=400, facecolor=fig.get_facecolor())
        img_buffer.seek(0)
        plt.close(fig)
        return img_buffer


def upload_output_if_needed(out_png: Path, discord_channel_id: str | None, discord_message: str = ''):
    if not discord_channel_id:
        return None
    response = upload_file(discord_channel_id, out_png, discord_message)
    print(f"UPLOAD_OK channel={discord_channel_id} message_id={response.get('id')} file={out_png}")
    return response


async def run_once(hours_to_plot: int = 8, data_dir: Path | None = None, out_png: Path | None = None, ohlcv_cache_path: Path | None = None, absorption_config_path: Path | None = None, discord_channel_id: str | None = None, discord_message: str = ''):
    cp.HOURS_TO_PLOT = hours_to_plot if hours_to_plot else HOURS_TO_PLOT_OVERRIDE
    cp.OB_TIME_RESOLUTION = OB_TIME_RESOLUTION_OVERRIDE
    cp.OB_Y_AXIS_RANGE = OB_Y_AXIS_RANGE_OVERRIDE
    cp.OHLCV_API_INTERVAL = OHLCV_INTERVAL_OVERRIDE
    cp.OHLCV_API_INTERVAL_MINUTES = OHLCV_INTERVAL_MIN_OVERRIDE
    cp.OI_FETCH_INTERVAL = OHLCV_INTERVAL_OVERRIDE
    cp.VWAP_PERIODS_CONFIG = {
        '12H': (int(12 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FFFFFF'),
        '24H': (int(24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FFD700'),
        '7D':  (int(7 * 24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FFA500'),
        '14D': (int(14 * 24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#87CEEB'),
        '30D': (int(30 * 24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FF00FF'),
    }
    plt.rcParams['savefig.dpi'] = SAVEFIG_DPI_OVERRIDE

    data_dir = data_dir or DEFAULT_DATA_DIR
    out_png = out_png or DEFAULT_OUT_PNG
    ohlcv_cache_path = ohlcv_cache_path or DEFAULT_OHLCV_CACHE_PATH
    absorption_config_path = absorption_config_path or DEFAULT_ABSORPTION_CFG_PATH
    cfg = load_absorption_config(absorption_config_path)
    market = 'Futures'
    symbol = cp.SYMBOL
    now_utc = pd.Timestamp.now(tz=pytz.utc)

    inputs = resolve_inputs_v3(data_dir)
    book_df = ws.load_book_data_with_stats_ws(market, cp.HOURS_TO_PLOT, inputs)
    agg_df = ws.load_aggregated_trade_data_ws(market, cp.HOURS_TO_PLOT, inputs)

    ohlcv_start = now_utc - pd.Timedelta(hours=cp.HOURS_TO_PLOT + 1)
    ohlcv_df = ws.load_ohlcv_cache(ohlcv_cache_path, OHLCV_CACHE_TTL_SEC)
    ohlcv_cache_hit = ohlc_df is not None if 'ohlc_df' in locals() else False
    if ohlcv_df is None:
        async with aiohttp.ClientSession() as session:
            ohlcv_df = await cp.fetch_binance_ohlcv_from_api(session, market, cp.FUTURES_SYMBOL_API, cp.OHLCV_API_INTERVAL, ohlcv_start, now_utc)
        if isinstance(ohlcv_df, pd.DataFrame) and not ohlcv_df.empty:
            ws.save_ohlcv_cache(ohlcv_cache_path, ohlcv_df)
        ohlcv_cache_hit = False
    else:
        ohlcv_cache_hit = True

    if not ohlcv_df.empty and 'volume' in ohlcv_df.columns and cp.VOLUME_EMA_HOURS > 0:
        interval_seconds = cp.OHLCV_API_INTERVAL_MINUTES * 60
        ema_span = max(1, int(cp.VOLUME_EMA_HOURS * 3600 / interval_seconds))
        if len(ohlcv_df) > ema_span:
            ohlcv_df['volume_ema'] = ohlcv_df['volume'].ewm(span=ema_span, adjust=False).mean()
        else:
            ohlcv_df['volume_ema'] = np.nan

    feature_df = load_feature_rows(inputs['feature_jsonl'], ohlcv_start) if inputs['feature_jsonl'].exists() else pd.DataFrame()
    visible_bars = aggregate_feature_bars(feature_df, ohlcv_df, cfg) if not feature_df.empty else pd.DataFrame()
    markers = compute_absorption_markers(visible_bars, cfg)

    img = render_layered_chart(book_df, agg_df, ohlcv_df, markers, cfg, market=market, symbol=symbol)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with open(out_png, 'wb') as f:
        f.write(img.getvalue())

    print(f"OK version={VERSION_LABEL} out={out_png} rows(book={len(book_df)}, agg={len(agg_df)}, ohlcv={len(ohlcv_df)}, features={len(feature_df)}) markers={len(markers)} hours={cp.HOURS_TO_PLOT} ohlcv_cache_hit={ohlcv_cache_hit}")

    if discord_channel_id:
        upload_output_if_needed(out_png, discord_channel_id, discord_message)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Single-pass layered orderheatmap renderer preserving heatmap and trade circles')
    ap.add_argument('--data-dir', default=str(DEFAULT_DATA_DIR))
    ap.add_argument('--out', default=str(DEFAULT_OUT_PNG))
    ap.add_argument('--ohlcv-cache', default=str(DEFAULT_OHLCV_CACHE_PATH))
    ap.add_argument('--hours', type=int, default=8)
    ap.add_argument('--absorption-config', default=str(DEFAULT_ABSORPTION_CFG_PATH))
    ap.add_argument('--discord-channel-id', default='')
    ap.add_argument('--discord-message', default='')
    args = ap.parse_args()
    try:
        asyncio.run(run_once(args.hours, Path(args.data_dir), Path(args.out), Path(args.ohlcv_cache), Path(args.absorption_config), args.discord_channel_id or None, args.discord_message))
    except DiscordUploadError as exc:
        raise SystemExit(f'Discord upload failed: {exc}')
    except Exception as exc:
        raise SystemExit(str(exc))
