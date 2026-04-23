import argparse
import asyncio
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
TARGET_PATH = BASE / 'chartProt3_ws_layered_v3.py'


def load_target_module():
    spec = importlib.util.spec_from_file_location('chartProt3_ws_layered_v3_base_v322', str(TARGET_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


base = load_target_module()
base.VERSION_LABEL = 'v3.22'


PRICE_CANDIDATE_COLS = [
    'best_ask_price',
    'best_bid_price',
    'ask_price',
    'bid_price',
    'trade_price',
    'price',
    'last_price',
    'mid_price',
    'mid',
]


old_aggregate_feature_bars = base.aggregate_feature_bars


def aggregate_feature_bars(feature_df: pd.DataFrame, ohlc_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    out = old_aggregate_feature_bars(feature_df, ohlc_df, cfg)
    if out.empty or feature_df.empty:
        return out
    work = feature_df.copy()
    interval = cfg.get('bar_interval', '5min')
    work['bar_ts'] = pd.to_datetime(work['ts'], utc=True, errors='coerce').dt.floor(interval)
    extra = {}
    for col in PRICE_CANDIDATE_COLS:
        if col in work.columns:
            extra[col] = 'last'
    if extra:
        grouped_extra = work.groupby('bar_ts').agg(extra)
        out = out.join(grouped_extra, how='left')
    return out


def _safe_float(v):
    try:
        x = float(v)
        if np.isfinite(x):
            return x
    except Exception:
        return None
    return None


def _round_to_tick(price: float, tick: float | None):
    if tick is None or tick <= 0:
        return float(price)
    return round(float(price) / tick) * tick


def _pick_price_from_row(row, side: str, tick: float | None):
    side_candidates = {
        'buy_absorption': ['best_ask_price', 'ask_price', 'trade_price', 'price', 'last_price', 'mid_price', 'mid'],
        'sell_absorption': ['best_bid_price', 'bid_price', 'trade_price', 'price', 'last_price', 'mid_price', 'mid'],
    }
    for col in side_candidates.get(side, []):
        if col in row.index:
            val = _safe_float(row[col])
            if val is not None and val > 0:
                return _round_to_tick(val, tick)
    return None


def _fallback_marker_price(row, side: str, plot_cfg: dict, tick: float | None):
    fallback = plot_cfg.get('marker_price_fallback', 'bar_extreme_offset')
    offset_ratio = float(plot_cfg.get('marker_price_fallback_offset_ratio', 0.02))
    high = _safe_float(row.get('high'))
    low = _safe_float(row.get('low'))
    open_ = _safe_float(row.get('open'))
    close = _safe_float(row.get('close'))
    if high is None or low is None:
        return None
    span = max(high - low, 1e-9)

    if fallback == 'bar_body_edge' and open_ is not None and close is not None:
        if side == 'buy_absorption':
            price = max(open_, close) + span * offset_ratio
        else:
            price = min(open_, close) - span * offset_ratio
        return _round_to_tick(price, tick)

    if fallback == 'bar_body_mid' and open_ is not None and close is not None:
        body_hi = max(open_, close)
        body_lo = min(open_, close)
        if side == 'buy_absorption':
            price = body_hi - (body_hi - body_lo) * 0.25
        else:
            price = body_lo + (body_hi - body_lo) * 0.25
        return _round_to_tick(price, tick)

    if side == 'buy_absorption':
        price = high + span * offset_ratio
    else:
        price = low - span * offset_ratio
    return _round_to_tick(price, tick)


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

    work['ti_norm'] = base.normalize_series(work['trade_imbalance_notional_window'], q=norm_q, floor=norm_floor)
    work['mid_move_norm'] = base.normalize_series(work['mid_move_window_bps'], q=move_q, floor=move_floor)
    work['ask_replenish_norm'] = base.normalize_series(work['net_ask_add_cancel_notional_window'], q=norm_q, floor=norm_floor)
    work['bid_replenish_norm'] = base.normalize_series(work['net_bid_add_cancel_notional_window'], q=norm_q, floor=norm_floor)
    work['best_ask_delta_norm'] = base.normalize_series(work['best_ask_qty_delta_window'], q=norm_q, floor=norm_floor)
    work['best_bid_delta_norm'] = base.normalize_series(work['best_bid_qty_delta_window'], q=norm_q, floor=norm_floor)
    work['depth_ask_delta_norm'] = base.normalize_series(work['depth_ask_notional_5bps_delta_window'], q=norm_q, floor=norm_floor)
    work['depth_bid_delta_norm'] = base.normalize_series(work['depth_bid_notional_5bps_delta_window'], q=norm_q, floor=norm_floor)

    min_score = float(cfg.get('minimum_score', 1.75))
    medium_score = float(cfg.get('medium_score', 2.5))
    large_score = float(cfg.get('large_score', 3.6))
    min_ti_abs = float(cfg.get('minimum_trade_imbalance_notional', 0.0))
    tick = _safe_float(plot_cfg.get('marker_price_tick_size'))
    marker_price_mode = plot_cfg.get('marker_price_mode', 'quote_first')

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
            float(cfg.get('buy_trade_weight', 1.0)) * base._positive(ti)
            + float(cfg.get('ask_replenish_weight', 1.0)) * base._positive(row['ask_replenish_norm'])
            + float(cfg.get('best_ask_delta_weight', 0.6)) * base._positive(row['best_ask_delta_norm'])
            + float(cfg.get('depth_ask_delta_weight', 0.6)) * base._positive(row['depth_ask_delta_norm'])
            + float(cfg.get('buy_stall_weight', 0.8)) * base._negative_abs(move)
        )
        sell_score = (
            float(cfg.get('sell_trade_weight', 1.0)) * base._negative_abs(ti)
            + float(cfg.get('bid_replenish_weight', 1.0)) * base._positive(row['bid_replenish_norm'])
            + float(cfg.get('best_bid_delta_weight', 0.6)) * base._positive(row['best_bid_delta_norm'])
            + float(cfg.get('depth_bid_delta_weight', 0.6)) * base._positive(row['depth_bid_delta_norm'])
            + float(cfg.get('sell_stall_weight', 0.8)) * base._positive(move)
        )
        buy_trigger = raw_ti > min_ti_abs and buy_score >= min_score
        sell_trigger = raw_ti < -min_ti_abs and sell_score >= min_score
        if buy_trigger and (not sell_trigger or buy_score >= sell_score):
            side = 'buy_absorption'
            score = buy_score
        elif sell_trigger:
            side = 'sell_absorption'
            score = sell_score
        else:
            continue

        price = None
        if marker_price_mode == 'quote_first':
            price = _pick_price_from_row(row, side, tick)
        if price is None:
            price = _fallback_marker_price(row, side, plot_cfg, tick)
        if price is None:
            continue
        markers.append({
            'ts': row['ts'],
            'side': side,
            'score': score,
            'price': float(price),
            'size': score_to_size(score),
            'color': plot_cfg.get('buy_color', '#3b82f6') if side == 'buy_absorption' else plot_cfg.get('sell_color', '#ef4444'),
            'symbol': plot_cfg.get('buy_marker', 'o') if side == 'buy_absorption' else plot_cfg.get('sell_marker', 'o'),
        })

    if plot_cfg.get('keep_strongest_per_bar', True):
        strongest = {}
        for ev in markers:
            key = (ev['ts'], ev['side'])
            if key not in strongest or ev['score'] > strongest[key]['score']:
                strongest[key] = ev
        markers = sorted(strongest.values(), key=lambda x: x['ts'])
    return markers


base.aggregate_feature_bars = aggregate_feature_bars
base.compute_absorption_markers = compute_absorption_markers


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Single-pass layered orderheatmap renderer with improved marker price anchoring')
    ap.add_argument('--data-dir', default=str(base.DEFAULT_DATA_DIR))
    ap.add_argument('--out', default=str(base.DEFAULT_OUT_PNG))
    ap.add_argument('--ohlcv-cache', default=str(base.DEFAULT_OHLCV_CACHE_PATH))
    ap.add_argument('--hours', type=int, default=8)
    ap.add_argument('--absorption-config', default=str(base.DEFAULT_ABSORPTION_CFG_PATH))
    ap.add_argument('--discord-channel-id', default='')
    ap.add_argument('--discord-message', default='')
    args = ap.parse_args()
    try:
        asyncio.run(base.run_once(args.hours, Path(args.data_dir), Path(args.out), Path(args.ohlcv_cache), Path(args.absorption_config), args.discord_channel_id or None, args.discord_message))
    except DiscordUploadError as exc:
        raise SystemExit(f'Discord upload failed: {exc}')
    except Exception as exc:
        raise SystemExit(str(exc))
