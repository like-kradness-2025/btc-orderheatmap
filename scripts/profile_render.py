#!/usr/bin/env python3
"""Profile every stage of the orderheatmap rendering pipeline.

Measures wall-clock time for:
  Phase A — data loading / preparation
  Phase B — per-layer rendering
  Phase C — savefig / post-processing

Run directly on the Termux server via SSH.
"""
from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

# Project path setup — mirrors engine.py's sys.path injection
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys
for p in [_PROJECT_ROOT, str(_PROJECT_ROOT / 'vendor' / 'orderflow_pack' / 'orderflow')]:
    if p not in sys.path:
        sys.path.insert(0, p)

import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import pandas as pd

import runtime as base
from absorption_features import aggregate_feature_bars, build_absorption_features
from absorption_v1 import compute_absorption_markers_v1
from cvd import add_cvd_columns
from oi import build_oi_ohlc, load_oi_rows
import plot as plot_mod

# ------------------------------------------------------------
#  Timing
# ------------------------------------------------------------
_timings: list[tuple[str, float]] = []

class Timer:
    def __init__(self, label: str): self.label = label
    def __enter__(self): self._t0 = time.perf_counter(); return self
    def __exit__(self, *exc):
        self._elapsed = time.perf_counter() - self._t0
        _timings.append((self.label, self._elapsed))

def report():
    total = sum(t for _, t in _timings)
    print(f"\n{'='*70}")
    print(f"{'STAGE':<55} {'TIME (s)':>9}")
    print(f"{'-'*70}")
    for label, elapsed in _timings:
        pct = (elapsed / total * 100) if total > 0 else 0
        print(f"{label:<55} {elapsed:>8.3f}  ({pct:5.1f}%)")
    print(f"{'-'*70}")
    print(f"{'TOTAL':<55} {total:>8.3f}")
    print(f"{'='*70}\n")

