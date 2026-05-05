"""Canonical canonical engine: orchestration only.

This module replaces the historical multi-version import chain
with role-based modules:
- runtime: shared config, data helpers, base drawing helpers
- absorption: absorption marker aggregation/scoring/positioning
- oi: open-interest loading/aggregation
- plot: final chart composition
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pytz

import runtime as base
from absorption import aggregate_feature_bars, compute_absorption_markers
from oi import build_oi_ohlc, load_oi_rows
from plot import render_layered_chart

RUNTIME_LABEL = 'canonical'


async def run_once(
    hours_to_plot: int = 24,
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
    book_df = base.data.load_book_data_with_stats_ws(market, base.cp.HOURS_TO_PLOT, inputs)
    agg_df = base.data.load_aggregated_trade_data_ws(market, base.cp.HOURS_TO_PLOT, inputs)

    ohlcv_start = now_utc - pd.Timedelta(hours=base.cp.HOURS_TO_PLOT + 1)
    interval_delta = pd.Timedelta(minutes=base.cp.OHLCV_API_INTERVAL_MINUTES)

    cached_ohlcv = base.data.load_ohlcv_cache(ohlcv_cache_path, None)
    api_start = ohlcv_start
    if cached_ohlcv is not None and not cached_ohlcv.empty:
        cached_end = cached_ohlcv.index.max()
        if pd.notna(cached_end) and cached_end >= ohlcv_start:
            # Re-fetch the last cached candle too; it may have been incomplete when cached.
            api_start = max(ohlcv_start, cached_end - interval_delta)

    api_ohlcv = pd.DataFrame()
    if api_start <= now_utc:
        async with base.aiohttp.ClientSession() as session:
            api_ohlcv = await base.cp.fetch_binance_ohlcv_from_api(
                session, market, base.cp.FUTURES_SYMBOL_API, base.cp.OHLCV_API_INTERVAL, api_start, now_utc
            )

    ohlcv_df = base.data.merge_ohlcv_frames(cached_ohlcv, api_ohlcv)
    if not ohlcv_df.empty:
        if cached_ohlcv is not None and not cached_ohlcv.empty and api_ohlcv is not None and not api_ohlcv.empty:
            ohlcv_source = 'cache+binance_api'
        elif api_ohlcv is not None and not api_ohlcv.empty:
            ohlcv_source = 'binance_api'
        else:
            ohlcv_source = 'cache'
        base.data.save_ohlcv_cache(ohlcv_cache_path, ohlcv_df)
    else:
        ohlcv_source = 'none'

    if ohlcv_df is None or ohlcv_df.empty:
        ohlcv_df = base.data.generate_ohlcv_from_trades(inputs, base.cp.HOURS_TO_PLOT + 1, cfg.get('bar_interval', '5min'))
        if isinstance(ohlcv_df, pd.DataFrame) and not ohlcv_df.empty:
            ohlcv_source = 'local_trades'
            base.data.save_ohlcv_cache(ohlcv_cache_path, ohlcv_df)

    ohlcv_df = base.data.sanitize_ohlcv(ohlcv_df)
    if ohlcv_df.empty:
        raise RuntimeError('OHLCV unavailable after cache+API/local-trades fallback')

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
        f"OK runtime={RUNTIME_LABEL} out={out_png} rows(book={len(book_df)}, agg={len(agg_df)}, "
        f"ohlcv={len(ohlcv_df)}, oi={len(oi_df)}, features={len(feature_df)}) markers={len(markers)} "
        f"bands={bands_drawn} hours={base.cp.HOURS_TO_PLOT} ohlcv_source={ohlcv_source}"
    )

    if discord_channel_id:
        base.upload_output_if_needed(out_png, discord_channel_id, discord_message)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Orderheatmap canonical role-based renderer engine')
    ap.add_argument('--data-dir', default=str(base.DEFAULT_DATA_DIR))
    ap.add_argument('--out', default=str(base.DEFAULT_OUT_PNG))
    ap.add_argument('--ohlcv-cache', default=str(base.DEFAULT_OHLCV_CACHE_PATH))
    ap.add_argument('--hours', type=int, default=24)
    ap.add_argument('--absorption-config', default=str(base.DEFAULT_ABSORPTION_CFG_PATH))
    ap.add_argument('--discord-channel-id', default='')
    ap.add_argument('--discord-message', default='')
    args = ap.parse_args(argv)
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
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
