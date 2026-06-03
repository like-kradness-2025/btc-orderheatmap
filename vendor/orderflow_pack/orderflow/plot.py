"""Chart composition and final rendering for orderheatmap canonical."""
from __future__ import annotations

import io

import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

import runtime as rt
from oi import draw_oi_delta_background

RUNTIME_LABEL = 'canonical'
JST = rt.JST
CVD_COLOR = '#FFD700'
OI_LINE_COLOR = '#e5e7eb'


def draw_oi_line_layer(ax_oi, oi_df: pd.DataFrame, cp_mod):
    """Draw OI as a line on the OI subplot."""
    if oi_df is None or oi_df.empty or 'close' not in oi_df.columns:
        ax_oi.text(0.5, 0.5, 'OI data unavailable', transform=ax_oi.transAxes, ha='center', va='center', color='white', alpha=0.7)
        return
    work = oi_df.copy().sort_index()
    work['close'] = pd.to_numeric(work['close'], errors='coerce')
    work = work.dropna(subset=['close'])
    if work.empty:
        ax_oi.text(0.5, 0.5, 'OI data unavailable', transform=ax_oi.transAxes, ha='center', va='center', color='white', alpha=0.7)
        return
    ax_oi.plot(
        mdates.date2num(work.index.to_pydatetime()),
        work['close'],
        color=OI_LINE_COLOR,
        linewidth=1.15,
        alpha=0.92,
        label='OI',
        zorder=2.2,
    )


def draw_cvd_line_layer(ax_oi, aggregated_trade_df: pd.DataFrame, time_min_dt_plot, time_max_dt_plot, cp_mod):
    """Draw CVD on a secondary y-axis over the OI subplot.

    Plot-only responsibility: this function assumes CVD columns were already
    created upstream by cvd.add_cvd_columns().
    """
    if aggregated_trade_df is None or aggregated_trade_df.empty or 'cvd_quote' not in aggregated_trade_df.columns:
        return None
    cvd = aggregated_trade_df[(aggregated_trade_df.index >= time_min_dt_plot) & (aggregated_trade_df.index <= time_max_dt_plot)].copy()
    if cvd.empty:
        return None
    cvd['cvd_quote'] = pd.to_numeric(cvd['cvd_quote'], errors='coerce')
    cvd = cvd.dropna(subset=['cvd_quote'])
    if cvd.empty:
        return None

    ax_cvd = ax_oi.twinx()
    ax_cvd.set_facecolor('none')
    ax_cvd.plot(
        mdates.date2num(cvd.index.to_pydatetime()),
        cvd['cvd_quote'],
        color=CVD_COLOR,
        linewidth=1.15,
        alpha=0.92,
        label='CVD',
        zorder=4.0,
    )
    ax_cvd.set_ylabel('CVD', color=CVD_COLOR, fontsize=cp_mod.AXIS_LABEL_FONTSIZE)
    ax_cvd.tick_params(axis='y', colors=CVD_COLOR, labelsize=cp_mod.TICK_LABEL_FONTSIZE)
    ax_cvd.yaxis.set_major_formatter(FuncFormatter(rt.y_fmt))
    ax_cvd.grid(False)
    return ax_cvd