# ------------------------------------------------------------
#  Wrapped rendering — manually timed per-layer
# ------------------------------------------------------------
def timed_render(book_df, agg_df, ohlc_data, oi_ohlc, markers, cfg, market, symbol):
    """Same signature as plot.render_layered_chart but with per-layer timing."""
    center_price = base.compute_center_price(book_df, agg_df, ohlc_data)
    price_min = center_price - (base.cp.OB_Y_AXIS_RANGE / 2.0)
    price_max = center_price + (base.cp.OB_Y_AXIS_RANGE / 2.0)
    time_min_dt_plot, time_max_dt_plot = base.compute_plot_window(
        book_df, agg_df, ohlc_data, base.cp.HOURS_TO_PLOT)

    with Timer('B0. fig+grid setup'):
        with plt.style.context('dark_background'):
            fig = plt.figure(figsize=(
                base.cp.FIG_WIDTH * base.cp.FIG_WIDTH_MULTIPLIER,
                base.cp.FIG_HEIGHT * base.cp.FIG_HEIGHT_MULTIPLIER))
            fig.patch.set_facecolor('#121212')

            import matplotlib.gridspec as gridspec
            gs_outer = gridspec.GridSpec(2, 1,
                height_ratios=[base.cp.FIG_HEIGHT_RATIO_MAIN, base.cp.FIG_HEIGHT_RATIO_OI],
                hspace=0.06, left=0.055, right=0.955, bottom=0.085, top=0.925)
            current_grid_ratios = base.cp.GRIDSPEC_WIDTH_RATIOS_WITH_BAR.copy()
            gs_top_outer = gridspec.GridSpecFromSubplotSpec(1, 2,
                subplot_spec=gs_outer[0],
                width_ratios=[current_grid_ratios[0], current_grid_ratios[1] + current_grid_ratios[2]],
                wspace=0.054)
            ax_cbar_left = fig.add_subplot(gs_top_outer[0])
            gs_top_inner = gridspec.GridSpecFromSubplotSpec(1, 2,
                subplot_spec=gs_top_outer[1],
                width_ratios=[current_grid_ratios[1], current_grid_ratios[2]], wspace=0)
            ax_main_price = fig.add_subplot(gs_top_inner[0])
            ax_ob_bars = fig.add_subplot(gs_top_inner[1])
            gs_bottom_outer = gridspec.GridSpecFromSubplotSpec(1, 2,
                subplot_spec=gs_outer[1],
                width_ratios=[current_grid_ratios[0], current_grid_ratios[1] + current_grid_ratios[2]],
                wspace=0.054)
            ax_oi_spacer = fig.add_subplot(gs_bottom_outer[0])
            gs_bottom_inner = gridspec.GridSpecFromSubplotSpec(1, 2,
                subplot_spec=gs_bottom_outer[1],
                width_ratios=[current_grid_ratios[1], current_grid_ratios[2]], wspace=0)
            ax_oi = fig.add_subplot(gs_bottom_inner[0], sharex=ax_main_price)
            for ax_ in [ax_cbar_left, ax_main_price, ax_ob_bars, ax_oi, ax_oi_spacer]:
                ax_.set_facecolor(base.cp.BG_COLOR)
            ax_oi_spacer.set_axis_off()

            import matplotlib.dates as mdates
            import matplotlib.ticker as mticker
            ax_main_price.set_ylim(price_min, price_max)
            ax_main_price.yaxis.tick_right()
            ax_main_price.yaxis.set_label_position('right')
            ax_main_price.yaxis.set_major_locator(mticker.MultipleLocator(500))
            ax_main_price.tick_params(axis='y', colors='white',
                labelsize=base.cp.TICK_LABEL_FONTSIZE, labelright=False)
            ax_main_price.yaxis.set_major_formatter(base.price_formatter)
            ax_main_price.set_xlim(mdates.date2num(time_min_dt_plot), mdates.date2num(time_max_dt_plot))
            plt.setp(ax_main_price.get_xticklabels(), visible=False)
            ax_main_price.grid(True, axis='x', linestyle=':', alpha=0.18, color='gray', zorder=0)

    with Timer('B1. heatmap + colorbars'):
        base.draw_heatmap_layer(ax_main_price, ax_cbar_left, book_df, price_min, price_max,
                                base.cp, time_min_dt_plot, time_max_dt_plot)

    with Timer('B2. candles'):
        visible_ohlc = (ohlc_data[(ohlc_data.index >= time_min_dt_plot) & (ohlc_data.index <= time_max_dt_plot)]
                        if not ohlc_data.empty else pd.DataFrame())
        base.draw_candle_layer(ax_main_price, visible_ohlc, base.cp)

    with Timer('B3. VWAP'):
        base.draw_vwap_layer(ax_main_price, visible_ohlc, base.cp)

    with Timer('B4. trade circles'):
        base.draw_trade_circle_layer(ax_main_price, agg_df, base.cp)

    with Timer('B5. absorption markers'):
        base.draw_absorption_marker_layer(ax_main_price, markers, cfg)

    with Timer('B6. OB bars'):
        base.draw_orderbook_bar_layer(ax_ob_bars, book_df, price_min, price_max, base.cp)

    with Timer('B7a. OI delta bg'):
        visible_oi = (oi_ohlc[(oi_ohlc.index >= time_min_dt_plot) & (oi_ohlc.index <= time_max_dt_plot)]
                      if not oi_ohlc.empty else pd.DataFrame())
        bands_drawn = plot_mod.draw_oi_delta_background(ax_oi, visible_oi, base.cp, visible_ohlc)

    with Timer('B7b. OI line'):
        plot_mod.draw_oi_line_layer(ax_oi, visible_oi, base.cp)

    with Timer('B7c. CVD line'):
        ax_cvd = plot_mod.draw_cvd_line_layer(ax_oi, agg_df, time_min_dt_plot, time_max_dt_plot, base.cp)

    with Timer('B8. grid+ticks'):
        ax_oi.grid(True, linestyle=':', alpha=0.16, color='gray', zorder=0)
        ax_oi.tick_params(axis='x', colors='white', labelsize=base.cp.TICK_LABEL_FONTSIZE)
        ax_oi.tick_params(axis='y', colors='white', labelsize=base.cp.TICK_LABEL_FONTSIZE)
        ax_oi.yaxis.set_major_formatter(plt.FuncFormatter(base.y_fmt))
        import pytz
        JST = pytz.timezone('Asia/Tokyo')
        ax_oi.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d\n%H:%M', tz=JST))

    with Timer('B9. labels+legend+title'):
        latest_ohlc_visible = visible_ohlc.iloc[-1] if not visible_ohlc.empty else None
        if latest_ohlc_visible is not None:
            latest_plot_price = latest_ohlc_visible['close']
            latest_price_color = (base.cp.CANDLE_UP_BODY_COLOR
                if latest_ohlc_visible['close'] >= latest_ohlc_visible['open']
                else base.cp.CANDLE_DOWN_BODY_COLOR)
            ax_main_price.text(0.015, 0.975, f'{latest_plot_price:.2f}',
                transform=ax_main_price.transAxes,
                fontsize=max(base.cp.TICK_LABEL_FONTSIZE * 2.2, 18),
                fontweight='bold', color=latest_price_color,
                va='top', ha='left',
                bbox=dict(boxstyle='round,pad=0.28', fc='black', ec=latest_price_color, lw=1.0, alpha=0.82),
                zorder=6)
            ax_ob_bars.axhline(latest_plot_price, color=latest_price_color,
                linestyle='--', linewidth=0.8, alpha=0.7, zorder=4)
        if not visible_oi.empty:
            latest_oi = visible_oi.iloc[-1]
            ax_oi.text(0.995, 0.92,
                f"OI {base.y_fmt(float(latest_oi['close']), None)}",
                transform=ax_oi.transAxes, ha='right', va='top',
                color='#00d4aa', fontsize=base.cp.TICK_LABEL_FONTSIZE + 1)
        if ax_cvd is not None and agg_df is not None and 'cvd_quote' in agg_df.columns:
            cvd_visible = agg_df[(agg_df.index >= time_min_dt_plot) & (agg_df.index <= time_max_dt_plot)]
            if not cvd_visible.empty:
                latest_cvd = pd.to_numeric(cvd_visible['cvd_quote'], errors='coerce').dropna()
                if not latest_cvd.empty:
                    ax_cvd.text(0.995, 0.72,
                        f"CVD {base.y_fmt(float(latest_cvd.iloc[-1]), None)}",
                        transform=ax_cvd.transAxes, ha='right', va='top',
                        color='#ff6b6b', fontsize=base.cp.TICK_LABEL_FONTSIZE + 1)
        from matplotlib.lines import Line2D
        main_handles, main_labels = ax_main_price.get_legend_handles_labels()
        marker_count = len(markers) if markers is not None else 0
        if marker_count > 0:
            main_handles.append(Line2D([0], [0],
                marker=cfg['plot'].get('buy_marker', 'o'), color='none',
                label='Buy absorption',
                markerfacecolor=cfg['plot'].get('buy_color', '#3b82f6'),
                markeredgecolor='white', markersize=8))
            main_handles.append(Line2D([0], [0],
                marker=cfg['plot'].get('sell_marker', 'o'), color='none',
                label='Sell absorption',
                markerfacecolor=cfg['plot'].get('sell_color', '#ef4444'),
                markeredgecolor='white', markersize=8))
        if main_handles:
            ax_main_price.legend(handles=main_handles, labels=main_labels,
                fontsize=base.cp.LEGEND_FONTSIZE, loc='lower left',
                bbox_to_anchor=(0.005, 0.005), framealpha=0.7, labelcolor='white'
            ).get_frame().set_facecolor('black')
        title_time_str = (time_max_dt_plot.astimezone(JST).strftime('%Y-%m-%d %H:%M')
                          if pd.notna(time_max_dt_plot) else 'N/A')
        fig.suptitle(
            f"{symbol.replace('/', '_')} {market} OrderHeatmap v3.41 | "
            f"{base.cp.OHLCV_API_INTERVAL} | {title_time_str} JST",
            color='white', fontsize=base.cp.TITLE_FONTSIZE, y=0.96)

    with Timer('B10. layout (tight_layout)'):
        try:
            fig.canvas.draw()
            fig.tight_layout(rect=[0.03, 0.04, 0.97, 0.95])
            main_pos = ax_main_price.get_position()
            oi_pos = ax_oi.get_position()
            ax_oi.set_position([main_pos.x0, oi_pos.y0, main_pos.width, oi_pos.height])
            if ax_cvd is not None:
                ax_cvd.set_position(ax_oi.get_position())
        except Exception:
            pass

    with Timer('B11. savefig + plt.close'):
        import io
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=base.SAVEFIG_DPI_OVERRIDE,
                    facecolor=fig.get_facecolor())
        img_buffer.seek(0)
        plt.close(fig)

    return img_buffer, bands_drawn


