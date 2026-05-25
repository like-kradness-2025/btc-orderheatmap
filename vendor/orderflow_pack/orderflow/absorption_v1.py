"""Absorption marker builder v1.

This module converts v1 classifier output into plot markers.
It intentionally keeps marker creation separate from feature construction and classification.
"""
from __future__ import annotations

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


def _score_to_size(score: float, cfg: dict) -> float:
    plot_cfg = cfg.get('plot', {})
    min_score = float(cfg.get('absorption_v1_min_display_score', 3.0))
    large_score = float(cfg.get('absorption_v1_large_score', 5.0))
    min_size = float(plot_cfg.get('small_size', 80.0))
    max_size = float(plot_cfg.get('large_size', 600.0))
    if large_score <= min_score:
        return min_size
    t = max(0.0, min(1.0, (float(score) - min_score) / (large_score - min_score)))
    return min_size + t * (max_size - min_size)


def _marker_price(row: pd.Series, side: str, cfg: dict) -> float | None:
    plot_cfg = cfg.get('plot', {})
    offset_ratio = float(plot_cfg.get('y_offset_ratio') or plot_cfg.get('marker_price_fallback_offset_ratio', 0.02))
    high = _safe_float(row.get('high'))
    low = _safe_float(row.get('low'))
    close = _safe_float(row.get('close'))
    if high is None or low is None:
        return close
    span = max(high - low, 1e-9)
    if side == 'buy_absorption':
        return high + span * offset_ratio
    if side == 'sell_absorption':
        return low - span * offset_ratio
    return close


def compute_absorption_markers_v1(feature_df: pd.DataFrame, cfg: dict) -> list[dict]:
    if feature_df is None or feature_df.empty or not cfg.get('enabled', True):
        return []

    classified = classify_absorption_v1(feature_df, cfg)
    if classified.empty:
        return []

    plot_cfg = cfg.get('plot', {})
    markers: list[dict] = []
    work = classified.copy().reset_index()
    if 'ts' not in work.columns:
        work = work.rename(columns={work.columns[0]: 'ts'})
    work['ts'] = pd.to_datetime(work['ts'], utc=True, errors='coerce')
    work = work.dropna(subset=['ts'])

    for _, row in work.iterrows():
        label = str(row.get('absorption_v1_label', 'none'))
        if label not in {'buy_absorption', 'sell_absorption'}:
            continue
        side = label
        score_col = 'buy_absorption_score' if side == 'buy_absorption' else 'sell_absorption_score'
        score = _safe_float(row.get(score_col)) or 0.0
        price = _marker_price(row, side, cfg)
        if price is None:
            continue
        markers.append({
            'ts': row['ts'],
            'side': side,
            'score': score,
            'price': float(price),
            'size': _score_to_size(score, cfg),
            'color': plot_cfg.get('buy_color', '#3b82f6') if side == 'buy_absorption' else plot_cfg.get('sell_color', '#ef4444'),
            'symbol': plot_cfg.get('buy_marker', 'o') if side == 'buy_absorption' else plot_cfg.get('sell_marker', 'o'),
            'label': label,
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
    return markers
