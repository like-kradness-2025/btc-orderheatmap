"""Canonical v3.27 layered orderheatmap renderer.

The implementation currently delegates to the previously named
chartProt3_ws_layered_v323a module, whose internal VERSION_LABEL is already
v3.27. This file provides the stable, correctly named entrypoint used by
run_plot_v327.sh and new operational scripts.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from chartProt3_ws_layered_v323a import base, run_once


if __name__ == '__main__':
    ap = base.argparse.ArgumentParser(description='Layered orderheatmap renderer v3.27')
    ap.add_argument('--data-dir', default=str(base.DEFAULT_DATA_DIR))
    ap.add_argument('--out', default=str(base.DEFAULT_OUT_PNG))
    ap.add_argument('--ohlcv-cache', default=str(base.DEFAULT_OHLCV_CACHE_PATH))
    ap.add_argument('--hours', type=int, default=12)
    ap.add_argument('--absorption-config', default=str(base.DEFAULT_ABSORPTION_CFG_PATH))
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
        ))
    except base.DiscordUploadError as exc:
        raise SystemExit(f'Discord upload failed: {exc}')
    except Exception as exc:
        raise SystemExit(str(exc))
