"""Bar-level absorption feature construction.

Responsibility boundary:
- Build numeric features used by the absorption classifier.
- Do not create markers.
- Do not draw charts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def robust_zscore(s: pd.Series, window: int = 96, min_periods: int = 20, eps: float = 1e-9) -> pd.Series:
    x = pd.to_numeric(s, errors='coerce')
    med = x.rolling(window=window, min_periods=min_periods).median()
    mad = (x - med).abs().rolling(window=window, min_periods=min_periods).median()
    z = 0.6745 * (x - med) / (mad + eps)
    return z.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _numeric(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if df is None or col not in df.columns:
        return pd.Series(default, index=df.index if isinstance(df, pd.DataFrame) else None, dtype=float)
    return pd.to_numeric(df[col], errors='coerce').fillna(default)


def _resample_trade_pressure(agg_df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if agg_df is None or agg_df.empty:
        return pd.DataFrame()
    work = agg_df.copy()
    work.index = pd.to_datetime(work.index, utc=True, errors='coerce')
    work = work[work.index.notna()].sort_index()
    if work.empty:
        return pd.DataFrame()

    if 'buy_quote' in work.columns and 'sell_quote' in work.columns:
        buy_quote = _numeric(work, 'buy_quote')
        sell_quote = _numeric(work, 'sell_quote')
    elif 'buy_notional_sum' in work.columns and 'sell_notional_sum' in work.columns:
        buy_quote = _numeric(work, 'buy_notional_sum')
        sell_quote = _numeric(work, 'sell_notional_sum')
    else:
        price = _numeric(work, 'vwap_price', np.nan).replace(0, np.nan)
        if price.isna().all():
            price = _numeric(work, 'close_price', np.nan).replace(0, np.nan)
        price = price.ffill().bfill().fillna(0.0)
        buy_quote = _numeric(work, 'buy_sum_quantity') * price
        sell_quote = _numeric(work, 'sell_sum_quantity') * price

    flow = pd.DataFrame({
        'buy_quote_flow': buy_quote,
        'sell_quote_flow': sell_quote,
    }, index=work.index)
    flow['net_delta_quote_flow'] = flow['buy_quote_flow'] - flow['sell_quote_flow']
    return flow.resample(interval).sum().dropna(how='all')


def build_absorption_features(bar_df: pd.DataFrame, agg_df: pd.DataFrame | None, cfg: dict) -> pd.DataFrame:
    """Return bar_df enriched with v1 absorption features.

    v1 model:
      absorption = strong side pressure + price progress failure + opposite refill hint - continuation
    """
    if bar_df is None or bar_df.empty:
        return pd.DataFrame()

    interval = cfg.get('bar_interval', '5min')
    out = bar_df.copy().sort_index()
    out.index = pd.to_datetime(out.index, utc=True, errors='coerce')
    out = out[out.index.notna()].sort_index()
    if out.empty:
        return pd.DataFrame()

    for col in ['open', 'high', 'low', 'close']:
        out[col] = pd.to_numeric(out.get(col), errors='coerce')
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    if out.empty:
        return pd.DataFrame()

    rng = (out['high'] - out['low']).abs().replace(0, np.nan)
    body = (out['close'] - out['open']).abs()
    out['close_pos'] = ((out['close'] - out['low']) / rng).replace([np.inf, -np.inf], np.nan).fillna(0.5).clip(0.0, 1.0)
    out['upper_wick_ratio'] = ((out['high'] - out[['open', 'close']].max(axis=1)) / rng).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    out['lower_wick_ratio'] = ((out[['open', 'close']].min(axis=1) - out['low']) / rng).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    out['body_efficiency'] = (body / rng).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(0.0, 1.0)
    out['range_abs'] = rng.fillna(0.0)

    pressure = _resample_trade_pressure(agg_df, interval)
    if not pressure.empty:
        out = out.join(pressure, how='left')
    for col in ['buy_quote_flow', 'sell_quote_flow', 'net_delta_quote_flow']:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors='coerce').fillna(0.0)

    z_window = int(cfg.get('absorption_v1_z_window', 96))
    z_min = int(cfg.get('absorption_v1_z_min_periods', 20))
    out['buy_pressure_z'] = robust_zscore(out['buy_quote_flow'], z_window, z_min)
    out['sell_pressure_z'] = robust_zscore(out['sell_quote_flow'], z_window, z_min)
    out['net_delta_quote_z'] = robust_zscore(out['net_delta_quote_flow'], z_window, z_min)

    out['ask_refill_z'] = robust_zscore(pd.to_numeric(out.get('net_ask_add_cancel_notional_window', 0.0), errors='coerce').fillna(0.0), z_window, z_min)
    out['bid_refill_z'] = robust_zscore(pd.to_numeric(out.get('net_bid_add_cancel_notional_window', 0.0), errors='coerce').fillna(0.0), z_window, z_min)

    buy_pressure_min = float(cfg.get('absorption_v1_pressure_z_min', 2.0))
    sell_pressure_min = buy_pressure_min
    out['buy_continuation'] = (out['buy_pressure_z'] >= buy_pressure_min) & (out['close_pos'] >= float(cfg.get('absorption_v1_buy_continuation_close_pos', 0.75)))
    out['sell_continuation'] = (out['sell_pressure_z'] >= sell_pressure_min) & (out['close_pos'] <= float(cfg.get('absorption_v1_sell_continuation_close_pos', 0.25)))

    return out


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


def _aggregate_feature_bars_base(feature_df: pd.DataFrame, ohlc_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
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


def aggregate_feature_bars(feature_df: pd.DataFrame, ohlc_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    out = _aggregate_feature_bars_base(feature_df, ohlc_df, cfg)
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
