#!/usr/bin/env python3
"""Calculate per-row absorption scores for live feature JSONL.

This script loads the absorption marker config and a JSONL of live feature rows,
computes normalized buy/sell absorption scores, and writes an augmented JSONL
with score fields appended.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ORDERFLOW_DIR = ROOT / "vendor" / "orderflow_pack" / "orderflow"
DEFAULT_CFG_PATH = ROOT / "orderflow" / "config" / "absorption_marker_config.json"
DEFAULT_INPUT_PATH = ROOT / "data" / "live" / "live_features_1s.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "live" / "live_features_with_scores.jsonl"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


runtime_mod = load_module("orderflow_runtime", ORDERFLOW_DIR / "runtime.py")
load_absorption_config = runtime_mod.load_absorption_config
normalize_series = runtime_mod.normalize_series
_positive = runtime_mod._positive
_negative_abs = runtime_mod._negative_abs


SCORE_COLUMNS = [
    "trade_imbalance_notional_window",
    "mid_move_window_bps",
    "net_ask_add_cancel_notional_window",
    "net_bid_add_cancel_notional_window",
    "best_ask_qty_delta_window",
    "best_bid_qty_delta_window",
    "depth_ask_notional_5bps_delta_window",
    "depth_bid_notional_5bps_delta_window",
]


def _read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
                if limit is not None and len(rows) >= limit:
                    break
    return rows


def compute_scores(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["buy_score", "sell_score", "absorption_score"])

    work = df.copy()
    norm_q = float(cfg.get("normalize_quantile", 0.95))
    norm_floor = float(cfg.get("normalize_floor", 1.0))
    move_q = float(cfg.get("mid_move_quantile", 0.90))
    move_floor = float(cfg.get("mid_move_floor", 0.25))

    for col in SCORE_COLUMNS:
        if col not in work.columns:
            work[col] = 0.0
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)

    work["ti_norm"] = normalize_series(work["trade_imbalance_notional_window"], q=norm_q, floor=norm_floor)
    work["mid_move_norm"] = normalize_series(work["mid_move_window_bps"], q=move_q, floor=move_floor)
    work["ask_replenish_norm"] = normalize_series(work["net_ask_add_cancel_notional_window"], q=norm_q, floor=norm_floor)
    work["bid_replenish_norm"] = normalize_series(work["net_bid_add_cancel_notional_window"], q=norm_q, floor=norm_floor)
    work["best_ask_delta_norm"] = normalize_series(work["best_ask_qty_delta_window"], q=norm_q, floor=norm_floor)
    work["best_bid_delta_norm"] = normalize_series(work["best_bid_qty_delta_window"], q=norm_q, floor=norm_floor)
    work["depth_ask_delta_norm"] = normalize_series(work["depth_ask_notional_5bps_delta_window"], q=norm_q, floor=norm_floor)
    work["depth_bid_delta_norm"] = normalize_series(work["depth_bid_notional_5bps_delta_window"], q=norm_q, floor=norm_floor)

    buy_score = (
        float(cfg.get("buy_trade_weight", 1.0)) * work["ti_norm"].map(_positive)
        + float(cfg.get("ask_replenish_weight", 1.0)) * work["ask_replenish_norm"].map(_positive)
        + float(cfg.get("best_ask_delta_weight", 0.6)) * work["best_ask_delta_norm"].map(_positive)
        + float(cfg.get("depth_ask_delta_weight", 0.6)) * work["depth_ask_delta_norm"].map(_positive)
        + float(cfg.get("buy_stall_weight", 0.8)) * work["mid_move_norm"].map(_negative_abs)
    )
    sell_score = (
        float(cfg.get("sell_trade_weight", 1.0)) * work["ti_norm"].map(_negative_abs)
        + float(cfg.get("bid_replenish_weight", 1.0)) * work["bid_replenish_norm"].map(_positive)
        + float(cfg.get("best_bid_delta_weight", 0.6)) * work["best_bid_delta_norm"].map(_positive)
        + float(cfg.get("depth_bid_delta_weight", 0.6)) * work["depth_bid_delta_norm"].map(_positive)
        + float(cfg.get("sell_stall_weight", 0.8)) * work["mid_move_norm"].map(_positive)
    )

    out = pd.DataFrame({
        "buy_score": buy_score.astype(float),
        "sell_score": sell_score.astype(float),
    })
    out["absorption_score"] = out[["buy_score", "sell_score"]].max(axis=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Calculate absorption scores for live feature JSONL")
    ap.add_argument("--config", type=Path, default=DEFAULT_CFG_PATH)
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    ap.add_argument("--limit", type=int, default=None, help="Only process the first N data rows")
    args = ap.parse_args()

    cfg = load_absorption_config(args.config)
    rows = _read_jsonl(args.input, limit=args.limit)
    if not rows:
        raise SystemExit(f"No JSONL rows found in {args.input}")

    df = pd.DataFrame(rows)
    scores = compute_scores(df, cfg)
    out_df = pd.concat([df.reset_index(drop=True), scores], axis=1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Write scored output to the specified output path
    with args.output.open("w", encoding="utf-8") as f:
        for row in out_df.to_dict(orient="records"):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    # Also overwrite the original input file so that downstream tools can find the scored data
    with args.input.open("w", encoding="utf-8") as f:
        for row in out_df.to_dict(orient="records"):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(out_df)} scored rows to {args.output} and {args.input}")
    print(f"Wrote {len(out_df)} scored rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
