import argparse
import asyncio
import importlib.util
import io
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import pytz
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

BASE = Path(__file__).resolve().parent
TARGET_PATH = BASE / 'chartProt3_ws_layered_v323.py'
VERSION_LABEL = 'v3.23a'
JST = pytz.timezone('Asia/Tokyo')


def load_target_module():
    spec = importlib.util.spec_from_file_location('chartProt3_ws_layered_v323_for_v323a', str(TARGET_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


target = load_target_module()
base = target.base


def draw_oi_delta_background(ax_oi, oi_df: pd.DataFrame, cp_mod):
    if oi_df.empty:
        return
    slot_days = (cp_mod.OHLCV_API_INTERVAL_MINUTES * 60) / (24 * 60 * 60)
    blue = '#60a5fa'
    red = '#fca5a5'
    for ts, row in oi_df.iterrows():
        try:
            delta = float(row['close']) - float(row['open'])
        except Exception:
            continue
        if not np.isfinite(delta) or abs(delta) <= 1e-12:
            continue
        center = mdates.date2num(pd.Timestamp(ts).to_pydatetime())
        left = center - slot_days / 2.0
        right = center + slot_days / 2.0
        color = blue if delta > 0 else red
        ax_oi.axvspan(left, right, color=color, alpha=0.10, ec='none', zorder=0.1)


def render_layered_chart(book_df: pd.DataFrame, aggregated_trade_df: pd.DataFrame, ohlc_data: pd.DataFrame, oi_ohlc: pd.DataFrame, markers, cfg, market: str = 'Futures', symbol: str = 'BTC/USDT') -> io.BytesIO:
    center_price = base.compute_center_price(book_df, aggregated_trade_df, ohlc_data)
    price_min = center_price - (base.cp.OB_Y_AXIS_RANGE / 2.0)
    price_max = center_price + (base.cp.OB_Y_AXIS_RANGE / 2.0)
    time_min_dt_plot, time_max_dt_plot = base.compute_plot_window(book_df, aggregated_trade_df, ohlc_data, base.cp.HOURS_TO_PLOT)

    with plt.style.context('dark_background'):
        fig = plt.figure(figsize=(base.cp.FIG_WIDTH * 1.5, base.cp.FIG_HEIGHT * 1.12))
        fig.patch.set_facecolor('#121212')
        gs_outer = gridspec.GridSpec(2, 1, height_ratios=[6.2, 1.55], hspace=0.08, left=0.06, right=0.94, bottom=0.10, top=0.92)

        current_grid_ratios = base.cp.GRIDSPEC_WIDTH_RATIOS_WITH_BAR.copy()
        gs_top_outer = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_outer[0], width_ratios=[current_grid_ratios[0], current_grid_ratios[1] + current_grid_ratios[2]], wspace=0.054)
        ax_cbar_left = fig.add_subplot(gs_top_outer[0])
        gs_top_inner = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_top_outer[1], width_ratios=[current_grid_ratios[1], current_grid_ratios[2]], wspace=0)
        ax_main_price = fig.add_subplot(gs_top_inner[0])
        ax_ob_bars = fig.add_subplot(gs_top_inner[1])

        gs_bottom_outer = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_outer[1], width_ratios=[current_grid_ratios[0], current_grid_ratios[1] + current_grid_ratios[2]], wspace=0.054)
        ax_oi_spacer = fig.add_subplot(gs_bottom_outer[0])
        gs_bottom_inner = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_bottom_outer[1], width_ratios=[current_grid_ratios[1], current_grid_ratios[2]], wspace=0)
        ax_oi = fig.add_subplot(gs_bottom_inner[0], sharex=ax_main_price)

        for ax_ in [ax_cbar_left, ax_main_price, ax_ob_bars, ax_oi, ax_oi_spacer]:
            ax_.set_facecolor(base.cp.BG_COLOR)
        ax_oi_spacer.set_axis_off()

        ax_main_price.set_ylim(price_min, price_max)
        ax_main_price.yaxis.tick_right()
        ax_main_price.yaxis.set_label_position('right')
        ax_main_price.yaxis.set_major_locator(mticker.MultipleLocator(200))
        ax_main_price.tick_params(axis='y', colors='white', labelsize=base.cp.TICK_LABEL_FONTSIZE, labelright=False)
        ax_main_price.yaxis.set_major_formatter(base.price_formatter)
        ax_main_price.set_xlim(mdates.date2num(time_min_dt_plot), mdates.date2num(time_max_dt_plot))
        plt.setp(ax_main_price.get_xticklabels(), visible=False)
        ax_main_price.grid(True, axis='x', linestyle=':', alpha=0.3, color='gray', zorder=0)

        base.draw_heatmap_layer(ax_main_price, ax_cbar_left, book_df, price_min, price_max, base.cp, time_min_dt_plot, time_max_dt_plot)
        visible_ohlc = ohlc_data[(ohlc_data.index >= time_min_dt_plot) & (ohlc_data.index <= time_max_dt_plot)] if not ohlc_data.empty else pd.DataFrame()
        base.draw_candle_layer(ax_main_price, visible_ohlc, base.cp)
        base.draw_vwap_layer(ax_main_price, visible_ohlc, base.cp)
        base.draw_trade_circle_layer(ax_main_price, aggregated_trade_df, base.cp)
        base.draw_absorption_marker_layer(ax_main_price, markers, cfg)
        base.draw_orderbook_bar_layer(ax_ob_bars, book_df, price_min, price_max, base.cp)

        visible_oi = oi_ohlc[(oi_ohlc.index >= time_min_dt_plot) & (oi_ohlc.index <= time_max_dt_plot)] if not oi_ohlc.empty else pd.DataFrame()
        draw_oi_delta_background(ax_oi, visible_oi, base.cp)
        target.draw_oi_candle_layer(ax_oi, visible_oi, base.cp)
        ax_oi.grid(True, linestyle=':', alpha=0.25, color='gray', zorder=0)
        ax_oi.tick_params(axis='x', colors='white', labelsize=base.cp.TICK_LABEL_FONTSIZE)
        ax_oi.tick_params(axis='y', colors='white', labelsize=base.cp.TICK_LABEL_FONTSIZE)
        ax_oi.yaxis.set_major_formatter(FuncFormatter(base.y_fmt))
        ax_oi.set_ylabel('OI', color='white', fontsize=base.cp.AXIS_LABEL_FONTSIZE)
        ax_oi.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d\n%H:%M', tz=JST))

        latest_ohlc_visible = visible_ohlc.iloc[-1] if not visible_ohlc.empty else None
        if latest_ohlc_visible is not None:
            latest_plot_price = latest_ohlc_visible['close']
            latest_price_color = base.cp.CANDLE_UP_BODY_COLOR if latest_ohlc_visible['close'] >= latest_ohlc_visible['open'] else base.cp.CANDLE_DOWN_BODY_COLOR
            ax_ob_bars.text(0.38, latest_plot_price, f'{latest_plot_price:.2f}', transform=ax_ob_bars.get_yaxis_transform(), fontsize=max(base.cp.TICK_LABEL_FONTSIZE * 2.2, 18), fontweight='bold', color=latest_price_color, va='center', ha='left', bbox=dict(boxstyle='round,pad=0.28', fc='black', ec=latest_price_color, lw=1.0, alpha=0.82), zorder=6)
            ax_ob_bars.axhline(latest_plot_price, color=latest_price_color, linestyle='--', linewidth=0.8, alpha=0.7, zorder=4)

        if not visible_oi.empty:
            latest_oi = visible_oi.iloc[-1]
            oi_color = base.cp.CANDLE_UP_BODY_COLOR if latest_oi['close'] >= latest_oi['open'] else base.cp.CANDLE_DOWN_BODY_COLOR
            ax_oi.text(0.995, 0.92, f"OI {base.y_fmt(float(latest_oi['close']), None)}", transform=ax_oi.transAxes, ha='right', va='top', color=oi_color, fontsize=base.cp.TICK_LABEL_FONTSIZE + 1)

        main_handles, main_labels = ax_main_price.get_legend_handles_labels()
        if markers:
            main_handles.append(Line2D([0], [0], marker=cfg['plot'].get('buy_marker', 'o'), color='none', label='Buy absorption', markerfacecolor=cfg['plot'].get('buy_color', '#3b82f6'), markeredgecolor='white', markersize=8))
            main_handles.append(Line2D([0], [0], marker=cfg['plot'].get('sell_marker', 'o'), color='none', label='Sell absorption', markerfacecolor=cfg['plot'].get('sell_color', '#ef4444'), markeredgecolor='white', markersize=8))
            main_labels.extend(['Buy absorption', 'Sell absorption'])
        if main_handles:
            ax_main_price.legend(handles=main_handles, labels=main_labels, fontsize=base.cp.LEGEND_FONTSIZE, loc='upper left', bbox_to_anchor=(0.01, 0.99), framealpha=0.7, labelcolor='white').get_frame().set_facecolor('black')

        title_time_str = time_max_dt_plot.astimezone(JST).strftime('%Y-%m-%d %H:%M') if pd.notna(time_max_dt_plot) else 'N/A'
        fig.suptitle(f"{base.cp.EXCHANGE_NAME} {symbol.replace('/', '_')} [{market}] Layered Flow Chart {VERSION_LABEL} ({base.cp.OHLCV_API_INTERVAL} Candle) - {title_time_str} JST", color='white', fontsize=base.cp.TITLE_FONTSIZE, y=0.96)
        try:
            fig.canvas.draw()
            fig.tight_layout(rect=[0.03, 0.04, 0.97, 0.95])
            main_pos = ax_main_price.get_position()
            oi_pos = ax_oi.get_position()
            ax_oi.set_position([main_pos.x0, oi_pos.y0, main_pos.width, oi_pos.height])
        except Exception:
            pass
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=276, facecolor=fig.get_facecolor())
        img_buffer.seek(0)
        plt.close(fig)
        return img_buffer


