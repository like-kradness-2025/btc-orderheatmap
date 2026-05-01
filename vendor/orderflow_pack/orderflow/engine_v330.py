"""Canonical v3.30 engine: orchestration only.

This module replaces the historical v3 -> v322 -> v323 -> v323a import chain
with role-based modules:
- runtime_v330: shared config, data helpers, base drawing helpers
- absorption_v330: absorption marker aggregation/scoring/positioning
- oi_v330: open-interest loading/aggregation
- plot_v330: final chart composition
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pytz

import runtime_v330 as base
from absorption_v330 import aggregate_feature_bars, compute_absorption_markers
from oi_v330 import build_oi_ohlc, load_oi_rows
from plot_v330 import render_layered_chart

VERSION_LABEL = 'v3.30'


async def run_once(
    hours_to_plot: int = 12,
    data_dir: Path | None = None,
    out_png: Path | None = None,
    ohlcv_cache_path: Path | None = None,
    absorption_config_path: Path | None = None,
    discord_channel_id: str | None = None,
    discord_message: str = '',
):
    base.cp.HOURS_TO_PLOT = hours_to_plot if hours_to_plot else base.HOURS_TO_PLOT_OVERRIDE
    base.cp.OB_TIME_RESOLUTION = base.OB_TIME_RESOLUTION_OVERRIDE
    base.cp.OB_Y_AXIS_RANGE = base.OB_Y_AXIS_RANGE_OVERRIDE
    base.cp.OHLCV_API_INTERVAL = base.OHLCV_INTERVAL_OVERRIDE
    base.cp.OHLCV_API_INTERVAL_MINUTES = base.OHLCV_INTERVAL_MIN_OVERRIDE
    base.cp.OI_FETCH_INTERVAL = base.OHLCV_INTERVAL_OVERRIDE
    base.cp.VWAP_PERIODS_CONFIG = {
        '12H': (int(12 * 60 / base.cp.OHLCV_API_INTERVAL_MINUTES), '#FFFFFF'),
        '24H': (int(24 * 60 / base.cp.OHLCV_API_INTERVAL_MINUTES), '#FFD700'),
        '7D':  (int(7 * 24 * 60 / base.cp.OHLCV_API_INTERVAL_MINUTES), '#FFA500'),
        '14D': (int(14 * 24 * 60 / base.cp.OHLCV_API_INTERVAL_MINUTES), '#87CEEB'),
        '30D': (int(30 * 24 * 60 / base.cp.OHLCV_API_INTERVAL_MINUTES), '#FF00FF'),
    }
    plt.rcParams['savefig.dpi'] = base.SAVEFIG_DPI_OVERRIDE

    data_dir = data_dir or base.DEFAULT_DATA_DIR
    out_png = out_png or base.DEFAULT_OUT_PNG
    ohlcv_cache_path = ohlcv_cache_path or base.DEFAULT_OHLCV_CACHE_PATH
    absorption_config_path = absorption_config_path or base.DEFAULT_ABSORPTION_CFG_PATH
    cfg = base.load_absorption_config(absorption_config_path)
    market = 'Futures'
    symbol = base.cp.SYMBOL
    now_utc = pd.Timestamp.now(tz=pytz.utc)

    inputs = base.resolve_inputs_v3(data_dir)
    book_df = base.ws.load_book_data_with_stats_ws(market, base.cp.HOURS_TO_PLOT, inputs)
    agg_df = base.ws.load_aggregated_trade_data_ws(market, base.cp.HOURS_TO_PLOT, inputs)

    ohlcv_start = now_utc - pd.Timedelta(hours=base.cp.HOURS_TO_PLOT + 1)
    ohlcv_df = base.ws.load_ohlcv_cache(ohlcv_cache_path, base.OHLCV_CACHE_TTL_SEC)
    ohlcv_cache_hit = ohlcv_df is not None
    if ohlcv_df is None:
        async with base.aiohttp.ClientSession() as session:
            ohlcv_df = await base.cp.fetch_binance_ohlcv_from_api(
                session, market, base.cp.FUTURES_SYMBOL_API, base.cp.OHLCV_API_INTERVAL, ohlcv_start, now_utc
            )
        if isinstance(ohlcv_df, pd.DataFrame) and not ohlcv_df.empty:
            base.ws.save_ohlcv_cache(ohlcv_cache_path, ohlcv_df)

    if not ohlcv_df.empty and 'volume' in ohlcv_df.columns and base.cp.VOLUME_EMA_HOURS > 0:
        interval_seconds = base.cp.OHLCV_API_INTERVAL_MINUTES * 60
        ema_span = max(1, int(base.cp.VOLUME_EMA_HOURS * 3600 / interval_seconds))
        if len(ohlcv_df) > ema_span:
            ohlcv_df['volume_ema'] = ohlcv_df['volume'].ewm(span=ema_span, adjust=False).mean()
        else:
            ohlcv_df['volume_ema'] = pd.NA

    feature_df = base.load_feature_rows(inputs['feature_jsonl'], ohlcv_start) if inputs['feature_jsonl'].exists() else pd.DataFrame()
    bar_df = aggregate_feature_bars(feature_df, ohlcv_df, cfg) if not feature_df.empty else pd.DataFrame()
    markers = compute_absorption_markers(bar_df, cfg) if not bar_df.empty else []

    oi_df = load_oi_rows(inputs['oi_jsonl'], ohlcv_start) if inputs.get('oi_jsonl') and inputs['oi_jsonl'].exists() else pd.DataFrame()
    oi_ohlc = build_oi_ohlc(oi_df, cfg.get('bar_interval', '5min')) if not oi_df.empty else pd.DataFrame()

    img, bands_drawn = render_layered_chart(book_df, agg_df, ohlcv_df, oi_ohlc, markers, cfg, market=market, symbol=symbol)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with open(out_png, 'wb') as f:
        f.write(img.getvalue())

    print(
        f"OK version={VERSION_LABEL} out={out_png} rows(book={len(book_df)}, agg={len(agg_df)}, "
        f"ohlcv={len(ohlcv_df)}, oi={len(oi_df)}, features={len(feature_df)}) markers={len(markers)} "
        f"bands={bands_drawn} hours={base.cp.HOURS_TO_PLOT} ohlcv_cache_hit={ohlcv_cache_hit}"
    )

    if discord_channel_id:
        base.upload_output_if_needed(out_png, discord_channel_id, discord_message)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Orderheatmap v3.30 role-based renderer engine')
    ap.add_argument('--data-dir', default=str(base.DEFAULT_DATA_DIR))
    ap.add_argument('--out', default=str(base.DEFAULT_OUT_PNG))
    ap.add_argument('--ohlcv-cache', default=str(base.DEFAULT_OHLCV_CACHE_PATH))
    ap.add_argument('--hours', type=int, default=12)
    ap.add_argument('--absorption-config', default=str(base.DEFAULT_ABSORPTION_CFG_PATH))
    ap.add_argument('--discord-channel-id', default='')
    ap.add_argument('--discord-message', default='')
    args = ap.parse_args()
    try:
        asyncio.run(
            run_once(
                args.hours,
                Path(args.data_dir),
                Path(args.out),
                Path(args.ohlcv_cache),
                Path(args.absorption_config),
                args.discord_channel_id or None,
                args.discord_message,
            )
        )
    except base.DiscordUploadError as exc:
        raise SystemExit(f'Discord upload failed: {exc}')
    except Exception as exc:
        raise SystemExit(str(exc))
