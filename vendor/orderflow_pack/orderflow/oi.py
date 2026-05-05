"""Open-interest loading, aggregation, and OI subplot helpers for orderheatmap canonical."""
from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from runtime import data

def _safe_float(v):
    try:
        x = float(v)
        if np.isfinite(x):
            return x
    except Exception:
        return None
    return None

def load_oi_rows(oi_path: Path, start_ts: pd.Timestamp | None) -> pd.DataFrame:
    rows = data.read_jsonl_recent_until(oi_path, start_ts, chunk_bytes=8 * 1024 * 1024, max_bytes=128 * 1024 * 1024)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if 'ts' not in df.columns:
        return pd.DataFrame()
    df['ts'] = pd.to_datetime(df['ts'], utc=True, errors='coerce')
    df = df.dropna(subset=['ts']).sort_values('ts').reset_index(drop=True)
    if start_ts is not None:
        df = df[df['ts'] >= start_ts].reset_index(drop=True)
    if df.empty:
        return pd.DataFrame()

    candidate_cols = [
        'open_interest', 'openInterest', 'oi', 'sumOpenInterest', 'open_interest_value',
        'openInterestValue', 'oi_value', 'value'
    ]
    oi_series = None
    for col in candidate_cols:
        if col in df.columns:
            s = pd.to_numeric(df[col], errors='coerce')
            if s.notna().any():
                oi_series = s
                break
    if oi_series is None:
        for col in df.columns:
            if col == 'ts':
                continue
            if 'oi' in str(col).lower() or 'interest' in str(col).lower():
                s = pd.to_numeric(df[col], errors='coerce')
                if s.notna().any():
                    oi_series = s
                    break
    if oi_series is None:
        return pd.DataFrame()
    out = pd.DataFrame({'ts': df['ts'], 'oi': oi_series}).dropna(subset=['oi'])
    out = out[out['oi'].astype(float).map(np.isfinite)]
    return out.reset_index(drop=True)

