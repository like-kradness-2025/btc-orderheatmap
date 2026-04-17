# -*- coding: utf-8 -*-
import sys # 環境診断用に追加
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.colors as mcolors
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
import numpy as np
from ta.volatility import AverageTrueRange
import time
import datetime
from typing import List, Tuple, Dict, Optional, Any
import os
import requests # For Discord sending
import traceback
import io
import gc
from matplotlib.ticker import FuncFormatter
import pytz
import aiohttp # For Binance OI fetching
import asyncio
import warnings
import logging
from matplotlib.lines import Line2D

# --- 環境診断用コード ---
print(f"--- 環境診断 ---")
print(f"Python実行ファイル: {sys.executable}")
print(f"Pythonモジュール検索パス (sys.path):")
for p in sys.path:
    print(f"  {p}")
print(f"--- 環境診断終了 ---")
# --- 環境診断用コードここまで ---

# python-binanceを使用しないため、BINANCE_AVAILABLEは常にTrueと仮定
BINANCE_AVAILABLE = True

# --- Font setting for Japanese (commented out as per request to remove Japanese) ---
# try:
#     plt.rcParams['font.family'] = 'IPAexGothic'
# except Exception as e:
#     print(f"Failed to set Japanese font: {e}. Japanese characters in plots may not display correctly.")
# --- End of font setting modification ---

# --- Fast JSON library orjson trial ---
try:
    import orjson
    JSON_LIB = orjson
    USE_ORJSON = True
except ImportError:
    import json
    JSON_LIB = json
    USE_ORJSON = False


# === Combined VWAP Spread + OI + Volume + ATR Signal ===
def calculate_combined_signal(df_ohlcv, df_oi, spread_short, spread_long, atr_window=14, atr_multiplier=0.5):
    """
    Returns pd.Series with 1 (long), -1 (short), 0 (neutral)
    """
    df = df_ohlcv[['high', 'low', 'close', 'volume']].join(df_oi[['open_interest']], how='inner').sort_index()
    atr = AverageTrueRange(df['high'], df['low'], df['close'], window=atr_window).average_true_range()
    oi_change = df['open_interest'].pct_change()
    vol_change = df['volume'].pct_change()
    thr = atr * atr_multiplier
    long_cond = (spread_short > thr) & (spread_long > thr) & (oi_change > 0) & (vol_change > 0)
    short_cond = (spread_short < -thr) & (spread_long < -thr) & (oi_change > 0) & (vol_change > 0)
    signal = pd.Series(0, index=spread_short.index)
    signal.loc[long_cond] = 1
    signal.loc[short_cond] = -1
    return signal

# --- Logging setup ---
logger = logging.getLogger("ChartProt")
logger.setLevel(logging.INFO)
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s')

if not logger.handlers:
    log_file = 'chartProt.log'
    file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='a')
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)
# --- End of logging setup ---


# --- Settings ---
DB_PATH = "market_data_history.db" # For order book, aggregated trade history
HISTORY_DB_PATH = "ohlcv_oi_history.db" # For OI data only now

BOOK_TABLE_NAME = "order_book_history"
AGGREGATED_TRADE_TABLE_NAME = "aggregated_trade_history"
# OHLCV_TABLE_NAME = "ohlcv_history" # ★ OHLCVテーブルは使用しない
OPEN_INTEREST_TABLE_NAME = "open_interest_history"

EXCHANGE_NAME = "Binance"
SYMBOL = "BTC/USDT"
FUTURES_SYMBOL_API = "BTCUSDT"
SPOT_SYMBOL_API = "BTCUSDT"
SPOT_SYMBOL_LOWER = SYMBOL.replace('/', '').lower()
FUTURES_SYMBOL_LOWER = SYMBOL.replace('/', '').lower()

HOURS_TO_PLOT = 24 # Plot duration (hours)
# HOURS_TO_SAVE_HISTORY = 32 * 24 # ★ OHLCV保存期間は使用しない
DAYS_TO_FETCH_OHLCV_API = 32 # ★ APIからOHLCVデータを取得する日数
HOURS_TO_SAVE_OI_HISTORY = 32 * 24 # OIデータの保存期間

OB_Y_AXIS_RANGE = 8000
OB_PRICE_RESOLUTION = 20
OB_BAR_AGGREGATION_PRICE = 20

TRADE_PLOT_MIN_QTY_THRESHOLD = {'Spot': 15.0, 'Futures': 60.0}
TRADE_MARKER_SIZE_MIN = 20
TRADE_MARKER_SIZE_MAX = 2000
TRADE_MARKER_SIZE_POWER = 0.6
TRADE_BUY_COLOR = '#2E8B57'
TRADE_SELL_COLOR = '#DC143C'

# !!! 注意: 以下のWebhook URLはご自身の有効なものに置き換えてください !!!
DISCORD_CHART_WEBHOOK_URLS = {
    'Spot': "YOUR_SPOT_WEBHOOK_URL_HERE", # 例: ""
    'Futures': "YOUR_FUTURES_WEBHOOK_URL_HERE" # 例: 
}
DISCORD_LOG_WEBHOOK_URL = "YOUR_LOG_WEBHOOK_URL_HERE" 

FIG_WIDTH = 15
FIG_HEIGHT = 13
GRIDSPEC_WIDTH_RATIOS_WITH_BAR = [0.1, 4.0, 0.3]
GRIDSPEC_HEIGHT_RATIOS_MAIN = [6.5, 1.0, 1.0]
MAIN_SUBPLOT_HSPACE = 0.04
BG_COLOR = '#151515'

OB_TIME_RESOLUTION = '5min'
OB_MIN_QTY_THRESHOLD_HEATMAP = {'Spot': 25.0, 'Futures': 100.0}
OB_VMAX_PERCENTILE = 99
OB_ASK_CMAP_NAME = 'OrRd_r'
OB_BID_CMAP_NAME = 'Blues_r'
OB_COLOR_NORM = 'power'
OB_POWER_GAMMA = 0.5
OB_LOG_VMIN = 0.1

OB_BAR_MAX_WIDTH_RATIO = 0.15

CANDLE_UP_BODY_COLOR = '#3bb2e5'
CANDLE_UP_WICK_COLOR = '#3bb2e5'
CANDLE_DOWN_BODY_COLOR = '#e9546c'
CANDLE_DOWN_WICK_COLOR = '#e9546c'
CANDLE_EDGE_LW = 0.2
CANDLE_WICK_LW = 0.7
CANDLE_ALPHA = 1.0

# VWAP Settings
OHLCV_API_INTERVAL_MINUTES = 5 # Assuming 5 minute interval for OHLCV
VWAP_PERIODS_CONFIG = { # Label: (Periods, Color)
    "12H": (int(12 * 60 / OHLCV_API_INTERVAL_MINUTES), '#FFFFFF'),  # White
    "24H": (int(24 * 60 / OHLCV_API_INTERVAL_MINUTES), '#FFD700'),  # Gold
    "7D":  (int(7 * 24 * 60 / OHLCV_API_INTERVAL_MINUTES), '#FFA500'),  # Orange
    "14D": (int(14 * 24 * 60 / OHLCV_API_INTERVAL_MINUTES), '#87CEEB'), # SkyBlue
    "30D": (int(30 * 24 * 60 / OHLCV_API_INTERVAL_MINUTES), '#FF00FF')   # Magenta
}
VWAP_MARKER_SIZE = 2
VWAP_MARKER_ALPHA = 0.9

VOLUME_COLOR = 'cyan'
VOLUME_EMA_COLOR = 'lightblue'
VOLUME_EMA_LINEWIDTH = 1.0
OPEN_INTEREST_COLOR = 'lightcoral'
OPEN_INTEREST_LINEWIDTH = 1.5

TITLE_FONTSIZE = 14
AXIS_LABEL_FONTSIZE = 8
TICK_LABEL_FONTSIZE = 7
LEGEND_FONTSIZE = 8
ORDER_BOOK_QTY_FONTSIZE = 5
COLORBAR_LABEL_FONTSIZE = 8

VOLUME_EMA_HOURS = 24
TRADE_VWAP_PERIODS = {
    'Spot': {'short': '60min', 'long': '12h'},
    'Futures': {'short': '60min', 'long': '12h'}
} # 短期と長期の期間を現物・先物それぞれに設定

SPOT_API_BASE = "https://api.binance.com"
FUTURES_API_BASE = "https://fapi.binance.com"
OHLCV_API_ENDPOINT = "/api/v3/klines"
FUTURES_OHLCV_API_ENDPOINT = "/fapi/v1/klines"
OI_API_ENDPOINT = "/futures/data/openInterestHist"

OI_FETCH_LIMIT = 500
OI_FETCH_INTERVAL = "5m"
OHLCV_API_INTERVAL = "5m"

JST = pytz.timezone('Asia/Tokyo')
EXECUTION_INTERVAL_SECONDS = 300

# === Discord notification function ===
def send_discord_notification(message: str, webhook_url: Optional[str], level: str = "info", image_buffer: Optional[io.BytesIO] = None, filename: str = "chart.png"):
    if not webhook_url or webhook_url.startswith("YOUR_") or not webhook_url.startswith("https://discord.com/api/webhooks/"):
        logger.warning(f"Discord Webhook URL ({webhook_url=}) is invalid or not set. Skipping notification.")
        return
    level_emoji_map = {"info": ":information_source:", "warning": ":warning:", "error": ":x:", "critical": ":boom:", "success": ":white_check_mark:"}
    emoji = level_emoji_map.get(level.lower(), "")
    payload = {"content": f"{emoji} {message}"}
    files = None
    if image_buffer:
        try:
            image_buffer.seek(0)
            files = {'file': (filename, image_buffer, 'image/png')}
        except Exception as e:
            logger.error(f"Error preparing file for Discord sending: {e}")
            payload["content"] += f"\n(Image attachment error: {e})"
            files = None
    try:
        response = requests.post(webhook_url, data=payload, files=files, timeout=(15, 60))
        response.raise_for_status()
    except requests.exceptions.Timeout: logger.error("Timeout during Discord notification.")
    except requests.exceptions.HTTPError as e: logger.error(f"Discord notification HTTP error: {e.response.status_code} - {e.response.text[:200]}")
    except requests.exceptions.RequestException as e: logger.error(f"Discord notification error: {e}")
    except Exception as e: logger.error(f"Unexpected error during Discord notification: {e}", exc_info=True)

