from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from PIL import Image


@dataclass
class MarkerEvent:
    ts: pd.Timestamp
    side: str
    score: float
    price: float
    size: float
    color: str
    symbol: str


def load_config(config_path: Path | None) -> dict:
    if config_path is None or not config_path.exists():
        return {}
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def merge_config(default_cfg: dict, override_cfg: dict | None) -> dict:
    override_cfg = override_cfg or {}
    out = json.loads(json.dumps(default_cfg))
    for k, v in override_cfg.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def read_jsonl_recent_until(path: Path, start_ts: pd.Timestamp | None, chunk_bytes: int = 32 * 1024 * 1024, max_bytes: int = 256 * 1024 * 1024):
    rows = []
    if not path.exists():
        return rows
    size = path.stat().st_size
    if size <= 0:
        return rows
    read_bytes = 0
    with open(path, 'rb') as f:
        pos = size
        carry = b''
        while pos > 0 and read_bytes < max_bytes:
            take = min(chunk_bytes, pos)
            pos -= take
            f.seek(pos)
            chunk = f.read(take)
            read_bytes += take
            data = chunk + carry
            lines = data.splitlines()
            if pos > 0 and lines:
                carry = lines.pop(0)
            else:
                carry = b''
            parsed = []
            for ln in lines:
                if not ln.strip():
                    continue
                try:
                    parsed.append(json.loads(ln.decode('utf-8', errors='ignore')))
                except Exception:
                    pass
            if parsed:
                rows = parsed + rows
                if start_ts is not None:
                    oldest_ts = pd.to_datetime(parsed[0].get('ts'), utc=True, errors='coerce')
                    if pd.notna(oldest_ts) and oldest_ts <= start_ts:
                        break
        if carry.strip():
            try:
                rows.insert(0, json.loads(carry.decode('utf-8', errors='ignore')))
            except Exception:
                pass
    return rows


def load_feature_rows(feature_path: Path, start_ts: pd.Timestamp | None) -> pd.DataFrame:
    rows = read_jsonl_recent_until(feature_path, start_ts)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df['ts'] = pd.to_datetime(df['ts'], utc=True, errors='coerce')
    df = df.dropna(subset=['ts']).sort_values('ts').reset_index(drop=True)
    if start_ts is not None:
        df = df[df['ts'] >= start_ts]
    return df


