"""Bar-level absorption classifier v1.

v1 definition:
- Absorption candidate = strong side market pressure + failed price progress.
- Refill-supported absorption = candidate + opposite-side book refill hint.
- Continuation bars are explicitly excluded.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def classify_absorption_v1(feature_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    if feature_df is None or feature_df.empty:
        return pd.DataFrame()
    out = feature_df.copy().sort_index()

    pressure_min = float(cfg.get('absorption_v1_pressure_z_min', 2.0))
    refill_min = float(cfg.get('absorption_v1_refill_z_min', 1.5))
    buy_close_max = float(cfg.get('absorption_v1_buy_close_pos_max', 0.50))
    sell_close_min = float(cfg.get('absorption_v1_sell_close_pos_min', 0.50))
    wick_min = float(cfg.get('absorption_v1_wick_ratio_min', 0.30))

    for col in [
        'buy_pressure_z', 'sell_pressure_z', 'ask_refill_z', 'bid_refill_z',
        'close_pos', 'upper_wick_ratio', 'lower_wick_ratio',
        'buy_continuation', 'sell_continuation',
    ]:
        if col not in out.columns:
            out[col] = False if col.endswith('continuation') else 0.0

    buy_progress_failed = (out['close_pos'] <= buy_close_max) | (out['upper_wick_ratio'] >= wick_min)
    sell_progress_failed = (out['close_pos'] >= sell_close_min) | (out['lower_wick_ratio'] >= wick_min)

    out['buy_absorption_candidate'] = (
        (out['buy_pressure_z'] >= pressure_min)
        & buy_progress_failed
        & (~out['buy_continuation'].astype(bool))
    )
    out['sell_absorption_candidate'] = (
        (out['sell_pressure_z'] >= pressure_min)
        & sell_progress_failed
        & (~out['sell_continuation'].astype(bool))
    )

    out['buy_refill_supported_absorption'] = out['buy_absorption_candidate'] & (out['ask_refill_z'] >= refill_min)
    out['sell_refill_supported_absorption'] = out['sell_absorption_candidate'] & (out['bid_refill_z'] >= refill_min)

    out['buy_absorption_score'] = (
        out['buy_pressure_z'].clip(lower=0)
        + (1.0 - out['close_pos']).clip(lower=0, upper=1.0)
        + out['upper_wick_ratio'].clip(lower=0)
        + out['ask_refill_z'].clip(lower=0) * 0.6
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    out['sell_absorption_score'] = (
        out['sell_pressure_z'].clip(lower=0)
        + out['close_pos'].clip(lower=0, upper=1.0)
        + out['lower_wick_ratio'].clip(lower=0)
        + out['bid_refill_z'].clip(lower=0) * 0.6
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    def _label(row):
        if bool(row.get('buy_refill_supported_absorption')) and bool(row.get('sell_refill_supported_absorption')):
            return 'buy_absorption' if row.get('buy_absorption_score', 0.0) >= row.get('sell_absorption_score', 0.0) else 'sell_absorption'
        if bool(row.get('buy_refill_supported_absorption')):
            return 'buy_absorption'
        if bool(row.get('sell_refill_supported_absorption')):
            return 'sell_absorption'
        if bool(row.get('buy_absorption_candidate')):
            return 'buy_absorption_candidate'
        if bool(row.get('sell_absorption_candidate')):
            return 'sell_absorption_candidate'
        if bool(row.get('buy_continuation')):
            return 'buy_continuation'
        if bool(row.get('sell_continuation')):
            return 'sell_continuation'
        return 'none'

    out['absorption_v1_label'] = out.apply(_label, axis=1)
    out['display_absorption_marker'] = out['absorption_v1_label'].isin(['buy_absorption', 'sell_absorption'])
    return out