def y_fmt(y, pos):
    if abs(y) >= 1e9: return f'{y/1e9:.1f}G'
    if abs(y) >= 1e6: return f'{y/1e6:.1f}M'
    if abs(y) >= 1e3: return f'{y/1e3:.1f}k'
    if abs(y) >= 1: return f'{y:.0f}'
    if abs(y) > 1e-9 : return f'{y:.2f}'
    return '0'
y_formatter = FuncFormatter(y_fmt)

def price_fmt(y, pos): return f'{y:.0f}'
price_formatter = FuncFormatter(price_fmt)

def initialize_db(db_path: str, history_db_path: str):
    conn_main = None
    try:
        conn_main = sqlite3.connect(db_path)
        cursor = conn_main.cursor()
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {BOOK_TABLE_NAME} (timestamp_unix REAL NOT NULL, market TEXT NOT NULL, symbol TEXT NOT NULL, mid_price REAL, bids_json TEXT, asks_json TEXT, PRIMARY KEY (timestamp_unix, market, symbol))")
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {AGGREGATED_TRADE_TABLE_NAME} (timestamp_unix INTEGER NOT NULL, market TEXT NOT NULL, symbol TEXT NOT NULL, open_price REAL, high_price REAL, low_price REAL, close_price REAL, total_quantity REAL, buy_quantity REAL, sell_quantity REAL, number_of_trades INTEGER, PRIMARY KEY (timestamp_unix, market, symbol))")
        conn_main.commit(); logger.info(f"DB '{db_path}' tables initialized or verified.")
    except sqlite3.Error as e: logger.error(f"Main DB initialization error: {e}", exc_info=True); send_discord_notification(f"Error during main DB initialization: {e}", DISCORD_LOG_WEBHOOK_URL, level="error")
    finally:
        if conn_main: conn_main.close()
    conn_history = None
    try:
        conn_history = sqlite3.connect(history_db_path)
        cursor = conn_history.cursor()
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {OPEN_INTEREST_TABLE_NAME} (timestamp_unix INTEGER NOT NULL, market TEXT NOT NULL, symbol TEXT NOT NULL, period TEXT NOT NULL, open_interest REAL, PRIMARY KEY (timestamp_unix, market, symbol, period))")
        conn_history.commit(); logger.info(f"History DB '{history_db_path}' tables for OI initialized or verified.")
    except sqlite3.Error as e: logger.error(f"History DB initialization error: {e}", exc_info=True); send_discord_notification(f"Error during history DB initialization: {e}", DISCORD_LOG_WEBHOOK_URL, level="error")
    finally:
        if conn_history: conn_history.close()

def save_open_interest_data_to_db(df: pd.DataFrame, db_path: str, table_name: str, market: str, symbol: str, period: str, retention_hours: int):
    if df.empty: return
    conn = None
    try:
        conn = sqlite3.connect(db_path); cursor = conn.cursor(); data_to_insert = []
        for index, row in df.iterrows(): data_to_insert.append((int(index.timestamp()), market, symbol, period, row['open_interest']))
        cursor.executemany(f"INSERT OR REPLACE INTO {table_name} (timestamp_unix, market, symbol, period, open_interest) VALUES (?, ?, ?, ?, ?)", data_to_insert)
        cutoff_timestamp = time.time() - (retention_hours * 3600)
        cursor.execute(f"DELETE FROM {table_name} WHERE market = ? AND symbol = ? AND period = ? AND timestamp_unix < ?", (market, symbol, period, cutoff_timestamp))
        conn.commit(); logger.info(f"Saved/updated Open Interest data to DB and deleted old data ({len(data_to_insert)} entries, {market}, {symbol}, {period})")
    except sqlite3.Error as e: logger.error(f"Open Interest data DB save error: {e}", exc_info=True)
    finally:
        if conn: conn.close()

def load_open_interest_data_from_db(db_path: str, table_name: str, market: str, symbol_lower: str, period: str, hours: Optional[int] = None) -> pd.DataFrame:
    required_cols = ['timestamp_unix', 'open_interest']
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
        params: List[Any] = [market, symbol_lower, period]
        query = f"SELECT {', '.join(required_cols)} FROM {table_name} WHERE market = ? AND symbol = ? AND period = ?"
        if hours is not None and hours > 0:
            query += " AND timestamp_unix >= ?"
            params.append(int(time.time() - (hours * 3600)))
        query += " ORDER BY timestamp_unix ASC"
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        if df.empty: logger.warning(f"{market} {symbol_lower} ({period}) - No OI data for the specified period. Check DB. (Hours: {hours})"); return pd.DataFrame()
        df['timestamp'] = pd.to_datetime(df['timestamp_unix'], unit='s', utc=True, errors='coerce'); df.dropna(subset=['timestamp'], inplace=True); df.set_index('timestamp', inplace=True)
        if 'open_interest' in df.columns: df['open_interest'] = pd.to_numeric(df['open_interest'], errors='coerce')
        else: df['open_interest'] = np.nan
        df.dropna(subset=['open_interest'], inplace=True); return df[['open_interest']]
    except Exception as e: logger.error(f"DB/Open Interest loading error ({market} {symbol_lower} {period}): {e}", exc_info=True); return pd.DataFrame()

def load_book_data_with_stats(db_path: str, table_name:str, market: str, hours: Optional[int] = None) -> pd.DataFrame:
    required_cols = ['timestamp_unix', 'mid_price', 'bids_json', 'asks_json']
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0); current_db_symbol = FUTURES_SYMBOL_LOWER if market == "Futures" else SPOT_SYMBOL_LOWER; params: List[Any] = [market, current_db_symbol]
        query = f"SELECT {', '.join(required_cols)} FROM {table_name} WHERE market = ? AND symbol = ?"
        if hours is not None and hours > 0: query += " AND timestamp_unix >= ?"; params.append(time.time() - (hours * 3600))
        query += " ORDER BY timestamp_unix ASC"; df = pd.read_sql_query(query, conn, params=params); conn.close()
        if df.empty: logger.warning(f"{market} ({current_db_symbol}) - No order book data for the specified period. Check DB. (Hours: {hours})"); return pd.DataFrame()
        df['timestamp'] = pd.to_datetime(df['timestamp_unix'], unit='s', utc=True, errors='coerce'); df.dropna(subset=['timestamp'], inplace=True); df.set_index('timestamp', inplace=True)
        for col in ['bids_json', 'asks_json']:
            parsed_col = []
            for json_data in df[col]:
                item_data = {}
                if isinstance(json_data, str) and json_data.strip():
                    try: item_data = {float(k): float(v) for k, v in JSON_LIB.loads(json_data).items()}
                    except Exception: pass
                elif isinstance(json_data, dict):
                    try: item_data = {float(k): float(v) for k, v in json_data.items()}
                    except Exception: pass
                parsed_col.append(item_data)
            df[col] = parsed_col
        numeric_stat_cols = ['mid_price']
        for col in numeric_stat_cols:
            if col not in df.columns: df[col] = 0.0
            else: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return df
    except Exception as e: logger.error(f"DB/Order book loading error ({market}): {e}", exc_info=True); return pd.DataFrame()

def load_aggregated_trade_data(db_path: str, table_name: str, market: str, symbol_lower: str, hours: Optional[int] = None) -> pd.DataFrame:
    required_cols = ['timestamp_unix', 'open_price', 'high_price', 'low_price', 'close_price', 'total_quantity', 'buy_quantity', 'sell_quantity', 'number_of_trades']
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0); params: List[Any] = [market, symbol_lower]
        query = f"SELECT {', '.join(required_cols)} FROM {table_name} WHERE market = ? AND symbol = ?"
        if hours is not None and hours > 0: query += " AND timestamp_unix >= ?"; params.append(int(time.time() - (hours * 3600)))
        query += " ORDER BY timestamp_unix ASC"; df = pd.read_sql_query(query, conn, params=params); conn.close()
        if df.empty: logger.warning(f"{market} {symbol_lower} - No aggregated trade history data. Check DB. (Hours: {hours})"); return pd.DataFrame()
        df['timestamp'] = pd.to_datetime(df['timestamp_unix'], unit='s', utc=True, errors='coerce'); df.dropna(subset=['timestamp'], inplace=True); df.set_index('timestamp', inplace=True)
        numeric_cols = ['open_price', 'high_price', 'low_price', 'close_price', 'total_quantity', 'buy_quantity', 'sell_quantity', 'number_of_trades']
        for col in numeric_cols:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
            else: df[col] = np.nan
        df.dropna(subset=['open_price', 'high_price', 'low_price', 'close_price', 'total_quantity'], inplace=True); return df
    except Exception as e: logger.error(f"DB/Aggregated trade history loading error ({market} {symbol_lower}): {e}", exc_info=True); return pd.DataFrame()