def build_oi_ohlc(oi_df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if oi_df.empty:
        return pd.DataFrame()
    work = oi_df.copy()
    work['ts'] = pd.to_datetime(work['ts'], utc=True, errors='coerce')
    work = work.dropna(subset=['ts']).set_index('ts').sort_index()
    if work.empty:
        return pd.DataFrame()
    ohlc = work['oi'].resample(interval).ohlc().dropna(how='all')
    return ohlc

def draw_oi_candle_layer(ax_oi, oi_df: pd.DataFrame, cp_mod):
    if oi_df.empty:
        ax_oi.text(0.5, 0.5, 'OI data unavailable', transform=ax_oi.transAxes, ha='center', va='center', color='white', alpha=0.7)
        return
    width_days = (cp_mod.OHLCV_API_INTERVAL_MINUTES * 60 / (24 * 60 * 60)) * 0.7
    up = oi_df[oi_df['close'] >= oi_df['open']]
    down = oi_df[oi_df['close'] < oi_df['open']]
    up_idx_num = mdates.date2num(up.index.to_pydatetime())
    down_idx_num = mdates.date2num(down.index.to_pydatetime())
    ax_oi.bar(up_idx_num, up['close'] - up['open'], width_days, bottom=up['open'], color=cp_mod.CANDLE_UP_BODY_COLOR, alpha=0.85, zorder=2.1, edgecolor=cp_mod.CANDLE_UP_BODY_COLOR, linewidth=cp_mod.CANDLE_EDGE_LW)
    ax_oi.bar(down_idx_num, down['close'] - down['open'], width_days, bottom=down['open'], color=cp_mod.CANDLE_DOWN_BODY_COLOR, alpha=0.85, zorder=2.1, edgecolor=cp_mod.CANDLE_DOWN_BODY_COLOR, linewidth=cp_mod.CANDLE_EDGE_LW)
    ax_oi.vlines(up_idx_num, up['low'], up['high'], color=cp_mod.CANDLE_UP_WICK_COLOR, linewidth=cp_mod.CANDLE_WICK_LW, alpha=0.9, zorder=2.0)
    ax_oi.vlines(down_idx_num, down['low'], down['high'], color=cp_mod.CANDLE_DOWN_WICK_COLOR, linewidth=cp_mod.CANDLE_WICK_LW, alpha=0.9, zorder=2.0)


def compute_price_atr_gate(price_df: pd.DataFrame, period: int = 14):
    if price_df.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    work = price_df[['high', 'low', 'close']].copy()
    for col in ['high', 'low', 'close']:
        work[col] = pd.to_numeric(work[col], errors='coerce')
    work.index = pd.to_datetime(work.index, utc=True, errors='coerce')
    work = work.dropna(subset=['high', 'low', 'close']).sort_index()
    if work.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    prev_close = work['close'].shift(1)
    tr = pd.concat([
        (work['high'] - work['low']).abs(),
        (work['high'] - prev_close).abs(),
        (work['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    tr_pct = tr / prev_close.abs().replace(0, np.nan)
    atr_pct = tr_pct.rolling(period, min_periods=max(3, period // 2)).mean()
    atr_pct = atr_pct.combine_first(tr_pct.expanding(min_periods=3).mean())
    return tr_pct, atr_pct

def draw_oi_delta_background(ax_oi, oi_df: pd.DataFrame, cp_mod, price_df: pd.DataFrame):
    if oi_df.empty or price_df.empty:
        return 0
    # Intentional: these bands are aligned to price direction, not OI direction.
    # v3.27 keeps all qualifying bands, but fades weak moves and boosts strong ones.
    slot_days = (cp_mod.OHLCV_API_INTERVAL_MINUTES * 60) / (24 * 60 * 60)
    price_by_ts = price_df[['open', 'high', 'low', 'close']].copy()
    for col in ['open', 'high', 'low', 'close']:
        price_by_ts[col] = pd.to_numeric(price_by_ts[col], errors='coerce')
    price_by_ts.index = pd.to_datetime(price_by_ts.index, utc=True, errors='coerce')
    price_by_ts = price_by_ts.dropna(subset=['open', 'high', 'low', 'close']).sort_index()
    if price_by_ts.empty:
        return 0

    tr_pct, atr_pct = compute_price_atr_gate(price_by_ts)
    if tr_pct.empty or atr_pct.empty:
        return 0

    atr_mult = 1.15
    alpha_min = 0.08
    alpha_max = 0.28
    strength_cap = 2.80
    blue = '#60a5fa'
    red = '#fca5a5'

    bands_drawn = 0
    for ts in price_by_ts.index.intersection(oi_df.index):
        try:
            bar = price_by_ts.loc[ts]
            delta = float(bar['close']) - float(bar['open'])
            bar_tr_pct = float(tr_pct.loc[ts]) if ts in tr_pct.index else np.nan
            bar_atr_pct = float(atr_pct.loc[ts]) if ts in atr_pct.index else np.nan
        except Exception:
            continue
        if not np.isfinite(delta) or abs(delta) <= 1e-12:
            continue
        if not np.isfinite(bar_tr_pct) or not np.isfinite(bar_atr_pct) or bar_atr_pct <= 0:
            continue
        strength = bar_tr_pct / bar_atr_pct
        if strength < atr_mult:
            continue
        direction = 1 if delta > 0 else -1
        center = mdates.date2num(pd.Timestamp(ts).to_pydatetime())
        left = center - slot_days / 2.0
        right = center + slot_days / 2.0
        color = blue if direction > 0 else red
        strength_norm = (strength - atr_mult) / max(strength_cap - atr_mult, 1e-9)
        strength_norm = float(np.clip(strength_norm, 0.0, 1.0))
        alpha = alpha_min + (alpha_max - alpha_min) * strength_norm
        ax_oi.axvspan(left, right, color=color, alpha=alpha, ec='none', zorder=0.1)
        bands_drawn += 1

    return bands_drawn
