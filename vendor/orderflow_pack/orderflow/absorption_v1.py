"""Absorption marker builder v1.

This module converts v1 classifier output into plot markers.
It intentionally keeps marker creation separate from feature construction and classification.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from absorption_classifier import classify_absorption_v1


def _safe_float(v):
    try:
        x = float(v)
        if np.isfinite(x):
            return x
    except Exception:
        return None
    return None


def _score_to_size(score: float, cfg: dict, score_floor: float, score_cap: float) -> float:
    plot_cfg = cfg.get('plot', {})
    min_size = float(cfg.get('absorption_v1_marker_min_size', plot_cfg.get('small_size', 30.0)))
    max_size = float(cfg.get('absorption_v1_marker_max_size', min(plot_cfg.get('medium_size', 200.0), 220.0)))
    if score_cap <= score_floor:
        return min_size
    t = max(0.0, min(1.0, (float(score) - score_floor) / (score_cap - score_floor)))
    # sqrt compression: keep separation but avoid almost everything becoming max.
    t = math.sqrt(t)
    return min_size + t * (max_size - min_size)


def _marker_price(row: pd.Series, side: str, cfg: dict) -> float | None:
    plot_cfg = cfg.get('plot', {})
    high = _safe_float(row.get('high'))
    low = _safe_float(row.get('low'))
    close = _safe_float(row.get('close'))
    ref = _safe_float(plot_cfg.get('marker_price_reference', close))
    if high is None or low is None:
        return close
    offset_bps = float(plot_cfg.get('marker_offset_bps', 50.0))
    offset_price = ref * offset_bps / 10000.0
    if side == 'buy_absorption':
        return high + offset_price
    if side == 'sell_absorption':
        return low - offset_price
    return close


def _cooldown_filter(markers: list[dict], min_bars_between_same_side: int) -> list[dict]:
    if min_bars_between_same_side <= 0 or not markers:
        return markers
    kept: list[dict] = []
    last_index_by_side: dict[str, int] = {}
    for idx, ev in enumerate(sorted(markers, key=lambda x: x['ts'])):
        side = ev.get('side', '')
        last_idx = last_index_by_side.get(side)
        if last_idx is not None and idx - last_idx <= min_bars_between_same_side:
            # If two same-side events are too close, keep the stronger one.
            if kept and kept[-1].get('side') == side and ev.get('score', 0.0) > kept[-1].get('score', 0.0):
                kept[-1] = ev
                last_index_by_side[side] = idx
            continue
        kept.append(ev)
        last_index_by_side[side] = idx
    return kept


def compute_absorption_markers_v1(feature_df: pd.DataFrame, cfg: dict) -> list[dict]:
    if feature_df is None or feature_df.empty or not cfg.get('enabled', True):
        return []

    classified = classify_absorption_v1(feature_df, cfg)
    if classified.empty:
        return []

    plot_cfg = cfg.get('plot', {})
    work = classified.copy().reset_index()
    if 'ts' not in work.columns:
        work = work.rename(columns={work.columns[0]: 'ts'})
    work['ts'] = pd.to_datetime(work['ts'], utc=True, errors='coerce')
    work = work.dropna(subset=['ts'])

    display = work[work.get('absorption_v1_label', 'none').isin(['buy_absorption', 'sell_absorption'])].copy()
    if display.empty:
        return []

    def _row_score(row):
        side = str(row.get('absorption_v1_label'))
        score_col = 'buy_absorption_score' if side == 'buy_absorption' else 'sell_absorption_score'
        return _safe_float(row.get(score_col)) or 0.0

    display['_display_score'] = display.apply(_row_score, axis=1)
    min_score = float(cfg.get('absorption_v1_min_display_score', 4.8))
    display = display[display['_display_score'] >= min_score]
    if display.empty:
        return []

    top_n = int(cfg.get('absorption_v1_max_markers', 12))
    if top_n > 0 and len(display) > top_n:
        display = display.nlargest(top_n, '_display_score').sort_values('ts')

    score_floor = float(display['_display_score'].quantile(float(cfg.get('absorption_v1_size_floor_quantile', 0.20))))
    score_cap = float(display['_display_score'].quantile(float(cfg.get('absorption_v1_size_cap_quantile', 0.95))))
    score_floor = max(score_floor, min_score)

    markers: list[dict] = []
    for _, row in display.iterrows():
        side = str(row.get('absorption_v1_label', 'none'))
        score = _safe_float(row.get('_display_score')) or 0.0
        price = _marker_price(row, side, cfg)
        if price is None:
            continue
        markers.append({
            'ts': row['ts'],
            'side': side,
            'score': score,
            'price': float(price),
            'size': _score_to_size(score, cfg, score_floor, score_cap),
            'color': plot_cfg.get('buy_color', '#3b82f6') if side == 'buy_absorption' else plot_cfg.get('sell_color', '#ef4444'),
            'symbol': plot_cfg.get('buy_marker', 'o') if side == 'buy_absorption' else plot_cfg.get('sell_marker', 'o'),
            'label': side,
            'buy_pressure_z': _safe_float(row.get('buy_pressure_z')),
            'sell_pressure_z': _safe_float(row.get('sell_pressure_z')),
            'ask_refill_z': _safe_float(row.get('ask_refill_z')),
            'bid_refill_z': _safe_float(row.get('bid_refill_z')),
            'close_pos': _safe_float(row.get('close_pos')),
        })

    keep_strongest = plot_cfg.get('keep_strongest_per_bar', True)
    if keep_strongest:
        strongest: dict[tuple[pd.Timestamp, str], dict] = {}
        for ev in markers:
            key = (ev['ts'], ev['side'])
            if key not in strongest or ev.get('score', 0.0) > strongest[key].get('score', 0.0):
                strongest[key] = ev
        markers = sorted(strongest.values(), key=lambda x: x['ts'])
    else:
        markers = sorted(markers, key=lambda x: x['ts'])

    cooldown = int(cfg.get('absorption_v1_min_bars_between_same_side', 2))
    markers = _cooldown_filter(markers, cooldown)
    return markers
