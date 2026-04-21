import sys
from pathlib import Path
import argparse
import asyncio
import importlib.util
import io
import os
import shutil
import tempfile
import time

import pandas as pd
import numpy as np
import pytz
import aiohttp

BASE = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BASE.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_DATA_DIR = BASE / 'data/live'
DEFAULT_OUT_PNG = BASE / 'orderflow' / 'chartProt3_ws_compat_v2.png'
DEFAULT_OHLCV_CACHE_PATH = BASE / 'orderflow' / 'ohlcv_cache.pkl'
DEFAULT_ABSORPTION_CFG_PATH = BASE / 'orderflow' / 'absorption_marker_config.json'


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws = load_module('chartProt3_ws_compat_base', BASE / 'orderflow' / 'chartProt3_ws_compat.py')
overlay_mod = load_module('absorption_overlay_v2', BASE / 'orderflow' / 'absorption_overlay_v2.py')


def resolve_inputs_v2(data_dir: Path):
    inputs = ws.resolve_inputs(data_dir)
    inputs['feature_jsonl'] = data_dir / 'live_features_1s.jsonl'
    inputs['oi_jsonl'] = data_dir / 'live_oi.jsonl'
    return inputs


def compute_plot_bounds(book_df: pd.DataFrame, aggregated_trade_df: pd.DataFrame, ohlc_data: pd.DataFrame, binance_oi_df: pd.DataFrame | None, cp):
    center_price = None
    if not ohlc_data.empty and 'close' in ohlc_data.columns:
        vp = ohlc_data['close'].dropna().tolist()
        center_price = vp[-1] if vp else None
    if center_price is None and not book_df.empty and 'mid_price' in book_df.columns:
        mp_valid = book_df['mid_price'].dropna()
        center_price = mp_valid.iloc[-1] if not mp_valid.empty else None
    if center_price is None and not aggregated_trade_df.empty and 'close_price' in aggregated_trade_df.columns:
        cp_valid = aggregated_trade_df['close_price'].dropna()
        center_price = cp_valid.iloc[-1] if not cp_valid.empty else None
    if center_price is None:
        center_price = 65000.0

    price_min = center_price - (cp.OB_Y_AXIS_RANGE / 2.0)
    price_max = center_price + (cp.OB_Y_AXIS_RANGE / 2.0)

    all_times = []
    if not book_df.empty:
        all_times.extend(book_df.index.tolist())
    if not aggregated_trade_df.empty:
        all_times.extend(aggregated_trade_df.index.tolist())
    if not ohlc_data.empty:
        latest_data_time = ohlc_data.index.max() if not ohlc_data.empty else None
        if not book_df.empty and (latest_data_time is None or book_df.index.max() > latest_data_time):
            latest_data_time = book_df.index.max()
        if not aggregated_trade_df.empty and (latest_data_time is None or aggregated_trade_df.index.max() > latest_data_time):
            latest_data_time = aggregated_trade_df.index.max()
        if binance_oi_df is not None and not binance_oi_df.empty and (latest_data_time is None or binance_oi_df.index.max() > latest_data_time):
            latest_data_time = binance_oi_df.index.max()
        effective_plot_end_time = latest_data_time if latest_data_time is not None else pd.Timestamp.now(tz=pytz.utc)
        effective_plot_start_time = effective_plot_end_time - pd.Timedelta(hours=cp.HOURS_TO_PLOT)
        ohlc_for_plot_window = ohlc_data[(ohlc_data.index >= effective_plot_start_time) & (ohlc_data.index <= effective_plot_end_time)]
        all_times.extend(ohlc_for_plot_window.index.tolist())
    if binance_oi_df is not None and not binance_oi_df.empty:
        all_times.extend(binance_oi_df.index.tolist())

    time_min_dt_plot, time_max_dt_plot = None, None
    if all_times:
        valid_times = [t for t in all_times if pd.notna(t)]
        if valid_times:
            time_min_dt_plot = min(valid_times)
            time_max_dt_plot = max(valid_times)
    if pd.isna(time_min_dt_plot) or pd.isna(time_max_dt_plot):
        time_max_dt_plot = pd.Timestamp.now(tz=pytz.utc)
        time_min_dt_plot = time_max_dt_plot - pd.Timedelta(hours=cp.HOURS_TO_PLOT)

    return time_min_dt_plot, time_max_dt_plot, price_min, price_max