async def fetch_binance_ohlcv_from_api(session: aiohttp.ClientSession, market_type: str, symbol: str, interval: str, start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> pd.DataFrame:
    api_symbol = symbol.replace('/', '')
    logger.info(f"Fetching Binance {market_type} {api_symbol} {interval} OHLCV data from API ({start_dt.strftime('%Y-%m-%d %H:%M')} to {end_dt.strftime('%Y-%m-%d %H:%M')})...")

    base_url = SPOT_API_BASE if market_type == "Spot" else FUTURES_API_BASE
    endpoint = OHLCV_API_ENDPOINT if market_type == "Spot" else FUTURES_OHLCV_API_ENDPOINT
    url = f"{base_url}{endpoint}"

    all_klines = []
    current_start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    while current_start_ms < end_ms:
        params = {
            'symbol': api_symbol,
            'interval': interval,
            'startTime': current_start_ms,
            'limit': 1000
        }
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30.0, connect=15.0)) as response:
                response.raise_for_status()
                data = await response.json()
                await asyncio.sleep(0.1)

            if not data:
                logger.info(f"  No more OHLCV data returned for period starting {pd.to_datetime(current_start_ms, unit='ms', utc=True)}. Fetch complete.")
                break

            all_klines.extend(data)
            last_kline_open_time_ms = data[-1][0]
            current_start_ms = last_kline_open_time_ms + (OHLCV_API_INTERVAL_MINUTES * 60 * 1000)

            if len(data) < params['limit']:
                break

        except aiohttp.ClientResponseError as http_error:
            logger.error(f"  Binance OHLCV fetch HTTP error ({api_symbol}, {interval}): {http_error.status}, message='{http_error.message}', url='{http_error.request_info.url}'")
            return pd.DataFrame()
        except asyncio.TimeoutError:
            logger.warning(f"  Binance OHLCV fetch timed out for period starting {pd.to_datetime(current_start_ms, unit='ms', utc=True)}. Retrying...")
            await asyncio.sleep(5)
            continue
        except Exception as e:
            logger.error(f"  Binance OHLCV fetch unexpected error ({api_symbol}, {interval}): {e}", exc_info=True)
            return pd.DataFrame()

    if not all_klines:
        logger.warning(f"Could not fetch any Binance {market_type} OHLCV data from API ({api_symbol}, {interval}).")
        return pd.DataFrame()

    cols = ['Open time','Open','High','Low','Close','Volume','Close time','Quote asset volume','Number of trades','Taker buy base volume','Taker buy quote volume','Ignore']
    df = pd.DataFrame(all_klines, columns=cols)
    df.drop_duplicates(subset=['Open time'], keep='last', inplace=True)

    num_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=num_cols, inplace=True)

    if df.empty:
        logger.warning(f"No valid numeric OHLCV data found after processing ({api_symbol}, {interval}).")
        return pd.DataFrame()

    df['timestamp'] = pd.to_datetime(df['Open time'], unit='ms', utc=True)
    df.set_index('timestamp', inplace=True)
    df.rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'}, inplace=True)
    
    final_df = df[(df.index >= start_dt) & (df.index <= end_dt)]
    
    logger.info(f"Fetched {len(final_df)} OHLCV data points from Binance API ({api_symbol}, {interval}) for final use.")
    return final_df[['open','high','low','close','volume']]

async def fetch_binance_open_interest_from_api(session: aiohttp.ClientSession, symbol: str, period: str, start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> pd.DataFrame:
    logger.info(f"Fetching Binance Futures Open Interest ({symbol}, {period}) from API ({start_dt.strftime('%Y-%m-%d %H:%M')} to {end_dt.strftime('%Y-%m-%d %H:%M')})...")
    all_oi_data = []; current_start_dt = start_dt; max_fetches = 50; fetch_count = 0
    
    try:
        num = int(''.join(filter(str.isdigit, period))); unit = ''.join(filter(str.isalpha, period))
        if unit == 'm': period_delta = pd.Timedelta(minutes=num)
        elif unit == 'h': period_delta = pd.Timedelta(hours=num)
        else: raise ValueError("Invalid unit for OI period")
    except ValueError: logger.warning(f"Invalid OI period '{period}'. Defaulting to 5m."); period = '5m'; period_delta = pd.Timedelta(minutes=5)
    
    base_url = FUTURES_API_BASE; endpoint_url = f"{base_url}{OI_API_ENDPOINT}"
    max_api_fetch_duration = pd.Timedelta(days=1)

    while current_start_dt < end_dt and fetch_count < max_fetches:
        fetch_count += 1
        fetch_end_dt = min(end_dt, current_start_dt + max_api_fetch_duration)
        start_ms = int(current_start_dt.timestamp() * 1000)
        end_ms = int(fetch_end_dt.timestamp() * 1000)

        params = {'symbol': symbol, 'period': period, 'limit': OI_FETCH_LIMIT, 'startTime': start_ms, 'endTime': end_ms}
        
        try:
            async with session.get(endpoint_url, params=params, timeout=aiohttp.ClientTimeout(total=30.0, connect=15.0)) as response:
                response.raise_for_status(); data = await response.json(); await asyncio.sleep(0.1)
            
            if not data:
                logger.info(f"  No data returned for period starting {pd.to_datetime(start_ms, unit='ms', utc=True)}. Moving to next period: {fetch_end_dt + period_delta}")
                current_start_dt = fetch_end_dt + period_delta
                continue
            
            last_existing_timestamp = all_oi_data[-1]['timestamp'] if all_oi_data else 0
            new_data = [d for d in data if d['timestamp'] > last_existing_timestamp]
            all_oi_data.extend(new_data)

            last_record_time_ms = data[-1]['timestamp']
            current_start_dt = pd.to_datetime(last_record_time_ms, unit='ms', utc=True) + period_delta
            
            logger.info(f"  Fetched {len(data)} OI data points. Total fetched: {len(all_oi_data)}. Next start time: {current_start_dt.strftime('%Y-%m-%d %H:%M')}")

        except aiohttp.ClientResponseError as http_error:
            logger.error(f"  Binance OI fetch HTTP error ({symbol}, {period}): {http_error.status}, message='{http_error.message}', url='{http_error.request_info.url}'")
            current_start_dt = fetch_end_dt + period_delta
            await asyncio.sleep(2)
        except asyncio.TimeoutError:
            logger.warning(f"  Binance OI fetch timed out for period starting {current_start_dt}. Skipping to next period.")
            current_start_dt = fetch_end_dt + period_delta
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"  Binance OI fetch unexpected error ({symbol}, {period}): {e}", exc_info=True)
            current_start_dt = fetch_end_dt + period_delta
            await asyncio.sleep(5)

    if not all_oi_data: logger.warning(f"Could not fetch Binance Futures OI data from API ({symbol}, {period}). No data found or too many errors."); return pd.DataFrame()
    
    oi_df = pd.DataFrame(all_oi_data); oi_df.drop_duplicates(subset=['timestamp'], keep='last', inplace=True)
    num_cols_oi = ['sumOpenInterest', 'sumOpenInterestValue']
    for col in num_cols_oi:
        if col in oi_df.columns:
            oi_df[col] = pd.to_numeric(oi_df[col], errors='coerce')
        else:
            logger.warning(f"Column '{col}' not found in fetched OI data.")
            oi_df[col] = np.nan
    
    oi_df.dropna(subset=['sumOpenInterest'], inplace=True)
    
    if oi_df.empty: logger.warning(f"No valid numeric OI data found ({symbol}, {period}) after processing."); return pd.DataFrame()
    
    oi_df['timestamp'] = pd.to_datetime(oi_df['timestamp'], unit='ms', utc=True); oi_df.set_index('timestamp', inplace=True)
    oi_df = oi_df[(oi_df.index >= start_dt) & (oi_df.index <= end_dt)]; oi_df = oi_df[['sumOpenInterest']]; oi_df.rename(columns={'sumOpenInterest': 'open_interest'}, inplace=True)
    logger.info(f"Fetched {len(oi_df)} OI data points from Binance API ({symbol}, {period}) for final use."); return oi_df