def render_layered_chart(book_df: pd.DataFrame, aggregated_trade_df: pd.DataFrame, ohlc_data: pd.DataFrame, oi_ohlc: pd.DataFrame, markers, cfg, market: str = 'Futures', symbol: str = 'BTC/USDT') -> tuple[io.BytesIO, int]:
    center_price = rt.compute_center_price(book_df, aggregated_trade_df, ohlc_data)
    price_min = center_price - (rt.cp.OB_Y_AXIS_RANGE / 2.0)
    price_max = center_price + (rt.cp.OB_Y_AXIS_RANGE / 2.0)
    time_min_dt_plot, time_max_dt_plot = rt.compute_plot_window(book_df, aggregated_trade_df, ohlc_data, rt.cp.HOURS_TO_PLOT)

    with plt.style.context('dark_background'):
        fig = plt.figure(figsize=(rt.cp.FIG_WIDTH * rt.cp.FIG_WIDTH_MULTIPLIER, rt.cp.FIG_HEIGHT * rt.cp.FIG_HEIGHT_MULTIPLIER))
        fig.patch.set_facecolor('#121212')
        gs_outer = gridspec.GridSpec(2, 1, height_ratios=[rt.cp.FIG_HEIGHT_RATIO_MAIN, rt.cp.FIG_HEIGHT_RATIO_OI], hspace=0.06, left=0.055, right=0.955, bottom=0.085, top=0.925)

        current_grid_ratios = rt.cp.GRIDSPEC_WIDTH_RATIOS_WITH_BAR.copy()
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
            ax_.set_facecolor(rt.cp.BG_COLOR)
        ax_oi_spacer.set_axis_off()

        ax_main_price.set_ylim(price_min, price_max)
        ax_main_price.yaxis.tick_right()
        ax_main_price.yaxis.set_label_position('right')
        ax_main_price.yaxis.set_major_locator(mticker.MultipleLocator(500))
        ax_main_price.tick_params(axis='y', colors='white', labelsize=rt.cp.TICK_LABEL_FONTSIZE, labelright=False)
        ax_main_price.yaxis.set_major_formatter(rt.price_formatter)
        ax_main_price.set_xlim(mdates.date2num(time_min_dt_plot), mdates.date2num(time_max_dt_plot))
        plt.setp(ax_main_price.get_xticklabels(), visible=False)
        ax_main_price.grid(True, axis='x', linestyle=':', alpha=0.18, color='gray', zorder=0)

        rt.draw_heatmap_layer(ax_main_price, ax_cbar_left, book_df, price_min, price_max, rt.cp, time_min_dt_plot, time_max_dt_plot)
        visible_ohlc = ohlc_data[(ohlc_data.index >= time_min_dt_plot) & (ohlc_data.index <= time_max_dt_plot)] if not ohlc_data.empty else pd.DataFrame()
        rt.draw_candle_layer(ax_main_price, visible_ohlc, rt.cp)
        rt.draw_vwap_layer(ax_main_price, visible_ohlc, rt.cp)
        rt.draw_trade_circle_layer(ax_main_price, aggregated_trade_df, rt.cp)
        rt.draw_absorption_marker_layer(ax_main_price, markers, cfg)
        rt.draw_orderbook_bar_layer(ax_ob_bars, book_df, price_min, price_max, rt.cp)

        visible_oi = oi_ohlc[(oi_ohlc.index >= time_min_dt_plot) & (oi_ohlc.index <= time_max_dt_plot)] if not oi_ohlc.empty else pd.DataFrame()
        bands_drawn = draw_oi_delta_background(ax_oi, visible_oi, rt.cp, visible_ohlc)
        draw_oi_line_layer(ax_oi, visible_oi, rt.cp)
        ax_cvd = draw_cvd_line_layer(ax_oi, aggregated_trade_df, time_min_dt_plot, time_max_dt_plot, rt.cp)
        ax_oi.grid(True, linestyle=':', alpha=0.16, color='gray', zorder=0)
        ax_oi.tick_params(axis='x', colors='white', labelsize=rt.cp.TICK_LABEL_FONTSIZE)
        ax_oi.tick_params(axis='y', colors='white', labelsize=rt.cp.TICK_LABEL_FONTSIZE)
        ax_oi.yaxis.set_major_formatter(FuncFormatter(rt.y_fmt))
        ax_oi.set_ylabel('OI', color=OI_LINE_COLOR, fontsize=rt.cp.AXIS_LABEL_FONTSIZE)
        ax_oi.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d\n%H:%M', tz=JST))

        latest_ohlc_visible = visible_ohlc.iloc[-1] if not visible_ohlc.empty else None
        if latest_ohlc_visible is not None:
            latest_plot_price = latest_ohlc_visible['close']
            latest_price_color = rt.cp.CANDLE_UP_BODY_COLOR if latest_ohlc_visible['close'] >= latest_ohlc_visible['open'] else rt.cp.CANDLE_DOWN_BODY_COLOR
            ax_ob_bars.text(0.38, latest_plot_price, f'{latest_plot_price:.2f}', transform=ax_ob_bars.get_yaxis_transform(), fontsize=max(rt.cp.TICK_LABEL_FONTSIZE * 2.2, 18), fontweight='bold', color=latest_price_color, va='center', ha='left', bbox=dict(boxstyle='round,pad=0.28', fc='black', ec=latest_price_color, lw=1.0, alpha=0.82), zorder=6)
            ax_ob_bars.axhline(latest_plot_price, color=latest_price_color, linestyle='--', linewidth=0.8, alpha=0.7, zorder=4)

        if not visible_oi.empty:
            latest_oi = visible_oi.iloc[-1]
            ax_oi.text(0.995, 0.92, f"OI {rt.y_fmt(float(latest_oi['close']), None)}", transform=ax_oi.transAxes, ha='right', va='top', color=OI_LINE_COLOR, fontsize=rt.cp.TICK_LABEL_FONTSIZE + 1)
        if ax_cvd is not None and aggregated_trade_df is not None and 'cvd_quote' in aggregated_trade_df.columns:
            cvd_visible = aggregated_trade_df[(aggregated_trade_df.index >= time_min_dt_plot) & (aggregated_trade_df.index <= time_max_dt_plot)]
            if not cvd_visible.empty:
                latest_cvd = pd.to_numeric(cvd_visible['cvd_quote'], errors='coerce').dropna()
                if not latest_cvd.empty:
                    ax_cvd.text(0.995, 0.72, f"CVD {rt.y_fmt(float(latest_cvd.iloc[-1]), None)}", transform=ax_cvd.transAxes, ha='right', va='top', color=CVD_COLOR, fontsize=rt.cp.TICK_LABEL_FONTSIZE + 1)

        main_handles, main_labels = ax_main_price.get_legend_handles_labels()
        marker_count = len(markers) if markers is not None else 0
        if marker_count > 0:
            main_handles.append(Line2D([0], [0], marker=cfg['plot'].get('buy_marker', 'o'), color='none', label='Buy absorption', markerfacecolor=cfg['plot'].get('buy_color', '#3b82f6'), markeredgecolor='white', markersize=8))
            main_handles.append(Line2D([0], [0], marker=cfg['plot'].get('sell_marker', 'o'), color='none', label='Sell absorption', markerfacecolor=cfg['plot'].get('sell_color', '#ef4444'), markeredgecolor='white', markersize=8))
            main_labels.extend(['Buy absorption', 'Sell absorption'])
        if main_handles:
            ax_main_price.legend(handles=main_handles, labels=main_labels, fontsize=rt.cp.LEGEND_FONTSIZE, loc='upper left', bbox_to_anchor=(0.01, 0.99), framealpha=0.7, labelcolor='white').get_frame().set_facecolor('black')

        title_time_str = time_max_dt_plot.astimezone(JST).strftime('%Y-%m-%d %H:%M') if pd.notna(time_max_dt_plot) else 'N/A'
        fig.suptitle(f"{symbol.replace('/', '_')} {market} OrderHeatmap v3.41 | {rt.cp.OHLCV_API_INTERVAL} | {title_time_str} JST", color='white', fontsize=rt.cp.TITLE_FONTSIZE, y=0.96)
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
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=rt.SAVEFIG_DPI_OVERRIDE, facecolor=fig.get_facecolor())
        img_buffer.seek(0)
        plt.close(fig)
        return img_buffer, bands_drawn
