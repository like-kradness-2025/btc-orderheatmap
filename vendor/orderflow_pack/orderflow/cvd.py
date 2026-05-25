"""CVD feature construction for canonical orderflow data.

Responsibility boundary:
- This module only derives CVD-related columns from an already aggregated trade
  dataframe.
- It does not read files, fetch exchange data, or draw charts.
- Plotting code should consume the columns produced here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CVD_ZSCORE_WINDOW = 120
CVD_ZSCORE_MIN_PERIODS = 30


def robust_zscore(
    s: pd.Series,
    window: int = CVD_ZSCORE_WINDOW,
    min_periods: int = CVD_ZSCORE_MIN_PERIODS,
    eps: float = 1e-9,
) -> pd.Series:
    """Robust rolling z-score using rolling median and MAD."""
    x = pd.to_numeric(s, errors="coerce")
    med = x.rolling(window=window, min_periods=min_periods).median()
    mad = (x - med).abs().rolling(window=window, min_periods=min_periods).median()
    return 0.6745 * (x - med) / (mad + eps)


def add_cvd_columns(agg_df: pd.DataFrame) -> pd.DataFrame:
    """Return aggregated trades with lightweight CVD columns added.

    Required source columns:
      - buy_sum_quantity
      - sell_sum_quantity
      - vwap_price or close_price

    Optional source columns:
      - buy_notional_sum
      - sell_notional_sum

    The current receiver aggregation already normalizes trade side into buy/sell.
    Therefore this layer intentionally does not infer taker side again.
    """
    if agg_df is None:
        return pd.DataFrame()
    if agg_df.empty:
        return agg_df

    df = agg_df.copy().sort_index()

    buy_base = pd.to_numeric(df.get("buy_sum_quantity", 0.0), errors="coerce").fillna(0.0)
    sell_base = pd.to_numeric(df.get("sell_sum_quantity", 0.0), errors="coerce").fillna(0.0)

    df["delta_base"] = buy_base - sell_base
    df["cvd_base"] = df["delta_base"].cumsum()

    if "buy_notional_sum" in df.columns and "sell_notional_sum" in df.columns:
        buy_quote = pd.to_numeric(df["buy_notional_sum"], errors="coerce").fillna(0.0)
        sell_quote = pd.to_numeric(df["sell_notional_sum"], errors="coerce").fillna(0.0)
    else:
        price_source = df.get("vwap_price", df.get("close_price", np.nan))
        price = pd.to_numeric(price_source, errors="coerce").ffill().bfill()
        buy_quote = buy_base * price
        sell_quote = sell_base * price

    df["buy_quote"] = buy_quote.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["sell_quote"] = sell_quote.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["delta_quote"] = df["buy_quote"] - df["sell_quote"]
    df["cvd_quote"] = df["delta_quote"].cumsum()

    df["delta_base_z"] = robust_zscore(df["delta_base"])
    df["delta_quote_z"] = robust_zscore(df["delta_quote"])
    df["abs_delta_quote_z"] = robust_zscore(df["delta_quote"].abs())

    for n in (1, 3, 6, 12, 24):
        df[f"cvd_change_{n}"] = df["cvd_quote"].diff(n)

    return df