def plot_depth_chart_with_indicators(exchange: str, market: str, symbol: str, book_df: pd.DataFrame, aggregated_trade_df: pd.DataFrame, ohlc_data: pd.DataFrame, binance_oi_df: Optional[pd.DataFrame]) -> Optional[io.BytesIO]:
    logger.info(f"Generating composite chart [{market}] ({symbol})...")
    fig = None; is_futures = (market == "Futures")
    if book_df.empty and aggregated_trade_df.empty and ohlc_data.empty and (not is_futures or (binance_oi_df is None or binance_oi_df.empty)):
        logger.warning(f"[{market}] Skipping chart generation as all plot data is empty."); send_discord_notification(f"[{market}] Skipping chart generation as all plot data is empty.", DISCORD_LOG_WEBHOOK_URL, level="warning"); return None
    try:
        with plt.style.context('dark_background'):
            fig = plt.figure(figsize=(FIG_WIDTH, FIG_HEIGHT)); fig.patch.set_facecolor('#121212')
            gs_outer = gridspec.GridSpec(len(GRIDSPEC_HEIGHT_RATIOS_MAIN), 1, height_ratios=GRIDSPEC_HEIGHT_RATIOS_MAIN, hspace=MAIN_SUBPLOT_HSPACE, left=0.06, right=0.94, bottom=0.12, top=0.92)
            current_grid_ratios = GRIDSPEC_WIDTH_RATIOS_WITH_BAR.copy(); gs_top_outer_ratios = [current_grid_ratios[0], current_grid_ratios[1] + current_grid_ratios[2]]
            gs_top_outer_wspace = 0.054; gs_top_outer = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_outer[0], width_ratios=gs_top_outer_ratios, wspace=gs_top_outer_wspace)
            ax_cbar_left = fig.add_subplot(gs_top_outer[0]); gs_top_inner_ratios = [current_grid_ratios[1], current_grid_ratios[2]]
            gs_top_inner_wspace = 0; gs_top_inner = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_top_outer[1], width_ratios=gs_top_inner_ratios, wspace=gs_top_inner_wspace)
            ax_main_price = fig.add_subplot(gs_top_inner[0]); ax_ob_bars = fig.add_subplot(gs_top_inner[1])
            gs_middle_outer = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_outer[1], width_ratios=gs_top_outer_ratios, wspace=gs_top_outer_wspace)
            ax_middle_dummy_cbar = fig.add_subplot(gs_middle_outer[0]); ax_middle_dummy_cbar.set_visible(False)
            gs_middle_inner = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_middle_outer[1], width_ratios=gs_top_inner_ratios, wspace=gs_top_inner_wspace)
            ax_trade_vwap = fig.add_subplot(gs_middle_inner[0], sharex=ax_main_price); ax_middle_dummy_ob = fig.add_subplot(gs_middle_inner[1]); ax_middle_dummy_ob.set_visible(False)
            gs_bottom_outer = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_outer[2], width_ratios=gs_top_outer_ratios, wspace=gs_top_outer_wspace)
            ax_bottom_dummy_cbar = fig.add_subplot(gs_bottom_outer[0]); ax_bottom_dummy_cbar.set_visible(False)
            gs_bottom_inner = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_bottom_outer[1], width_ratios=gs_top_inner_ratios, wspace=gs_top_inner_wspace)
            ax_sub = fig.add_subplot(gs_bottom_inner[0], sharex=ax_main_price); ax_bottom_dummy_ob = fig.add_subplot(gs_bottom_inner[1]); ax_bottom_dummy_ob.set_visible(False)
            all_generated_axes = [ax_cbar_left, ax_main_price, ax_ob_bars, ax_middle_dummy_cbar, ax_trade_vwap, ax_middle_dummy_ob, ax_bottom_dummy_cbar, ax_sub, ax_bottom_dummy_ob]; _=[ax_.set_facecolor(BG_COLOR) for ax_ in all_generated_axes if ax_]
            plt.setp(ax_cbar_left.get_xticklabels(), visible=False); plt.setp(ax_cbar_left.get_yticklabels(), visible=False); ax_cbar_left.tick_params(axis='both', which='both', length=0); ax_cbar_left.spines['top'].set_visible(False); ax_cbar_left.spines['right'].set_visible(False); ax_cbar_left.spines['bottom'].set_visible(False); ax_cbar_left.spines['left'].set_visible(False)
            center_price = None
            if not ohlc_data.empty and 'close' in ohlc_data.columns: vp = ohlc_data['close'].dropna().tolist(); center_price = vp[-1] if vp else None
            if center_price is None and not book_df.empty and 'mid_price' in book_df.columns: mp_valid = book_df['mid_price'].dropna(); center_price = mp_valid.iloc[-1] if not mp_valid.empty else None
            if center_price is None and not aggregated_trade_df.empty and 'close_price' in aggregated_trade_df.columns: cp_valid = aggregated_trade_df['close_price'].dropna(); center_price = cp_valid.iloc[-1] if not cp_valid.empty else None
            if center_price is None: center_price = 65000.0
            price_min = center_price - (OB_Y_AXIS_RANGE / 2.0); price_max = center_price + (OB_Y_AXIS_RANGE / 2.0)
            ax_main_price.set_ylim(price_min, price_max); ax_main_price.yaxis.tick_right(); ax_main_price.yaxis.set_label_position("right"); ax_main_price.set_ylabel(""); ax_main_price.yaxis.set_major_locator(mticker.MultipleLocator(200)); ax_main_price.tick_params(axis='y', colors='white', labelsize=TICK_LABEL_FONTSIZE, labelright=False); ax_main_price.yaxis.set_major_formatter(price_formatter)
            ax_ob_bars.set_ylim(price_min, price_max); ax_ob_bars.yaxis.tick_right(); ax_ob_bars.yaxis.set_label_position("right"); ax_ob_bars.set_ylabel(""); ax_ob_bars.yaxis.set_major_locator(mticker.MultipleLocator(200)); ax_ob_bars.tick_params(axis='y', colors='white', labelsize=TICK_LABEL_FONTSIZE); plt.setp(ax_ob_bars.get_yticklabels(), visible=True); ax_ob_bars.grid(True, axis='y', linestyle=':', linewidth=0.5, color='gray', alpha=0.3, zorder=0)
            num_price_bins_hm = int(np.ceil((price_max - price_min) / OB_PRICE_RESOLUTION)); price_bins_hm = np.linspace(price_min, price_max, num_price_bins_hm + 1)
            num_price_bins_bar = int(np.ceil((price_max - price_min) / OB_BAR_AGGREGATION_PRICE)); price_bins_bar_edges = np.linspace(price_min, price_max, num_price_bins_bar + 1); price_centers_bar = price_bins_bar_edges[:-1] + OB_BAR_AGGREGATION_PRICE / 2.0
            all_times = []
            if not book_df.empty: all_times.extend(book_df.index.tolist())
            if not aggregated_trade_df.empty: all_times.extend(aggregated_trade_df.index.tolist())
            if not ohlc_data.empty:
                latest_data_time = ohlc_data.index.max() if not ohlc_data.empty else None
                if not book_df.empty and (latest_data_time is None or book_df.index.max() > latest_data_time): latest_data_time = book_df.index.max()
                if not aggregated_trade_df.empty and (latest_data_time is None or aggregated_trade_df.index.max() > latest_data_time): latest_data_time = aggregated_trade_df.index.max()
                if is_futures and binance_oi_df is not None and not binance_oi_df.empty and (latest_data_time is None or binance_oi_df.index.max() > latest_data_time): latest_data_time = binance_oi_df.index.max()
                effective_plot_end_time = latest_data_time if latest_data_time is not None else datetime.datetime.now(pytz.utc)
                effective_plot_start_time = effective_plot_end_time - pd.Timedelta(hours=HOURS_TO_PLOT)
                ohlc_for_plot_window = ohlc_data[(ohlc_data.index >= effective_plot_start_time) & (ohlc_data.index <= effective_plot_end_time)]; all_times.extend(ohlc_for_plot_window.index.tolist())
            if is_futures and binance_oi_df is not None and not binance_oi_df.empty: all_times.extend(binance_oi_df.index.tolist())
            time_min_dt_plot, time_max_dt_plot = None, None
            if all_times:
                valid_times = [t for t in all_times if pd.notna(t)]
                if valid_times: time_min_dt_plot = min(valid_times); time_max_dt_plot = max(valid_times)
            if pd.isna(time_min_dt_plot) or pd.isna(time_max_dt_plot): time_max_dt_plot = datetime.datetime.now(pytz.utc); time_min_dt_plot = time_max_dt_plot - pd.Timedelta(hours=HOURS_TO_PLOT)

            logger.info(f"[{market}] Preparing order book heatmap...")
            bid_pc_hm = None; ask_pc_hm = None
            if not book_df.empty:
                book_resampled = pd.DataFrame()
                try:
                    book_df_unique = book_df[~book_df.index.duplicated(keep='last')] if not book_df.index.is_unique else book_df
                    cols_to_resample = [col for col in ['bids_json', 'asks_json'] if col in book_df_unique.columns]
                    if cols_to_resample: book_resampled = book_df_unique[cols_to_resample].resample(OB_TIME_RESOLUTION).last().dropna(how='all')
                except Exception as resample_err: logger.error(f"Error: [{market}] Order book resampling failed: {resample_err}")
                if not book_resampled.empty:
                    time_coords_dt_hm = book_resampled.index
                    if len(time_coords_dt_hm) > 0:
                        time_deltas_hm = time_coords_dt_hm.to_series().diff().fillna(pd.Timedelta(OB_TIME_RESOLUTION)); time_edges_dt_hm_list = [time_coords_dt_hm[0]]; _ = [time_edges_dt_hm_list.append(time_coords_dt_hm[i] + time_deltas_hm.iloc[i]) for i in range(len(time_coords_dt_hm))]
                        time_edges_num_hm = mdates.date2num(time_edges_dt_hm_list); num_time_bins_hm = len(time_coords_dt_hm); bid_grid_hm = np.zeros((num_price_bins_hm, num_time_bins_hm)); ask_grid_hm = np.zeros((num_price_bins_hm, num_time_bins_hm))
                        for t_idx, timestamp in enumerate(time_coords_dt_hm):
                            row_data = book_resampled.loc[timestamp]; bids_data = row_data.get('bids_json', {}); asks_data = row_data.get('asks_json', {})
                            if isinstance(bids_data, dict): _=[ (bid_grid_hm.__setitem__((np.searchsorted(price_bins_hm, p, side='right') -1, t_idx), bid_grid_hm[np.searchsorted(price_bins_hm, p, side='right') -1, t_idx] + q)) for p, q in bids_data.items() if 0 <= np.searchsorted(price_bins_hm, p, side='right') -1 < num_price_bins_hm]
                            if isinstance(asks_data, dict): _=[ (ask_grid_hm.__setitem__((np.searchsorted(price_bins_hm, p, side='right') -1, t_idx), ask_grid_hm[np.searchsorted(price_bins_hm, p, side='right') -1, t_idx] + q)) for p, q in asks_data.items() if 0 <= np.searchsorted(price_bins_hm, p, side='right') -1 < num_price_bins_hm]
                        qty_thresh_hm = OB_MIN_QTY_THRESHOLD_HEATMAP.get(market, 0.0); bid_grid_masked_hm = np.ma.masked_where(bid_grid_hm < qty_thresh_hm, bid_grid_hm); ask_grid_masked_hm = np.ma.masked_where(ask_grid_hm < qty_thresh_hm, ask_grid_hm)
                        all_valid_quantities = [];_=[all_valid_quantities.extend(grid[~grid.mask].flatten()) for grid in [bid_grid_masked_hm, ask_grid_masked_hm] if np.ma.count(grid) > 0]
                        common_vmax = max(np.percentile(all_valid_quantities, OB_VMAX_PERCENTILE), qty_thresh_hm * 1.01) if all_valid_quantities else qty_thresh_hm * 1.01
                        effective_vmin = max(OB_LOG_VMIN, qty_thresh_hm if qty_thresh_hm > 0 else OB_LOG_VMIN); cmap_bid_hm = plt.get_cmap(OB_BID_CMAP_NAME); cmap_ask_hm = plt.get_cmap(OB_ASK_CMAP_NAME); norm_bid_hm, norm_ask_hm = None, None
                        if OB_COLOR_NORM == 'log': log_vmax = max(common_vmax, effective_vmin * 1.01); norm_bid_hm = mcolors.LogNorm(vmin=effective_vmin, vmax=log_vmax, clip=True); norm_ask_hm = mcolors.LogNorm(vmin=effective_vmin, vmax=log_vmax, clip=True)
                        elif OB_COLOR_NORM == 'power': pow_vmax = max(common_vmax, effective_vmin * 1.01); norm_bid_hm = mcolors.PowerNorm(gamma=OB_POWER_GAMMA, vmin=effective_vmin, vmax=pow_vmax, clip=True); norm_ask_hm = mcolors.PowerNorm(gamma=OB_POWER_GAMMA, vmin=effective_vmin, vmax=pow_vmax, clip=True)
                        else: norm_bid_hm = mcolors.Normalize(vmin=qty_thresh_hm, vmax=common_vmax, clip=True); norm_ask_hm = mcolors.Normalize(vmin=qty_thresh_hm, vmax=common_vmax, clip=True)
                        if num_time_bins_hm > 0 and len(time_edges_num_hm) == num_time_bins_hm + 1:
                            bid_pc_hm = ax_main_price.pcolormesh(time_edges_num_hm, price_bins_hm, bid_grid_masked_hm, cmap=cmap_bid_hm, norm=norm_bid_hm, shading='flat', zorder=1, alpha=0.8)
                            ask_pc_hm = ax_main_price.pcolormesh(time_edges_num_hm, price_bins_hm, ask_grid_masked_hm, cmap=cmap_ask_hm, norm=norm_ask_hm, shading='flat', zorder=1, alpha=0.8)
                        else: logger.warning(f"[{market}] Skipping heatmap drawing due to dimension mismatch or zero time bins.")

            if not aggregated_trade_df.empty:
                current_trade_threshold = TRADE_PLOT_MIN_QTY_THRESHOLD.get(market, 0.0); logger.info(f"[{market}] Preparing aggregated trade plot (filter threshold: {current_trade_threshold})...")
                buy_trades_to_plot = aggregated_trade_df[aggregated_trade_df['buy_quantity'] >= current_trade_threshold].copy()
                sell_trades_to_plot = aggregated_trade_df[aggregated_trade_df['sell_quantity'] >= current_trade_threshold].copy()

                if not buy_trades_to_plot.empty:
                    buy_trades_to_plot = buy_trades_to_plot.nlargest(20, 'buy_quantity').sort_index()
                if not sell_trades_to_plot.empty:
                    sell_trades_to_plot = sell_trades_to_plot.nlargest(20, 'sell_quantity').sort_index()

                combined_qty_for_scale = pd.concat([
                    buy_trades_to_plot['buy_quantity'] if not buy_trades_to_plot.empty else pd.Series(dtype='float64'),
                    sell_trades_to_plot['sell_quantity'] if not sell_trades_to_plot.empty else pd.Series(dtype='float64')
                ])
                min_q_all = combined_qty_for_scale.min() if not combined_qty_for_scale.empty else np.nan
                max_q_all = combined_qty_for_scale.max() if not combined_qty_for_scale.empty else np.nan

                def scale_trade_sizes(qtys_plot):
                    if len(qtys_plot) == 0:
                        return pd.Series(dtype='float64')
                    if np.isfinite(min_q_all) and np.isfinite(max_q_all) and max_q_all > min_q_all + 1e-9:
                        scaled = TRADE_MARKER_SIZE_MIN + (np.power((qtys_plot - min_q_all) / (max_q_all - min_q_all), TRADE_MARKER_SIZE_POWER)) * (TRADE_MARKER_SIZE_MAX - TRADE_MARKER_SIZE_MIN)
                    else:
                        scaled = pd.Series([(TRADE_MARKER_SIZE_MIN + TRADE_MARKER_SIZE_MAX) / 2.0] * len(qtys_plot), index=qtys_plot.index)
                    return np.nan_to_num(scaled.clip(lower=TRADE_MARKER_SIZE_MIN), nan=TRADE_MARKER_SIZE_MIN)

                if not buy_trades_to_plot.empty:
                    buy_times_plot = buy_trades_to_plot.index; buy_prices_plot = buy_trades_to_plot['close_price']; buy_qtys_plot = buy_trades_to_plot['buy_quantity']
                    buy_sizes_plot_final = scale_trade_sizes(buy_qtys_plot)
                    if buy_sizes_plot_final.size > 0:
                        buy_plot_df = pd.DataFrame({
                            'time_num': mdates.date2num(buy_times_plot.to_pydatetime()),
                            'price': buy_prices_plot,
                            'size': buy_sizes_plot_final,
                        }, index=buy_trades_to_plot.index).sort_values('size', ascending=True)
                        ax_main_price.scatter(buy_plot_df['time_num'], buy_plot_df['price'], s=buy_plot_df['size'], color=TRADE_BUY_COLOR, alpha=0.5, marker='o', edgecolors='w', linewidths=0.2, zorder=3.1, label="Buy Volume"); logger.info(f"[{market}] Buy aggregated trades plotted ({len(buy_trades_to_plot)} entries, top-20 by side, shared size scale, large-on-top order).")
                if not sell_trades_to_plot.empty:
                    sell_times_plot = sell_trades_to_plot.index; sell_prices_plot = sell_trades_to_plot['close_price']; sell_qtys_plot = sell_trades_to_plot['sell_quantity']
                    sell_sizes_plot_final = scale_trade_sizes(sell_qtys_plot)
                    if sell_sizes_plot_final.size > 0:
                        sell_plot_df = pd.DataFrame({
                            'time_num': mdates.date2num(sell_times_plot.to_pydatetime()),
                            'price': sell_prices_plot,
                            'size': sell_sizes_plot_final,
                        }, index=sell_trades_to_plot.index).sort_values('size', ascending=True)
                        ax_main_price.scatter(sell_plot_df['time_num'], sell_plot_df['price'], s=sell_plot_df['size'], color=TRADE_SELL_COLOR, alpha=0.3, marker='o', edgecolors='w', linewidths=0.2, zorder=3.2, label="Sell Volume"); logger.info(f"[{market}] Sell aggregated trades plotted ({len(sell_trades_to_plot)} entries, top-20 by side, shared size scale, large-on-top order).")

            if not ohlc_data.empty and all(col in ohlc_data.columns for col in ['open', 'high', 'low', 'close', 'volume']):
                ohlc_plot_df = ohlc_data[(ohlc_data.index >= time_min_dt_plot) & (ohlc_data.index <= time_max_dt_plot)]
                if not ohlc_plot_df.empty:
                    logger.info(f"[{market}] Starting {OHLCV_API_INTERVAL} candlestick plotting for visible window...")
                    ohlc_plot_idx_num = mdates.date2num(ohlc_plot_df.index.to_pydatetime()); time_diff_seconds = OHLCV_API_INTERVAL_MINUTES * 60; width_days = (time_diff_seconds / (24 * 60 * 60)) * 0.7
                    up = ohlc_plot_df[ohlc_plot_df['close'] >= ohlc_plot_df['open']]; down = ohlc_plot_df[ohlc_plot_df['close'] < ohlc_plot_df['open']]
                    up_idx_num = mdates.date2num(up.index.to_pydatetime()); down_idx_num = mdates.date2num(down.index.to_pydatetime())
                    ax_main_price.bar(up_idx_num, up['close'] - up['open'], width_days, bottom=up['open'], color=CANDLE_UP_BODY_COLOR, alpha=CANDLE_ALPHA, zorder=2.1, edgecolor=CANDLE_UP_BODY_COLOR, linewidth=CANDLE_EDGE_LW)
                    ax_main_price.bar(down_idx_num, down['close'] - down['open'], width_days, bottom=down['open'], color=CANDLE_DOWN_BODY_COLOR, alpha=CANDLE_ALPHA, zorder=2.1, edgecolor=CANDLE_DOWN_BODY_COLOR, linewidth=CANDLE_EDGE_LW)
                    ax_main_price.vlines(up_idx_num, up['low'], up['high'], color=CANDLE_UP_WICK_COLOR, linewidth=CANDLE_WICK_LW, alpha=CANDLE_ALPHA, zorder=2.0)
                    ax_main_price.vlines(down_idx_num, down['low'], down['high'], color=CANDLE_DOWN_WICK_COLOR, linewidth=CANDLE_WICK_LW, alpha=CANDLE_ALPHA, zorder=2.0)
                if not ohlc_data.empty and 'volume' in ohlc_data.columns and not ohlc_data['volume'].isnull().all():
                    logger.info(f"[{market}] Calculating and plotting VWAPs...")
                    typical_price = (ohlc_data['high'] + ohlc_data['low'] + ohlc_data['close']) / 3; pv = typical_price * ohlc_data['volume']
                    ohlc_data_vwap_num_idx = mdates.date2num(ohlc_data.index.to_pydatetime())
                    for label, (period_val, color_val) in VWAP_PERIODS_CONFIG.items():
                        if len(ohlc_data) >= period_val:
                            rolling_pv_sum = pv.rolling(window=period_val, min_periods=1).sum(); rolling_volume_sum = ohlc_data['volume'].rolling(window=period_val, min_periods=1).sum()
                            vwap_series = np.where(rolling_volume_sum != 0, rolling_pv_sum / rolling_volume_sum, np.nan)
                            ax_main_price.scatter(ohlc_data_vwap_num_idx, vwap_series, s=VWAP_MARKER_SIZE, color=color_val, label=f'VWAP({label})', marker='o', edgecolors='none', zorder=2.5, alpha=VWAP_MARKER_ALPHA)
                        else: logger.warning(f"[{market}] Not enough data for VWAP({label}) calculation (need {period_val}, got {len(ohlc_data)}).")
                latest_ohlc_visible = ohlc_plot_df.iloc[-1] if not ohlc_plot_df.empty else None
                if latest_ohlc_visible is not None and 'close' in latest_ohlc_visible and 'open' in latest_ohlc_visible:
                    latest_plot_price = latest_ohlc_visible['close']; latest_price_color = CANDLE_UP_BODY_COLOR if latest_ohlc_visible['close'] >= latest_ohlc_visible['open'] else CANDLE_DOWN_BODY_COLOR
                    ax_ob_bars.text(0.38, latest_plot_price, f'{latest_plot_price:.2f}', transform=ax_ob_bars.get_yaxis_transform(), fontsize=max(TICK_LABEL_FONTSIZE * 2.2, 18), fontweight='bold', color=latest_price_color, va='center', ha='left', bbox=dict(boxstyle='round,pad=0.28', fc='black', ec=latest_price_color, lw=1.0, alpha=0.82), zorder=6)
                    ax_ob_bars.axhline(latest_plot_price, color=latest_price_color, linestyle='--', linewidth=0.8, alpha=0.7, zorder=4)

            if time_min_dt_plot and time_max_dt_plot: ax_main_price.set_xlim(mdates.date2num(time_min_dt_plot), mdates.date2num(time_max_dt_plot))
            plt.setp(ax_main_price.get_xticklabels(), visible=False); ax_main_price.grid(True, axis='x', linestyle=':', alpha=0.3, color='gray', zorder=0)
            main_handles, main_labels = ax_main_price.get_legend_handles_labels()
            if main_handles: ax_main_price.legend(handles=main_handles, labels=main_labels, fontsize=LEGEND_FONTSIZE, loc='upper left', bbox_to_anchor=(0.01, 0.99), framealpha=0.7, labelcolor='white').get_frame().set_facecolor('black')
            cbar_formatter = mticker.LogFormatterSciNotation(base=10) if OB_COLOR_NORM == 'log' else None
            if OB_COLOR_NORM == 'linear': cbar_formatter = None
            gs_cbar_inner = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=gs_top_outer[0], hspace=0.1)
            if ask_pc_hm is not None:
                cax_ask = fig.add_subplot(gs_cbar_inner[0]); cbar_ask = fig.colorbar(ask_pc_hm, cax=cax_ask, orientation='vertical', format=cbar_formatter)
                cbar_ask.set_label('Ask Quantity', fontsize=COLORBAR_LABEL_FONTSIZE, color='white'); cbar_ask.ax.tick_params(labelsize=TICK_LABEL_FONTSIZE, colors='white'); cax_ask.yaxis.set_ticks_position('left'); cax_ask.yaxis.set_label_position('left')
                if OB_COLOR_NORM == 'log' and cbar_formatter: cbar_ask.update_ticks()
            else: cax_ask_placeholder = fig.add_subplot(gs_cbar_inner[0]); cax_ask_placeholder.set_visible(False)
            if bid_pc_hm is not None:
                cax_bid = fig.add_subplot(gs_cbar_inner[1]); cbar_bid = fig.colorbar(bid_pc_hm, cax=cax_bid, orientation='vertical', format=cbar_formatter)
                cbar_bid.set_label('Bid Quantity', fontsize=COLORBAR_LABEL_FONTSIZE, color='white'); cbar_bid.ax.tick_params(labelsize=TICK_LABEL_FONTSIZE, colors='white'); cax_bid.yaxis.set_ticks_position('left'); cax_bid.yaxis.set_label_position('left')
                if OB_COLOR_NORM == 'log' and cbar_formatter: cbar_bid.update_ticks()
            else: cax_bid_placeholder = fig.add_subplot(gs_cbar_inner[1]); cax_bid_placeholder.set_visible(False)
            logger.info(f"[{market}] Preparing order book bars..."); max_bar_qty_abs = 1.0
            if not book_df.empty and 'bids_json' in book_df.columns and 'asks_json' in book_df.columns:
                latest_book_row = book_df.iloc[-1] if not book_df.empty else None
                latest_bids_data = latest_book_row.get('bids_json', {}) if latest_book_row is not None and isinstance(latest_book_row.get('bids_json'), dict) else {}
                latest_asks_data = latest_book_row.get('asks_json', {}) if latest_book_row is not None and isinstance(latest_book_row.get('asks_json'), dict) else {}
                if num_price_bins_bar > 0:
                    price_bins_bar_edges_local = np.linspace(price_min, price_max, num_price_bins_bar + 1); price_centers_bar_local = price_bins_bar_edges_local[:-1] + OB_BAR_AGGREGATION_PRICE / 2.0
                    bid_qtys_bar = np.zeros(num_price_bins_bar); ask_qtys_bar = np.zeros(num_price_bins_bar)
                    _=[ (bid_qtys_bar.__setitem__(i, bid_qtys_bar[i] + q)) for p, q in latest_bids_data.items() if price_min <= p < price_max and 0 <= (i := int(np.floor((p - price_min) / OB_BAR_AGGREGATION_PRICE))) < num_price_bins_bar]
                    _=[ (ask_qtys_bar.__setitem__(i, ask_qtys_bar[i] + q)) for p, q in latest_asks_data.items() if price_min <= p < price_max and 0 <= (i := int(np.floor((p - price_min) / OB_BAR_AGGREGATION_PRICE))) < num_price_bins_bar]
                    current_bid_max = bid_qtys_bar.max() if bid_qtys_bar.size > 0 else 0; current_ask_max = ask_qtys_bar.max() if ask_qtys_bar.size > 0 else 0; max_bar_qty_abs = max(1.0, current_bid_max, current_ask_max)
                    bid_bar_widths_plot = (bid_qtys_bar / max_bar_qty_abs) * OB_BAR_MAX_WIDTH_RATIO; ask_bar_widths_plot = (ask_qtys_bar / max_bar_qty_abs) * OB_BAR_MAX_WIDTH_RATIO
                    ob_bid_bar_color_from_cmap = plt.get_cmap(OB_BID_CMAP_NAME)(0.8); ob_ask_bar_color_from_cmap = plt.get_cmap(OB_ASK_CMAP_NAME)(0.8)
                    ax_ob_bars.barh(price_centers_bar_local, bid_bar_widths_plot, height=OB_BAR_AGGREGATION_PRICE * 0.9, color=ob_bid_bar_color_from_cmap, alpha=0.7, align='center', zorder=1)
                    ax_ob_bars.barh(price_centers_bar_local, ask_bar_widths_plot, height=OB_BAR_AGGREGATION_PRICE * 0.9, color=ob_ask_bar_color_from_cmap, alpha=0.7, align='center', zorder=1)
                    ax_ob_bars.set_xlim(0, OB_BAR_MAX_WIDTH_RATIO * 1.1); top_n = 5
                    bid_indices_sorted_by_qty = np.argsort(bid_qtys_bar)[::-1]; top_n_bids_indices = bid_indices_sorted_by_qty[:top_n]
                    ask_indices_sorted_by_qty = np.argsort(ask_qtys_bar)[::-1]; top_n_asks_indices = ask_indices_sorted_by_qty[:top_n]
                    for i, p_center_val in enumerate(price_centers_bar_local):
                        if i in top_n_bids_indices and bid_qtys_bar[i] > 0.01: ax_ob_bars.text(bid_bar_widths_plot[i] + OB_BAR_MAX_WIDTH_RATIO * 0.015, p_center_val, f'{bid_qtys_bar[i]:.1f}', ha='left', va='center', color='lightblue', fontsize=ORDER_BOOK_QTY_FONTSIZE, zorder=1.1)
                        if i in top_n_asks_indices and ask_qtys_bar[i] > 0.01: ax_ob_bars.text(ask_bar_widths_plot[i] + OB_BAR_MAX_WIDTH_RATIO * 0.015, p_center_val, f'{ask_qtys_bar[i]:.1f}', ha='left', va='center', color='lightcoral', fontsize=ORDER_BOOK_QTY_FONTSIZE, zorder=1.1)
                else: ax_ob_bars.set_xlim(0, OB_BAR_MAX_WIDTH_RATIO * 1.1)
            ax_ob_bars.xaxis.set_visible(True); ax_ob_bars.tick_params(axis='x', colors='white', labelsize=TICK_LABEL_FONTSIZE, pad=1); ax_ob_bars.xaxis.set_ticks_position('top'); ax_ob_bars.xaxis.set_label_position('top')
            base_currency = symbol.split('/')[0] if '/' in symbol else symbol; ax_ob_bars.set_xlabel(f"Order Book Qty ({base_currency})", color='white', fontsize=AXIS_LABEL_FONTSIZE, labelpad=3)
            current_max_bar_qty_abs = max_bar_qty_abs; current_ob_bar_max_width_ratio = OB_BAR_MAX_WIDTH_RATIO
            if current_max_bar_qty_abs > 1e-9 and current_ob_bar_max_width_ratio > 1e-9:
                def qty_formatter_func(x, pos): actual_qty = (x / current_ob_bar_max_width_ratio) * current_max_bar_qty_abs; return f'{actual_qty/1e6:.1f}M' if abs(actual_qty) >= 1e6 else f'{actual_qty/1e3:.1f}k' if abs(actual_qty) >= 1e3 else f'{actual_qty:.2f}' if abs(actual_qty) < 1 and abs(actual_qty) > 1e-9 else f'{actual_qty:.1f}' if abs(actual_qty) >=1 else '0'
                ax_ob_bars.xaxis.set_major_formatter(FuncFormatter(qty_formatter_func)); tick_positions = np.linspace(0, current_ob_bar_max_width_ratio, 3); ax_ob_bars.set_xticks(tick_positions)
            else: ax_ob_bars.set_xticks([0, current_ob_bar_max_width_ratio / 2, current_ob_bar_max_width_ratio]); ax_ob_bars.xaxis.set_major_formatter(mticker.FormatStrFormatter('%.2f'))
            ax_ob_bars.grid(True, axis='x', linestyle=':', alpha=0.2, color='gray', zorder=0)

            # === マルチタイムフレームVWAPスプレッドの計算とプロット ===
            ax_trade_vwap.clear()
            ax_trade_vwap.set_facecolor(BG_COLOR)
            plt.setp(ax_trade_vwap.get_xticklabels(), visible=False)
            ax_trade_vwap.grid(True, axis='y', linestyle=':', alpha=0.3, color='gray')
            ax_trade_vwap.yaxis.tick_right()
            ax_trade_vwap.yaxis.set_label_position("right")
            ax_trade_vwap.tick_params(axis='y', colors='white', labelsize=TICK_LABEL_FONTSIZE)
            ax_trade_vwap.set_ylabel("VWAP Spread (Buy-Sell)", color='white', fontsize=AXIS_LABEL_FONTSIZE)
            ax_trade_vwap.axhline(0, color='white', linestyle='--', linewidth=0.8, alpha=0.7, zorder=1)

            if not aggregated_trade_df.empty and all(col in aggregated_trade_df.columns for col in ['close_price', 'buy_quantity', 'sell_quantity']):
                logger.info(f"[{market}] Calculating and plotting Multi-Timeframe VWAP Spread...")
                
                # 現在のマーケットに合わせたVWAP期間設定を取得
                current_vwap_periods = TRADE_VWAP_PERIODS.get(market)

                if current_vwap_periods:
                    agg_trades_for_vwap = aggregated_trade_df.copy()
                    spread_data = {}
                    # 短期・長期それぞれのVWAPとスプレッドを計算
                    for period_name, period_window in current_vwap_periods.items():
                        # 買いVWAP
                        buy_price_qty = agg_trades_for_vwap['close_price'] * agg_trades_for_vwap['buy_quantity']
                        buy_sum_price_qty_roll = buy_price_qty.rolling(window=period_window, min_periods=1).sum()
                        buy_sum_qty_roll = agg_trades_for_vwap['buy_quantity'].rolling(window=period_window, min_periods=1).sum()
                        buy_vwap = np.where(buy_sum_qty_roll != 0, buy_sum_price_qty_roll / buy_sum_qty_roll, np.nan)
                        # 売りVWAP
                        sell_price_qty = agg_trades_for_vwap['close_price'] * agg_trades_for_vwap['sell_quantity']
                        sell_sum_price_qty_roll = sell_price_qty.rolling(window=period_window, min_periods=1).sum()
                        sell_sum_qty_roll = agg_trades_for_vwap['sell_quantity'].rolling(window=period_window, min_periods=1).sum()
                        sell_vwap = np.where(sell_sum_qty_roll != 0, sell_sum_price_qty_roll / sell_sum_qty_roll, np.nan)
                        # スプレッド
                        spread_data[period_name] = pd.Series(buy_vwap - sell_vwap, index=agg_trades_for_vwap.index)

                    spread_short = spread_data.get('short', pd.Series(dtype=float)).dropna()
                    spread_long = spread_data.get('long', pd.Series(dtype=float)).dropna()

                    if not spread_short.empty and not spread_long.empty:
                        # タイムスタンプを数値に変換
                        times_num = mdates.date2num(spread_short.index.to_pydatetime())
                        
                        # 2本のラインをプロット (zorderを上げて最前面に)
                        line_short, = ax_trade_vwap.plot(times_num, spread_short, color='#3bb2e5', linewidth=1.2, label=f"Spread ({current_vwap_periods.get('short', '')})", zorder=2)
                        line_long, = ax_trade_vwap.plot(mdates.date2num(spread_long.index.to_pydatetime()), spread_long, color='#FFD700', linewidth=1.5, linestyle='--', label=f"Spread ({current_vwap_periods.get('long', '')})", zorder=2)

                        # Y軸の範囲を動的に調整
                        max_abs_spread = pd.concat([spread_short, spread_long]).abs().max()
                        padding = max(max_abs_spread * 0.1, 5)
                        ax_trade_vwap.set_ylim(-(max_abs_spread + padding), (max_abs_spread + padding))
                        ax_trade_vwap.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f'))

                        # ★★★ 変更点: シグナル強度に応じた背景の塗りつぶし ★★★
                        # 1. シグナル条件を定義
                        condition_green = (spread_short > 0) & (spread_long > 0)
                        condition_red = (spread_short < 0) & (spread_long < 0)

                        # 2. シグナルの強度を計算（短期と長期の絶対値の平均）
                        strength = (spread_short.abs() + spread_long.abs()) / 2
                        
                        # 3. 強度をアルファ値（透明度）にマッピング
                        signal_strength = strength[condition_green | condition_red]
                        max_strength_scale = signal_strength.quantile(0.95) if not signal_strength.empty else 1.0
                        
                        min_alpha = 0  # 最小の透明度
                        max_alpha = 0.3   # 最大の透明度（濃さ）
                        
                        alpha_values = min_alpha + (strength / max_strength_scale) * (max_alpha - min_alpha)
                        alpha_values = alpha_values.clip(lower=min_alpha, upper=max_alpha)

                        # 4. 条件に合致する期間を特定し、強度に応じた透明度で塗りつぶす
                        # 緑色シグナル（買い）
                        green_blocks = condition_green.ne(condition_green.shift()).cumsum()[condition_green]
                        for _, group in green_blocks.groupby(green_blocks):
                            start_idx, end_idx = group.index[0], group.index[-1]
                            avg_alpha = alpha_values.loc[start_idx:end_idx].mean()
                            ax_trade_vwap.axvspan(mdates.date2num(start_idx), mdates.date2num(end_idx),
                                                  facecolor=TRADE_BUY_COLOR, alpha=avg_alpha, zorder=0)

                        # 赤色シグナル（売り）
                        red_blocks = condition_red.ne(condition_red.shift()).cumsum()[condition_red]
                        for _, group in red_blocks.groupby(red_blocks):
                            start_idx, end_idx = group.index[0], group.index[-1]
                            avg_alpha = alpha_values.loc[start_idx:end_idx].mean()
                            ax_trade_vwap.axvspan(mdates.date2num(start_idx), mdates.date2num(end_idx),
                                                  facecolor=TRADE_SELL_COLOR, alpha=avg_alpha, zorder=0)

                        # 凡例の追加
                        ax_trade_vwap.legend(handles=[line_short, line_long], fontsize=LEGEND_FONTSIZE, loc='upper left', bbox_to_anchor=(0.01, 0.99), framealpha=0.7).get_frame().set_facecolor('black')
                    else:
                        logger.warning(f"[{market}] VWAP Spread could not be calculated for one or both periods.")
                        ax_trade_vwap.set_visible(False)
                else:
                    logger.warning(f"[{market}] VWAP period settings not found for market '{market}'. Skipping VWAP Spread plot.")
                    ax_trade_vwap.set_visible(False)
            else:
                logger.info(f"[{market}] Skipping VWAP Spread plot due to insufficient aggregated trade data.")
                ax_trade_vwap.set_visible(False)

            sub_label_text = ""
            if is_futures:
                sub_label_text = 'Open Interest'
                if binance_oi_df is not None and not binance_oi_df.empty and 'open_interest' in binance_oi_df.columns: ax_sub.plot(mdates.date2num(binance_oi_df.index.to_pydatetime()), binance_oi_df['open_interest'], color=OPEN_INTEREST_COLOR, linewidth=OPEN_INTEREST_LINEWIDTH, label='Open Interest', alpha=0.9, zorder=4)
                else: sub_label_text += ' (No Data)'
            else:
                sub_label_text = 'Volume'
                if not ohlc_data.empty and 'volume' in ohlc_data.columns:
                    ohlc_volume_plot_df = ohlc_data[(ohlc_data.index >= time_min_dt_plot) & (ohlc_data.index <= time_max_dt_plot)]
                    if not ohlc_volume_plot_df.empty:
                        times_num_vol = mdates.date2num(ohlc_volume_plot_df.index.to_pydatetime()); bar_width_td_days = (OHLCV_API_INTERVAL_MINUTES * 60 / (24 * 60 * 60)) * 0.8
                        ax_sub.bar(times_num_vol, ohlc_volume_plot_df['volume'], width=bar_width_td_days, color=VOLUME_COLOR, alpha=0.6, label='Volume')
                        if 'volume_ema' in ohlc_volume_plot_df.columns and not ohlc_volume_plot_df['volume_ema'].isnull().all(): ax_sub.plot(times_num_vol, ohlc_volume_plot_df['volume_ema'], color=VOLUME_EMA_COLOR, linewidth=VOLUME_EMA_LINEWIDTH, label=f'Volume EMA {VOLUME_EMA_HOURS}h', alpha=0.9, zorder=4)
                else: sub_label_text += ' (No Data)'
            ax_sub.set_ylabel(sub_label_text, color='white' if 'No Data' not in sub_label_text else 'gray', fontsize=AXIS_LABEL_FONTSIZE)
            ax_sub.yaxis.tick_right(); ax_sub.yaxis.set_label_position("right"); ax_sub.yaxis.set_major_formatter(y_formatter); ax_sub.tick_params(axis='y', colors='white', labelsize=TICK_LABEL_FONTSIZE)
            handles_s, labels_s = ax_sub.get_legend_handles_labels();_=[ax_sub.legend(handles_s, labels_s, fontsize=LEGEND_FONTSIZE, loc='upper left', bbox_to_anchor=(0.01, 0.99), framealpha=0.7, labelcolor='white').get_frame().set_facecolor('black') if handles_s else None]
            ax_sub.grid(True, linestyle=':', alpha=0.3, color='gray'); ax_sub.tick_params(axis='x', colors='white', labelsize=TICK_LABEL_FONTSIZE -1, pad=3); ax_sub.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M\n%m-%d', tz=JST))
            if time_min_dt_plot and time_max_dt_plot :
                plot_duration_hours = (time_max_dt_plot - time_min_dt_plot).total_seconds() / 3600; major_interval_minutes = 120 if plot_duration_hours > 12 else 60 if plot_duration_hours > 6 else 30 if plot_duration_hours > 3 else 10 if plot_duration_hours > 1 else 15
                ax_sub.xaxis.set_major_locator(mdates.MinuteLocator(interval=major_interval_minutes, tz=JST))
            plt.setp(ax_sub.get_xticklabels(), rotation=25, ha="right"); ax_sub.set_xlabel(f"Time (JST, approx. {HOURS_TO_PLOT}h)", color='white', fontsize=AXIS_LABEL_FONTSIZE -1, labelpad=8)
            title_time_str = time_max_dt_plot.astimezone(JST).strftime('%Y-%m-%d %H:%M') if pd.notna(time_max_dt_plot) else "N/A"
            fig.suptitle(f"{exchange} {symbol.replace('/','_')} [{market}] Flow Chart ({OHLCV_API_INTERVAL} Candle) - {title_time_str} JST", color='white', fontsize=TITLE_FONTSIZE, y=0.96)
            try: fig.canvas.draw(); fig.tight_layout(rect=[0.03, 0.04, 0.97, 0.95])
            except UserWarning as uw: logger.warning(f"Matplotlib draw/layout warning: {uw}")
            except Exception as e_draw: logger.error(f"Matplotlib draw/layout error: {e_draw}", exc_info=True)
            img_buffer = io.BytesIO(); plt.savefig(img_buffer, format='png', dpi=400, facecolor=fig.get_facecolor()); img_buffer.seek(0)
            logger.info(f"[{market}] Chart generation complete (in memory)."); return img_buffer
    except Exception as e: logger.error(f"[{market}] Critical error during chart generation: {e}", exc_info=True); send_discord_notification(f"[{market}] Critical error during chart generation: {e}", DISCORD_LOG_WEBHOOK_URL, level="error"); return None
    finally:
        if fig: plt.close(fig)
        gc.collect()