def aggregate_features_to_bars(feature_df: pd.DataFrame, ohlc_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    if feature_df.empty or ohlc_df.empty:
        return pd.DataFrame()

    feature_df = feature_df.copy()
    interval = cfg.get('bar_interval', '5min')
    agg_cfg = cfg.get('aggregation', {})
    feature_df['bar_ts'] = feature_df['ts'].dt.floor(interval)

    numeric_cols = list(agg_cfg.keys())
    for col in numeric_cols:
        if col in feature_df.columns:
            feature_df[col] = pd.to_numeric(feature_df[col], errors='coerce')
        else:
            feature_df[col] = np.nan

    agg_map = {}
    for col, how in agg_cfg.items():
        agg_map[col] = how

    grouped = feature_df.groupby('bar_ts').agg(agg_map)
    out = ohlc_df[['open', 'high', 'low', 'close']].copy()
    out.index = pd.to_datetime(out.index, utc=True)
    out = out.join(grouped, how='left')
    return out.dropna(subset=['open', 'high', 'low', 'close'])


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


def compute_absorption_markers(bar_df: pd.DataFrame, cfg: dict) -> list[MarkerEvent]:
    if bar_df.empty:
        return []

    plot_cfg = cfg.get('plot', {})
    work = bar_df.copy()
    work = work.reset_index().rename(columns={'index': 'ts'})
    work['ts'] = pd.to_datetime(work['ts'], utc=True, errors='coerce')
    work = work.dropna(subset=['ts'])

    norm_q = float(cfg.get('normalize_quantile', 0.95))
    norm_floor = float(cfg.get('normalize_floor', 1.0))
    move_q = float(cfg.get('mid_move_quantile', 0.90))
    move_floor = float(cfg.get('mid_move_floor', 0.25))

    for col in [
        'trade_imbalance_notional_window', 'mid_move_window_bps',
        'net_ask_add_cancel_notional_window', 'net_bid_add_cancel_notional_window',
        'best_ask_qty_delta_window', 'best_bid_qty_delta_window',
        'depth_ask_notional_5bps_delta_window', 'depth_bid_notional_5bps_delta_window'
    ]:
        work[col] = pd.to_numeric(work.get(col), errors='coerce').fillna(0.0)

    work['ti_norm'] = normalize_series(work['trade_imbalance_notional_window'], q=norm_q, floor=norm_floor)
    work['mid_move_norm'] = normalize_series(work['mid_move_window_bps'], q=move_q, floor=move_floor)
    work['ask_replenish_norm'] = normalize_series(work['net_ask_add_cancel_notional_window'], q=norm_q, floor=norm_floor)
    work['bid_replenish_norm'] = normalize_series(work['net_bid_add_cancel_notional_window'], q=norm_q, floor=norm_floor)
    work['best_ask_delta_norm'] = normalize_series(work['best_ask_qty_delta_window'], q=norm_q, floor=norm_floor)
    work['best_bid_delta_norm'] = normalize_series(work['best_bid_qty_delta_window'], q=norm_q, floor=norm_floor)
    work['depth_ask_delta_norm'] = normalize_series(work['depth_ask_notional_5bps_delta_window'], q=norm_q, floor=norm_floor)
    work['depth_bid_delta_norm'] = normalize_series(work['depth_bid_notional_5bps_delta_window'], q=norm_q, floor=norm_floor)

    price_range = max(float(work['high'].max() - work['low'].min()), 1.0)
    base_y_offset_ratio = float(plot_cfg.get('y_offset_ratio', 0.012))
    base_y_offset = price_range * base_y_offset_ratio
    
    # padding for marker clearance (in price units)
    padding_ratio = float(plot_cfg.get('y_offset_padding_ratio', 0.008))
    padding_offset = price_range * padding_ratio

    min_score = float(cfg.get('minimum_score', 1.75))
    medium_score = float(cfg.get('medium_score', 2.5))
    large_score = float(cfg.get('large_score', 3.6))
    min_ti_abs = float(cfg.get('minimum_trade_imbalance_notional', 0.0))

    buy_trade_weight = float(cfg.get('buy_trade_weight', 1.0))
    sell_trade_weight = float(cfg.get('sell_trade_weight', 1.0))
    ask_replenish_weight = float(cfg.get('ask_replenish_weight', 1.0))
    bid_replenish_weight = float(cfg.get('bid_replenish_weight', 1.0))
    best_ask_delta_weight = float(cfg.get('best_ask_delta_weight', 0.6))
    best_bid_delta_weight = float(cfg.get('best_bid_delta_weight', 0.6))
    depth_ask_delta_weight = float(cfg.get('depth_ask_delta_weight', 0.6))
    depth_bid_delta_weight = float(cfg.get('depth_bid_delta_weight', 0.6))
    buy_stall_weight = float(cfg.get('buy_stall_weight', 0.8))
    sell_stall_weight = float(cfg.get('sell_stall_weight', 0.8))

    def score_to_size(score: float) -> float:
        if score >= large_score:
            return float(plot_cfg.get('large_size', 170.0))
        if score >= medium_score:
            return float(plot_cfg.get('medium_size', 120.0))
        return float(plot_cfg.get('small_size', 80.0))

    raw_events: list[MarkerEvent] = []
    for _, row in work.iterrows():
        ti = float(row['ti_norm'])
        move = float(row['mid_move_norm'])
        raw_ti = float(row['trade_imbalance_notional_window'])

        buy_score = (
            buy_trade_weight * _positive(ti)
            + ask_replenish_weight * _positive(row['ask_replenish_norm'])
            + best_ask_delta_weight * _positive(row['best_ask_delta_norm'])
            + depth_ask_delta_weight * _positive(row['depth_ask_delta_norm'])
            + buy_stall_weight * _negative_abs(move)
        )
        sell_score = (
            sell_trade_weight * _negative_abs(ti)
            + bid_replenish_weight * _positive(row['bid_replenish_norm'])
            + best_bid_delta_weight * _positive(row['best_bid_delta_norm'])
            + depth_bid_delta_weight * _positive(row['depth_bid_delta_norm'])
            + sell_stall_weight * _positive(move)
        )

        buy_trigger = raw_ti > min_ti_abs and buy_score >= min_score
        sell_trigger = raw_ti < -min_ti_abs and sell_score >= min_score

        if buy_trigger and (not sell_trigger or buy_score >= sell_score):
            raw_events.append(MarkerEvent(
                ts=row['ts'], side='buy_absorption', score=float(buy_score),
                price=float(row['high']) + base_y_offset + padding_offset,
                size=score_to_size(float(buy_score)),
                color=str(plot_cfg.get('buy_color', '#3b82f6')),
                symbol=str(plot_cfg.get('buy_marker', 'v')),
            ))
        elif sell_trigger:
            raw_events.append(MarkerEvent(
                ts=row['ts'], side='sell_absorption', score=float(sell_score),
                price=float(row['low']) - base_y_offset - padding_offset,
                size=score_to_size(float(sell_score)),
                color=str(plot_cfg.get('sell_color', '#ef4444')),
                symbol=str(plot_cfg.get('sell_marker', '^')),
            ))

    if not raw_events:
        return []

    keep_strongest = bool(plot_cfg.get('keep_strongest_per_bar', True))
    cooldown = int(plot_cfg.get('min_bars_between_same_side', 0))
    if not keep_strongest and cooldown <= 0:
        return raw_events

    ordered = sorted(raw_events, key=lambda x: x.ts)
    by_bar: list[MarkerEvent] = []
    if keep_strongest:
        tmp = {}
        for ev in ordered:
            key = (ev.ts, ev.side)
            prev = tmp.get(key)
            if prev is None or ev.score > prev.score:
                tmp[key] = ev
        by_bar = sorted(tmp.values(), key=lambda x: x.ts)
    else:
        by_bar = ordered

    if cooldown <= 0:
        return by_bar

    kept: list[MarkerEvent] = []
    last_idx_by_side = {'buy_absorption': None, 'sell_absorption': None}
    for idx, ev in enumerate(by_bar):
        last_idx = last_idx_by_side.get(ev.side)
        if last_idx is None or idx - last_idx > cooldown:
            kept.append(ev)
            last_idx_by_side[ev.side] = idx
    return kept


def build_overlay_png(markers: Iterable[MarkerEvent], time_min_dt_plot, time_max_dt_plot, price_min, price_max, cp, output_path: Path) -> Path:
    markers = list(markers)
    fig = plt.figure(figsize=(cp.FIG_WIDTH, cp.FIG_HEIGHT))
    fig.patch.set_alpha(0.0)

    gs_outer = gridspec.GridSpec(len(cp.GRIDSPEC_HEIGHT_RATIOS_MAIN), 1, height_ratios=cp.GRIDSPEC_HEIGHT_RATIOS_MAIN, hspace=cp.MAIN_SUBPLOT_HSPACE, left=0.06, right=0.94, bottom=0.12, top=0.92)
    current_grid_ratios = cp.GRIDSPEC_WIDTH_RATIOS_WITH_BAR.copy()
    gs_top_outer_ratios = [current_grid_ratios[0], current_grid_ratios[1] + current_grid_ratios[2]]
    gs_top_outer_wspace = 0.054
    gs_top_outer = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_outer[0], width_ratios=gs_top_outer_ratios, wspace=gs_top_outer_wspace)
    gs_top_inner = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_top_outer[1], width_ratios=[current_grid_ratios[1], current_grid_ratios[2]], wspace=0)

    ax_main_price = fig.add_subplot(gs_top_inner[0])
    ax_sub = fig.add_subplot(gs_outer[2], sharex=ax_main_price)
    ax_dummy1 = fig.add_subplot(gs_top_outer[0]); ax_dummy1.set_visible(False)
    ax_dummy2 = fig.add_subplot(gs_top_inner[1]); ax_dummy2.set_visible(False)
    ax_dummy3 = fig.add_subplot(gs_outer[1]); ax_dummy3.set_visible(False)

    ax_main_price.set_facecolor((0, 0, 0, 0))
    ax_sub.set_facecolor((0, 0, 0, 0))

    ax_main_price.set_ylim(price_min, price_max)
    ax_main_price.set_xlim(mdates.date2num(time_min_dt_plot), mdates.date2num(time_max_dt_plot))
    ax_main_price.yaxis.tick_right()
    ax_main_price.yaxis.set_label_position('right')
    ax_main_price.yaxis.set_major_locator(mticker.MultipleLocator(200))
    plt.setp(ax_main_price.get_xticklabels(), visible=False)

    ax_sub.set_xlim(mdates.date2num(time_min_dt_plot), mdates.date2num(time_max_dt_plot))
    ax_sub.tick_params(axis='x', colors=(0, 0, 0, 0), labelsize=0)
    ax_sub.tick_params(axis='y', colors=(0, 0, 0, 0), labelsize=0)
    ax_sub.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))

    for ev in markers:
        x = mdates.date2num(pd.Timestamp(ev.ts).to_pydatetime())
        ax_main_price.scatter([x], [ev.price], s=ev.size, marker=ev.symbol, color=ev.color, edgecolors='white', linewidths=0.7, alpha=0.95, zorder=10)

    for ax in [ax_main_price, ax_sub]:
        for spine in ax.spines.values():
            spine.set_alpha(0.0)
        ax.tick_params(axis='both', colors=(0, 0, 0, 0), labelcolor=(0, 0, 0, 0), length=0)
        ax.grid(False)

    fig.canvas.draw()
    try:
        fig.tight_layout(rect=[0.03, 0.04, 0.97, 0.95])
    except Exception:
        pass
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format='png', dpi=400, transparent=True, bbox_inches=None)
    plt.close(fig)
    return output_path


def composite_overlay(base_png: Path, overlay_png: Path, out_png: Path) -> Path:
    base = Image.open(base_png).convert('RGBA')
    overlay = Image.open(overlay_png).convert('RGBA')
    if overlay.size != base.size:
        overlay = overlay.resize(base.size)
    merged = Image.alpha_composite(base, overlay)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    merged.save(out_png)
    return out_png