async def run_once(hours_to_plot: int = 8, data_dir: Path | None = None, out_png: Path | None = None, ohlcv_cache_path: Path | None = None, absorption_config_path: Path | None = None, discord_channel_id: str | None = None, discord_message: str = '', keep_intermediate: bool = False):
    cp = ws.load_cp_module(ws.CP_PATH)
    cp.HOURS_TO_PLOT = ws.HOURS_TO_PLOT_OVERRIDE if ws.HOURS_TO_PLOT_OVERRIDE else hours_to_plot
    cp.OB_TIME_RESOLUTION = ws.OB_TIME_RESOLUTION_OVERRIDE
    cp.OB_Y_AXIS_RANGE = ws.OB_Y_AXIS_RANGE_OVERRIDE
    cp.OHLCV_API_INTERVAL = ws.OHLCV_INTERVAL_OVERRIDE
    cp.OHLCV_API_INTERVAL_MINUTES = ws.OHLCV_INTERVAL_MIN_OVERRIDE
    cp.OI_FETCH_INTERVAL = ws.OHLCV_INTERVAL_OVERRIDE
    cp.VWAP_PERIODS = {
        '12H': (int(12 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FFFFFF'),
        '24H': (int(24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FFD700'),
        '7D':  (int(7 * 24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FFA500'),
        '14D': (int(14 * 24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#87CEEB'),
        '30D': (int(30 * 24 * 60 / cp.OHLCV_API_INTERVAL_MINUTES), '#FF00FF'),
    }
    try:
        cp.plt.rcParams['savefig.dpi'] = ws.SAVEFIG_DPI_OVERRIDE
    except Exception:
        pass
    if ws.HIDE_LOWER_SUBPLOTS:
        cp.GRIDSPEC_HEIGHT_RATIOS_MAIN = [8.5, 0.001, 0.001]
        cp.MAIN_SUBPLOT_HSPACE = 0.0
    if ws.HEATMAP_TONE_DOWN:
        cp.OB_VMAX_PERCENTILE = ws.HEATMAP_VMAX_PERCENTILE
        cp.OB_POWER_GAMMA = ws.HEATMAP_POWER_GAMMA
    if not ws.AUTO_OB_THRESHOLD:
        try:
            base_th = float(cp.OB_MIN_QTY_THRESHOLD_HEATMAP.get('Futures', 100.0))
            cp.OB_MIN_QTY_THRESHOLD_HEATMAP['Futures'] = max(1.0, base_th * ws.HEATMAP_THRESHOLD_RELAX)
        except Exception:
            pass
    try:
        cp.TRADE_PLOT_MIN_QTY_THRESHOLD.update(ws.TRADE_PLOT_MIN_QTY_THRESHOLD_OVERRIDE)
    except Exception:
        pass

    market = 'Futures'
    symbol = cp.SYMBOL
    now_utc = pd.Timestamp.now(tz=pytz.utc)
    data_dir = data_dir or DEFAULT_DATA_DIR
    out_png = out_png or DEFAULT_OUT_PNG
    ohlcv_cache_path = ohlcv_cache_path or DEFAULT_OHLCV_CACHE_PATH
    absorption_config_path = absorption_config_path or Path(os.environ.get('ABSORPTION_CONFIG_PATH', str(DEFAULT_ABSORPTION_CFG_PATH)))

    inputs = resolve_inputs_v2(data_dir)
    book_df = ws.load_book_data_with_stats_ws(market, cp.HOURS_TO_PLOT, inputs)
    agg_df = pd.DataFrame() if ws.SKIP_HIDDEN_CALCS else ws.load_aggregated_trade_data_ws(market, cp.HOURS_TO_PLOT, inputs)

    if ws.AUTO_OB_THRESHOLD and not book_df.empty:
        qty_vals = []
        if 'bids_json' in book_df.columns:
            for d in book_df['bids_json']:
                if isinstance(d, dict):
                    qty_vals.extend([float(v) for v in d.values()])
        if 'asks_json' in book_df.columns:
            for d in book_df['asks_json']:
                if isinstance(d, dict):
                    qty_vals.extend([float(v) for v in d.values()])
        q = np.array(qty_vals, dtype=float)
        q = q[np.isfinite(q) & (q > 0)]
        if q.size > 0:
            uses_bucketed_like = np.percentile(q, 95) > 20
            pct = ws.OB_THRESHOLD_PERCENTILE_BUCKETED if uses_bucketed_like else ws.OB_THRESHOLD_PERCENTILE
            k = ws.OB_THRESHOLD_K_BUCKETED if uses_bucketed_like else ws.OB_THRESHOLD_K
            max_th = ws.OB_THRESHOLD_MAX_BUCKETED if uses_bucketed_like else ws.OB_THRESHOLD_MAX
            dyn_ob_th = float(np.clip(np.percentile(q, pct) * k, ws.OB_THRESHOLD_MIN, max_th))
            cp.OB_MIN_QTY_THRESHOLD_HEATMAP[market] = dyn_ob_th

    ohlcv_start = now_utc - pd.Timedelta(hours=cp.HOURS_TO_PLOT + 1)
    ohlcv_df = ws.load_ohlcv_cache(ohlcv_cache_path, ws.OHLCV_CACHE_TTL_SEC)
    ohlcv_cache_hit = ohlcv_df is not None
    if ohlcv_df is None:
        async with aiohttp.ClientSession() as session:
            ohlcv_df = await cp.fetch_binance_ohlcv_from_api(session, market, cp.FUTURES_SYMBOL_API, cp.OHLCV_API_INTERVAL, ohlcv_start, now_utc)
        if isinstance(ohlcv_df, pd.DataFrame) and not ohlcv_df.empty:
            ws.save_ohlcv_cache(ohlcv_cache_path, ohlcv_df)

    if not ohlcv_df.empty and 'volume' in ohlcv_df.columns and cp.VOLUME_EMA_HOURS > 0:
        interval_seconds = cp.OHLCV_API_INTERVAL_MINUTES * 60
        ema_span = max(1, int(cp.VOLUME_EMA_HOURS * 3600 / interval_seconds))
        if len(ohlcv_df) > ema_span:
            ohlcv_df['volume_ema'] = ohlcv_df['volume'].ewm(span=ema_span, adjust=False).mean()
        else:
            ohlcv_df['volume_ema'] = np.nan

    oi_df = pd.DataFrame()
    img = cp.plot_depth_chart_with_indicators(cp.EXCHANGE_NAME, market, symbol, book_df, agg_df, ohlcv_df, oi_df)
    if img is None:
        raise RuntimeError('chart generation failed (img is None)')

    out_png.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix='orderheatmap_v2_'))
    base_png = temp_dir / 'base.png'
    overlay_png = temp_dir / 'overlay.png'
    with open(base_png, 'wb') as f:
        f.write(img.getvalue())

    default_cfg = overlay_mod.load_config(DEFAULT_ABSORPTION_CFG_PATH)
    custom_cfg = overlay_mod.load_config(absorption_config_path) if absorption_config_path != DEFAULT_ABSORPTION_CFG_PATH else {}
    cfg = overlay_mod.merge_config(default_cfg, custom_cfg)

    markers = []
    if bool(cfg.get('enabled', True)) and inputs['feature_jsonl'].exists() and not ohlcv_df.empty:
        feature_df = overlay_mod.load_feature_rows(inputs['feature_jsonl'], ohlcv_start)
        visible_ohlc = ohlcv_df.copy()
        feature_bars = overlay_mod.aggregate_features_to_bars(feature_df, visible_ohlc, cfg)
        markers = overlay_mod.compute_absorption_markers(feature_bars, cfg)

    time_min_dt_plot, time_max_dt_plot, price_min, price_max = compute_plot_bounds(book_df, agg_df, ohlcv_df, oi_df, cp)

    if markers:
        overlay_mod.build_overlay_png(markers, time_min_dt_plot, time_max_dt_plot, price_min, price_max, cp, overlay_png)
        overlay_mod.composite_overlay(base_png, overlay_png, out_png)
    else:
        shutil.copy2(base_png, out_png)

    q95_for_mode = None
    try:
        qv = []
        for d in book_df.get('bids_json', pd.Series(dtype=object)):
            if isinstance(d, dict):
                qv.extend(list(d.values()))
        for d in book_df.get('asks_json', pd.Series(dtype=object)):
            if isinstance(d, dict):
                qv.extend(list(d.values()))
        if qv:
            q95_for_mode = float(np.percentile(np.array(qv, dtype=float), 95))
    except Exception:
        pass
    mode_label = 'bucketed' if (q95_for_mode is not None and q95_for_mode > 20) else 'raw'

    print(f"OK out={out_png} rows(book={len(book_df)}, agg={len(agg_df)}, ohlcv={len(ohlcv_df)}) ob_heatmap_th={cp.OB_MIN_QTY_THRESHOLD_HEATMAP.get(market)} mode={mode_label} hours={cp.HOURS_TO_PLOT} markers={len(markers)} ohlcv_cache_hit={ohlcv_cache_hit} cfg={absorption_config_path}")

    if discord_channel_id:
        ws.upload_output_if_needed(out_png, discord_channel_id, discord_message)

    if not keep_intermediate:
        shutil.rmtree(temp_dir, ignore_errors=True)
    else:
        print(f"KEEP_INTERMEDIATE dir={temp_dir}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='WS chart renderer v2 with configurable absorption marker overlay')
    ap.add_argument('--data-dir', default=str(DEFAULT_DATA_DIR))
    ap.add_argument('--out', default=str(DEFAULT_OUT_PNG))
    ap.add_argument('--ohlcv-cache', default=str(DEFAULT_OHLCV_CACHE_PATH))
    ap.add_argument('--hours', type=int, default=8)
    ap.add_argument('--absorption-config', default=str(DEFAULT_ABSORPTION_CFG_PATH))
    ap.add_argument('--keep-intermediate', action='store_true')
    ap.add_argument('--discord-channel-id', default='')
    ap.add_argument('--discord-message', default='')
    args = ap.parse_args()
    try:
        asyncio.run(run_once(
            args.hours,
            Path(args.data_dir),
            Path(args.out),
            Path(args.ohlcv_cache),
            Path(args.absorption_config),
            args.discord_channel_id or None,
            args.discord_message,
            args.keep_intermediate,
        ))
    except Exception as exc:
        raise SystemExit(str(exc))