async def run_main_process_async():
    logger.info(f"\n--- Async process execution ({datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}) ---")
    markets_to_plot = ["Spot", "Futures"]; base_symbol = SYMBOL; exchange_name = EXCHANGE_NAME; now_jst = datetime.datetime.now(JST); now_utc = datetime.datetime.now(pytz.utc); now_str_file = now_jst.strftime("%Y%m%d_%H%M%S"); now_str_msg = now_jst.strftime('%Y-%m-%d %H:%M')
    
    async with aiohttp.ClientSession() as session:
        for market in markets_to_plot:
            logger.info(f"\n--- Starting processing for market '{market}' ---"); market_image_buffer = None
            book_df, aggregated_trade_df, binance_ohlcv_df, binance_oi_df = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
            is_futures = (market == "Futures")
            current_symbol_lower = FUTURES_SYMBOL_LOWER if is_futures else SPOT_SYMBOL_LOWER
            api_symbol_for_ohlcv = FUTURES_SYMBOL_API if is_futures else SPOT_SYMBOL_API

            try:
                book_df = load_book_data_with_stats(DB_PATH, BOOK_TABLE_NAME, market, HOURS_TO_PLOT)
                aggregated_trade_df = load_aggregated_trade_data(DB_PATH, AGGREGATED_TRADE_TABLE_NAME, market, current_symbol_lower, HOURS_TO_PLOT)

                logger.info(f"Fetching {DAYS_TO_FETCH_OHLCV_API} days of OHLCV data from API for market '{market}'...")
                ohlcv_fetch_start_time = now_utc - pd.Timedelta(days=DAYS_TO_FETCH_OHLCV_API)
                binance_ohlcv_df = await fetch_binance_ohlcv_from_api(
                    session, market, api_symbol_for_ohlcv, OHLCV_API_INTERVAL, ohlcv_fetch_start_time, now_utc
                )
                
                if binance_ohlcv_df.empty:
                    logger.warning(f"[{market}] Could not fetch OHLCV data from API. Skipping chart generation for this market.")
                    continue

                if is_futures:
                    required_history_start_time_utc_oi = now_utc - pd.Timedelta(hours=HOURS_TO_SAVE_OI_HISTORY)
                    db_oi_df = load_open_interest_data_from_db(HISTORY_DB_PATH, OPEN_INTEREST_TABLE_NAME, market, FUTURES_SYMBOL_LOWER, OI_FETCH_INTERVAL, HOURS_TO_SAVE_OI_HISTORY)
                    
                    oi_fetch_start_time = required_history_start_time_utc_oi
                    if not db_oi_df.empty:
                        last_db_oi_time = db_oi_df.index.max()
                        try:
                            oi_interval_minutes = int(''.join(filter(str.isdigit, OI_FETCH_INTERVAL)))
                            oi_fetch_start_time = max(oi_fetch_start_time, last_db_oi_time + pd.Timedelta(minutes=oi_interval_minutes))
                        except ValueError:
                            logger.warning(f"Could not parse OI_FETCH_INTERVAL '{OI_FETCH_INTERVAL}'. Using 5 minutes.")
                            oi_fetch_start_time = max(oi_fetch_start_time, last_db_oi_time + pd.Timedelta(minutes=5))
                    
                    fetched_oi_df = pd.DataFrame()
                    if oi_fetch_start_time < now_utc:
                        fetched_oi_df = await fetch_binance_open_interest_from_api(session, FUTURES_SYMBOL_API, OI_FETCH_INTERVAL, oi_fetch_start_time, now_utc)
                        if not fetched_oi_df.empty:
                            save_open_interest_data_to_db(fetched_oi_df, HISTORY_DB_PATH, OPEN_INTEREST_TABLE_NAME, market, FUTURES_SYMBOL_LOWER, OI_FETCH_INTERVAL, HOURS_TO_SAVE_OI_HISTORY)
                    
                    binance_oi_df = load_open_interest_data_from_db(HISTORY_DB_PATH, OPEN_INTEREST_TABLE_NAME, market, FUTURES_SYMBOL_LOWER, OI_FETCH_INTERVAL, HOURS_TO_PLOT)

                if 'volume' in binance_ohlcv_df.columns and not binance_ohlcv_df['volume'].isnull().all() and VOLUME_EMA_HOURS > 0:
                    try:
                        interval_seconds = OHLCV_API_INTERVAL_MINUTES * 60
                        ema_span_periods = int(VOLUME_EMA_HOURS * 3600 / interval_seconds)
                        ema_span_periods = max(1, ema_span_periods)
                        if len(binance_ohlcv_df) > ema_span_periods:
                            binance_ohlcv_df['volume_ema'] = binance_ohlcv_df['volume'].ewm(span=ema_span_periods, adjust=False).mean()
                        else:
                            binance_ohlcv_df['volume_ema'] = np.nan
                    except ValueError:
                        logger.warning(f"Could not parse OHLCV_API_INTERVAL for EMA. Volume EMA not calculated.")
                        binance_ohlcv_df['volume_ema'] = np.nan
                elif not binance_ohlcv_df.empty:
                    binance_ohlcv_df['volume_ema'] = np.nan

                market_image_buffer = plot_depth_chart_with_indicators(exchange_name, market, base_symbol, book_df, aggregated_trade_df, binance_ohlcv_df, binance_oi_df if is_futures else None)
                
                if market_image_buffer:
                    logger.info(f"[{market}] Sending chart image to Discord...");
                    safe_symbol = base_symbol.replace('/', '_')
                    market_filename = f"{exchange_name}_{market}_{safe_symbol}_{HOURS_TO_PLOT}h_flow_chart_{OHLCV_API_INTERVAL}_{now_str_file}.png"
                    discord_message = f"{exchange_name} {base_symbol} Flow Chart ({market} - {OHLCV_API_INTERVAL} Candle)\nTime: {now_str_msg} JST"
                    webhook_url_to_use = DISCORD_CHART_WEBHOOK_URLS.get(market)
                    send_discord_notification(discord_message, webhook_url_to_use, level="info", image_buffer=market_image_buffer, filename=market_filename)
            
            except Exception as market_e:
                logger.error(f"*** Error during processing of market '{market}': {market_e} ***", exc_info=True)
                send_discord_notification(f"*** Error during processing of market '{market}': {market_e} ***", DISCORD_LOG_WEBHOOK_URL, level="error")
            finally:
                logger.info(f"--- Market '{market}' processing complete ---")
                if 'market_image_buffer' in locals() and market_image_buffer and hasattr(market_image_buffer, 'closed') and not market_image_buffer.closed:
                    try: market_image_buffer.close()
                    except Exception as e_close: logger.warning(f"Warning: [{market}] Image buffer close error: {e_close}")
                del book_df, aggregated_trade_df, binance_ohlcv_df, binance_oi_df
                if 'db_oi_df' in locals(): del db_oi_df
                if 'fetched_oi_df' in locals(): del fetched_oi_df
                gc.collect()
    logger.info("\n--- All market processing complete ---")

