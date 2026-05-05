"""Production-safe chart constants and Binance OHLCV fetcher for canonical.

This module intentionally contains no import-time diagnostics, file handlers, CLI,
or legacy renderer code. It is the small config/API surface required by the
role-based canonical engine.
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp
import pandas as pd

logger = logging.getLogger("orderflow.chart_config")

# Market / API
EXCHANGE_NAME = "Binance"
SYMBOL = "BTC/USDT"
FUTURES_SYMBOL_API = "BTCUSDT"
SPOT_API_BASE = "https://api.binance.com"
FUTURES_API_BASE = "https://fapi.binance.com"
OHLCV_API_ENDPOINT = "/api/v3/klines"
FUTURES_OHLCV_API_ENDPOINT = "/fapi/v1/klines"

# Rendering dimensions and typography. Keep these aligned with the canonical visual
# contract; do not change layout/aspect without an explicit product decision.
FIG_WIDTH = 15
FIG_HEIGHT = 13
BG_COLOR = "#151515"
TITLE_FONTSIZE = 14
AXIS_LABEL_FONTSIZE = 8
TICK_LABEL_FONTSIZE = 7
LEGEND_FONTSIZE = 8
COLORBAR_LABEL_FONTSIZE = 8
GRIDSPEC_WIDTH_RATIOS_WITH_BAR = [0.1, 4.0, 0.3]

# Time / candle settings
HOURS_TO_PLOT = 12
OB_TIME_RESOLUTION = "5min"
OHLCV_API_INTERVAL = "5m"
OHLCV_API_INTERVAL_MINUTES = 5
OI_FETCH_INTERVAL = "5m"
VOLUME_EMA_HOURS = 24

# Price / order-book heatmap settings
OB_Y_AXIS_RANGE = 8000
OB_PRICE_RESOLUTION = 20
OB_MIN_QTY_THRESHOLD_HEATMAP = {"Spot": 25.0, "Futures": 100.0}
OB_VMAX_PERCENTILE = 99
OB_LOG_VMIN = 0.1
OB_BID_CMAP_NAME = "Blues_r"
OB_ASK_CMAP_NAME = "OrRd_r"
OB_COLOR_NORM = "power"
OB_POWER_GAMMA = 0.5

# Trade markers
TRADE_PLOT_MIN_QTY_THRESHOLD = {"Spot": 15.0, "Futures": 60.0}
TRADE_BUY_COLOR = "#2E8B57"
TRADE_SELL_COLOR = "#DC143C"

# Candles
CANDLE_UP_BODY_COLOR = "#3bb2e5"
CANDLE_DOWN_BODY_COLOR = "#e9546c"
CANDLE_UP_WICK_COLOR = "#3bb2e5"
CANDLE_DOWN_WICK_COLOR = "#e9546c"
CANDLE_ALPHA = 1.0
CANDLE_EDGE_LW = 0.2
CANDLE_WICK_LW = 0.7

# VWAP overlays. engine refreshes this after interval overrides.
VWAP_PERIODS_CONFIG = {
    "12H": (int(12 * 60 / OHLCV_API_INTERVAL_MINUTES), "#FFFFFF"),
    "24H": (int(24 * 60 / OHLCV_API_INTERVAL_MINUTES), "#FFD700"),
    "7D": (int(7 * 24 * 60 / OHLCV_API_INTERVAL_MINUTES), "#FFA500"),
    "14D": (int(14 * 24 * 60 / OHLCV_API_INTERVAL_MINUTES), "#87CEEB"),
    "30D": (int(30 * 24 * 60 / OHLCV_API_INTERVAL_MINUTES), "#FF00FF"),
}
VWAP_MARKER_SIZE = 2
VWAP_MARKER_ALPHA = 0.9

# Current order-book side bar
OB_BAR_AGGREGATION_PRICE = 20
OB_BAR_MAX_WIDTH_RATIO = 0.15
ORDER_BOOK_QTY_FONTSIZE = 5


async def fetch_binance_ohlcv_from_api(
    session: aiohttp.ClientSession,
    market_type: str,
    symbol: str,
    interval: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
) -> pd.DataFrame:
    """Fetch Binance OHLCV klines and return sanitized OHLCV columns.

    The function is deliberately quiet on success and returns an empty DataFrame
    on API failures so the caller can decide whether to fail or use another
    fallback. It does not create files or configure global logging.
    """
    api_symbol = symbol.replace("/", "")
    base_url = SPOT_API_BASE if market_type == "Spot" else FUTURES_API_BASE
    endpoint = OHLCV_API_ENDPOINT if market_type == "Spot" else FUTURES_OHLCV_API_ENDPOINT
    url = f"{base_url}{endpoint}"

    all_klines: list[list] = []
    current_start_ms = int(pd.Timestamp(start_dt).timestamp() * 1000)
    end_ms = int(pd.Timestamp(end_dt).timestamp() * 1000)
    step_ms = OHLCV_API_INTERVAL_MINUTES * 60 * 1000

    while current_start_ms < end_ms:
        params = {"symbol": api_symbol, "interval": interval, "startTime": current_start_ms, "limit": 1000}
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30.0, connect=15.0)) as response:
                response.raise_for_status()
                data = await response.json()
            await asyncio.sleep(0.1)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Binance OHLCV fetch failed symbol=%s interval=%s error=%s", api_symbol, interval, exc)
            return pd.DataFrame()
        except Exception as exc:
            logger.exception("Unexpected Binance OHLCV fetch error symbol=%s interval=%s: %s", api_symbol, interval, exc)
            return pd.DataFrame()

        if not data:
            break
        all_klines.extend(data)
        last_open_ms = int(data[-1][0])
        next_start_ms = last_open_ms + step_ms
        if next_start_ms <= current_start_ms:
            break
        current_start_ms = next_start_ms
        if len(data) < int(params["limit"]):
            break

    if not all_klines:
        return pd.DataFrame()

    cols = [
        "Open time", "Open", "High", "Low", "Close", "Volume", "Close time",
        "Quote asset volume", "Number of trades", "Taker buy base volume",
        "Taker buy quote volume", "Ignore",
    ]
    df = pd.DataFrame(all_klines, columns=cols)
    df.drop_duplicates(subset=["Open time"], keep="last", inplace=True)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["Open", "High", "Low", "Close", "Volume"], inplace=True)
    if df.empty:
        return pd.DataFrame()

    df["timestamp"] = pd.to_datetime(df["Open time"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
    final_df = df[(df.index >= start_dt) & (df.index <= end_dt)]
    return final_df[["open", "high", "low", "close", "volume"]].sort_index()