# ------------------------------------------------------------
#  Profiled run_once
# ------------------------------------------------------------
async def profile_run_once(
    hours_to_plot: int = 24,
    data_dir: Path | None = None,
    out_png: Path | None = None,
    ohlcv_cache_path: Path | None = None,
    absorption_config_path: Path | None = None,
):
    # Save and override chart_config values
    _saved = {a: getattr(base.cp, a) for a in (
        'HOURS_TO_PLOT', 'OB_TIME_RESOLUTION', 'OB_Y_AXIS_RANGE',
        'OHLCV_API_INTERVAL', 'OHLCV_API_INTERVAL_MINUTES',
        'OI_FETCH_INTERVAL', 'VWAP_PERIODS_CONFIG',
    )}
    base.cp.HOURS_TO_PLOT = hours_to_plot or base.HOURS_TO_PLOT_OVERRIDE
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
    cfg['bar_interval'] = f"{base.cp.OHLCV_API_INTERVAL_MINUTES}min"
    market = 'Futures'
    now_utc = pd.Timestamp.now(tz='UTC')

    # ---------- Phase A: Data Loading ----------
    with Timer('A0. resolve_inputs_v3'):
        inputs = base.resolve_inputs_v3(data_dir)

    with Timer('A1. load_book_data'):
        book_df = base.data.load_book_data_with_stats_ws(market, base.cp.HOURS_TO_PLOT, inputs)

    with Timer('A2. load_agg_trade_data'):
        agg_df = base.data.load_aggregated_trade_data_ws(market, base.cp.HOURS_TO_PLOT, inputs)

    with Timer('A3. add_cvd_columns'):
        agg_df = add_cvd_columns(agg_df)

    ohlcv_start = now_utc - pd.Timedelta(hours=base.cp.HOURS_TO_PLOT + 1)

    with Timer('A4a. OHLCV cache load'):
        cached_ohlcv = base.data.load_ohlcv_cache(ohlcv_cache_path, None)

    with Timer('A4b. OHLCV API fetch'):
        api_ohlcv = pd.DataFrame()
        async with base.aiohttp.ClientSession() as session:
            api_ohlcv = await base.cp.fetch_binance_ohlcv_from_api(
                session, market, base.cp.FUTURES_SYMBOL_API,
                base.cp.OHLCV_API_INTERVAL, ohlcv_start, now_utc)

    with Timer('A4c. OHLCV merge+sanitize+save-cache'):
        ohlcv_df = base.data.merge_ohlcv_frames(cached_ohlcv, api_ohlcv)
        if not ohlcv_df.empty and not cached_ohlcv.empty and not api_ohlcv.empty:
            base.data.save_ohlcv_cache(ohlcv_cache_path, ohlcv_df)
        if ohlcv_df is None or ohlcv_df.empty:
            ohlcv_df = base.data.generate_ohlcv_from_trades(
                inputs, base.cp.HOURS_TO_PLOT + 1, cfg.get('bar_interval', '5min'))
        ohlcv_df = base.data.sanitize_ohlcv(ohlcv_df)

    with Timer('A5. volume_ema'):
        if not ohlcv_df.empty and 'volume' in ohlcv_df.columns and base.cp.VOLUME_EMA_HOURS > 0:
            interval_seconds = base.cp.OHLCV_API_INTERVAL_MINUTES * 60
            ema_span = max(1, int(base.cp.VOLUME_EMA_HOURS * 3600 / interval_seconds))
            if len(ohlcv_df) > ema_span:
                ohlcv_df['volume_ema'] = ohlcv_df['volume'].ewm(span=ema_span, adjust=False).mean()
            else:
                ohlcv_df['volume_ema'] = pd.NA

    with Timer('A6. features+absorption'):
        feature_df = (base.load_feature_rows(inputs['feature_jsonl'], ohlcv_start)
                      if inputs['feature_jsonl'].exists() else pd.DataFrame())
        bar_df = (aggregate_feature_bars(feature_df, ohlcv_df, cfg)
                  if not feature_df.empty else pd.DataFrame())
        if not bar_df.empty:
            bar_df = build_absorption_features(bar_df, agg_df, cfg)
        markers = (compute_absorption_markers_v1(bar_df, cfg)
                   if not bar_df.empty else [])

    with Timer('A7. OI data load+build'):
        oi_df = (load_oi_rows(inputs['oi_jsonl'], ohlcv_start)
                 if inputs.get('oi_jsonl') and inputs['oi_jsonl'].exists()
                 else pd.DataFrame())
        oi_ohlc = (build_oi_ohlc(oi_df, cfg.get('bar_interval', '5min'))
                   if not oi_df.empty else pd.DataFrame())

    # ---------- Phase B: Rendering ----------
    with Timer('B_total. timed_render'):
        img, bands_drawn = timed_render(
            book_df, agg_df, ohlcv_df, oi_ohlc, markers, cfg,
            market=market, symbol=base.cp.SYMBOL)

    # Save output
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with open(out_png, 'wb') as f:
        f.write(img.getvalue())

    # Restore config
    for attr, val in _saved.items():
        setattr(base.cp, attr, val)

    print(f"\nData volumes:  book={len(book_df)}  agg={len(agg_df)}  ohlcv={len(ohlcv_df)}  "
          f"oi={len(oi_df)}  features={len(feature_df)}  markers={len(markers)}")
    report()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default=str(_PROJECT_ROOT / 'data' / 'live'))
    ap.add_argument('--out', default=str(_PROJECT_ROOT / 'artifacts' / 'profile_output.png'))
    ap.add_argument('--hours', type=int, default=24)
    ap.add_argument('--absorption-config', default=str(
        _PROJECT_ROOT / 'orderflow' / 'config' / 'absorption_marker_config.json'))
    args = ap.parse_args(argv)
    asyncio.run(profile_run_once(
        hours_to_plot=args.hours,
        data_dir=Path(args.data_dir),
        out_png=Path(args.out),
        absorption_config_path=Path(args.absorption_config),
    ))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