if __name__ == "__main__":
    initialize_db(DB_PATH, HISTORY_DB_PATH)
    send_discord_notification(f"chartProt.py program started (PID: {os.getpid()})", DISCORD_LOG_WEBHOOK_URL, level="info")
    logger.info("--- chartProt.py program started ---")
    logger.info(f"Main DB Path: {DB_PATH}, History DB Path (OI only): {HISTORY_DB_PATH}")
    logger.info(f"Plot Hours: {HOURS_TO_PLOT}, OHLCV Fetch Days: {DAYS_TO_FETCH_OHLCV_API}, Symbol: {SYMBOL}")
    logger.info(f"Candle/OHLCV Interval: {OHLCV_API_INTERVAL} ({OHLCV_API_INTERVAL_MINUTES} minutes)")
    
    critical_webhook_issue = False
    for mkt, url in DISCORD_CHART_WEBHOOK_URLS.items():
        if not url or url == f"YOUR_{mkt.upper()}_WEBHOOK_URL_HERE" or not url.startswith("https://discord.com/api/webhooks/"):
            logger.critical(f"!!! CRITICAL: Discord chart Webhook URL ({mkt}) is not set correctly. Please check the configuration. !!!")
            critical_webhook_issue = True
    if not DISCORD_LOG_WEBHOOK_URL or DISCORD_LOG_WEBHOOK_URL == "YOUR_LOG_WEBHOOK_URL_HERE" or not DISCORD_LOG_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/"):
        logger.critical(f"!!! CRITICAL: Discord log Webhook URL is not set correctly. Log notifications will not work. Please check the configuration. !!!")
        critical_webhook_issue = True
    if critical_webhook_issue:
        logger.error("Exiting program safely due to Webhook URL issue. Please review settings.")
        send_discord_notification("Exiting program due to critical Webhook URL issue. Please review your settings.", DISCORD_LOG_WEBHOOK_URL, level="critical")
        exit(1)
        
    run_count = 0
    while True:
        run_count += 1
        try:
            start_time_loop = time.monotonic()
            send_discord_notification(f"Periodic execution started (run #{run_count}) - {datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}", DISCORD_LOG_WEBHOOK_URL, level="info")
            asyncio.run(run_main_process_async())
            elapsed_time = time.monotonic() - start_time_loop
            send_discord_notification(f"Periodic execution completed (run #{run_count}). Processing time: {elapsed_time:.2f}s. Waiting approx. {max(0, EXECUTION_INTERVAL_SECONDS - elapsed_time):.0f}s for next run.", DISCORD_LOG_WEBHOOK_URL, level="success")
            wait_time = EXECUTION_INTERVAL_SECONDS - elapsed_time
            if wait_time > 0:
                time.sleep(wait_time)
            else:
                logger.warning(f"Processing time ({elapsed_time:.2f}s) exceeded execution interval. Running next cycle immediately.")
                send_discord_notification(f"Processing time ({elapsed_time:.2f}s) exceeded execution interval. Running next cycle immediately.", DISCORD_LOG_WEBHOOK_URL, level="warning")
        except KeyboardInterrupt:
            logger.info("\nProgram interrupted by user. Exiting.")
            send_discord_notification("chartProt.py interrupted by user (Ctrl+C). Program will exit.", DISCORD_LOG_WEBHOOK_URL, level="warning")
            break
        except Exception as e:
            logger.critical(f"Unexpected critical error during chartProt.py execution: {e}", exc_info=True)
            tb_str = traceback.format_exc()
            send_discord_notification(f"Unexpected critical error during chartProt.py execution:\n```\n{str(e)}\n\n{tb_str[:1500]}\n```\nRetrying in {EXECUTION_INTERVAL_SECONDS} seconds.", DISCORD_LOG_WEBHOOK_URL, level="critical")
            time.sleep(EXECUTION_INTERVAL_SECONDS)
    send_discord_notification("chartProt.py program finished.", DISCORD_LOG_WEBHOOK_URL, level="info")
    logger.info("--- chartProt.py program finished ---")
