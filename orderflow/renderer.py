"""Canonical CLI entrypoint for BTC orderheatmap.

This module is the stable, versionless runtime surface. The canonical engine is
hidden behind a stable internal engine alias while keeping existing chart
behavior intact.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
from pathlib import Path

from .version import RUNTIME_LABEL

ROOT = Path(__file__).resolve().parents[1]
ENGINE_ALIAS_PATH = ROOT / "vendor" / "orderflow_pack" / "orderflow" / "current_engine.py"
DEFAULT_DATA_DIR = ROOT / "data" / "live"
DEFAULT_OUT_PNG = ROOT / "artifacts" / "orderflow_chart_latest.png"
DEFAULT_OHLCV_CACHE_PATH = ROOT / "runtime" / "cache" / "ohlcv_cache.pkl"
DEFAULT_ABSORPTION_CFG_PATH = ROOT / "orderflow" / "config" / "absorption_marker_config.json"


def _load_engine():
    spec = importlib.util.spec_from_file_location("orderheatmap_current_engine", ENGINE_ALIAS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load renderer engine: {ENGINE_ALIAS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run_once(
    hours: int,
    data_dir: Path,
    out_png: Path,
    ohlcv_cache: Path,
    absorption_config: Path,
    discord_channel_id: str | None = None,
    discord_message: str = "",
) -> None:
    engine = _load_engine()
    await engine.run_once(
        hours,
        data_dir,
        out_png,
        ohlcv_cache,
        absorption_config,
        discord_channel_id,
        discord_message,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"BTC orderheatmap renderer {RUNTIME_LABEL}")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--out", default=str(DEFAULT_OUT_PNG))
    parser.add_argument("--ohlcv-cache", default=str(DEFAULT_OHLCV_CACHE_PATH))
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--absorption-config", default=str(DEFAULT_ABSORPTION_CFG_PATH))
    parser.add_argument("--discord-channel-id", default="")
    parser.add_argument("--discord-message", default="")
    return parser


def main() -> None:
    args = build_parser().parse_args()
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
        print(f"OK canonical_orderheatmap_runtime={RUNTIME_LABEL}")
    except Exception as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