async def run_once(hours_to_plot: int = 12, data_dir: Path | None = None, out_png: Path | None = None, ohlcv_cache_path: Path | None = None, absorption_config_path: Path | None = None, discord_channel_id: str | None = None, discord_message: str = ''):
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
    cfg = target.mod.load_absorption_config(absorption_config_path)
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
            ohlcv_df = await base.cp.fetch_binance_ohlcv_from_api(session, market, base.cp.FUTURES_SYMBOL_API, base.cp.OHLCV_API_INTERVAL, ohlcv_start, now_utc)
        if isinstance(ohlcv_df, pd.DataFrame) and not ohlcv_df.empty:
            base.ws.save_ohlcv_cache(ohlcv_cache_path, ohlcv_df)

    if not ohlcv_df.empty and 'volume' in ohlcv_df.columns and base.cp.VOLUME_EMA_HOURS > 0:
        interval_seconds = base.cp.OHLCV_API_INTERVAL_MINUTES * 60
        ema_span = max(1, int(base.cp.VOLUME_EMA_HOURS * 3600 / interval_seconds))
        if len(ohlcv_df) > ema_span:
            ohlcv_df['volume_ema'] = ohlcv_df['volume'].ewm(span=ema_span, adjust=False).mean()
        else:
            ohlcv_df['volume_ema'] = np.nan

    feature_df = base.load_feature_rows(inputs['feature_jsonl'], ohlcv_start) if inputs['feature_jsonl'].exists() else pd.DataFrame()
    bar_df = target.mod.aggregate_feature_bars(feature_df, ohlcv_df, cfg) if not feature_df.empty else pd.DataFrame()
    markers = target.mod.compute_absorption_markers(bar_df, cfg) if not bar_df.empty else []

    oi_df = target.load_oi_rows(inputs['oi_jsonl'], ohlcv_start) if inputs.get('oi_jsonl') and inputs['oi_jsonl'].exists() else pd.DataFrame()
    oi_ohlc = target.build_oi_ohlc(oi_df, cfg.get('bar_interval', '5min')) if not oi_df.empty else pd.DataFrame()

    img = render_layered_chart(book_df, agg_df, ohlcv_df, oi_ohlc, markers, cfg, market=market, symbol=symbol)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with open(out_png, 'wb') as f:
        f.write(img.getvalue())

    print(f"OK version={VERSION_LABEL} out={out_png} rows(book={len(book_df)}, agg={len(agg_df)}, ohlcv={len(ohlcv_df)}, oi={len(oi_df)}, features={len(feature_df)}) markers={len(markers)} hours={base.cp.HOURS_TO_PLOT} ohlcv_cache_hit={ohlcv_cache_hit}")

    if discord_channel_id:
        base.upload_output_if_needed(out_png, discord_channel_id, discord_message)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Layered orderheatmap renderer with OI delta background stripes')
    ap.add_argument('--data-dir', default=str(base.DEFAULT_DATA_DIR))
    ap.add_argument('--out', default=str(base.DEFAULT_OUT_PNG))
    ap.add_argument('--ohlcv-cache', default=str(base.DEFAULT_OHLCV_CACHE_PATH))
    ap.add_argument('--hours', type=int, default=12)
    ap.add_argument('--absorption-config', default=str(base.DEFAULT_ABSORPTION_CFG_PATH))
    ap.add_argument('--discord-channel-id', default='')
    ap.add_argument('--discord-message', default='')
    args = ap.parse_args()
    try:
        asyncio.run(run_once(args.hours, Path(args.data_dir), Path(args.out), Path(args.ohlcv_cache), Path(args.absorption_config), args.discord_channel_id or None, args.discord_message))
    except base.DiscordUploadError as exc:
        raise SystemExit(f'Discord upload failed: {exc}')
    except Exception as exc:
        raise SystemExit(str(exc))
