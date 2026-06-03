"""Data loading, JSONL parsing, OHLCV fallback, and sanitization for canonical.

This module is the only data-adapter layer used by the canonical renderer. It
replaces the old runtime dependency while preserving the
receiver JSONL formats currently produced by btc-receiver.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BOOK_RECENT_CHUNK_BYTES = 32 * 1024 * 1024
BOOK_RECENT_MAX_BYTES = 512 * 1024 * 1024
TRADE_RECENT_CHUNK_BYTES = 64 * 1024 * 1024
TRADE_RECENT_MAX_BYTES = 512 * 1024 * 1024
TRADE_AGGREGATION_RESOLUTION = "1min"
TRADE_PRICE_BUCKET_USD = 10.0
DATA_FRESHNESS_SEC = 300


def check_data_freshness(
    df_index: pd.Index, label: str, max_age_sec: int = DATA_FRESHNESS_SEC
) -> bool:
    """Check the most recent timestamp in a DatetimeIndex against now.

    Returns True if fresh (age <= max_age_sec) or index is empty.
    Prints a WARN line when stale — does NOT raise.
    """
    if df_index.empty:
        return True
    now = pd.Timestamp.now(tz="UTC")
    last_update = df_index.max()
    age_sec = int((now - last_update).total_seconds())
    if age_sec > max_age_sec:
        print(
            f"WARN data.freshness: {label} last_update={last_update} "
            f"age={age_sec}s > {max_age_sec}s"
        )
        return False
    return True


def resolve_inputs(data_dir: Path) -> dict[str, Path]:
    data_dir = Path(data_dir)
    return {
        "book_jsonl": data_dir / "live_book.jsonl",
        "book_raw_jsonl": data_dir / "live_book_raw.jsonl",
        "book_bucket_jsonl": data_dir / "live_book_bucketed.jsonl",
        "trade_jsonl": data_dir / "live_trades.jsonl",
        "trade_compact_jsonl": data_dir / "live_trades_compact.jsonl",
        "feature_jsonl": data_dir / "live_features_1s.jsonl",
        "oi_jsonl": data_dir / "live_oi.jsonl",
    }


def read_jsonl_recent_until(path: Path, start_ts: pd.Timestamp | None, chunk_bytes: int, max_bytes: int) -> list[dict[str, Any]]:
    """Read recent JSONL rows from the tail of a possibly large receiver file."""
    path = Path(path)
    rows: list[dict[str, Any]] = []
    if not path.exists() or path.stat().st_size == 0:
        return rows

    try:
        size = path.stat().st_size
        read_bytes = 0
        with path.open("rb") as f:
            pos = size
            carry = b""
            while pos > 0 and read_bytes < max_bytes:
                chunk_size = min(chunk_bytes, pos)
                pos -= chunk_size
                f.seek(pos)
                chunk = f.read(chunk_size)
                read_bytes += chunk_size

                data = chunk + carry
                lines = data.splitlines()
                if pos > 0 and lines:
                    carry = lines.pop(0)
                else:
                    carry = b""

                parsed_rows: list[dict[str, Any]] = []
                for ln in lines:
                    if not ln.strip():
                        continue
                    try:
                        parsed = json.loads(ln.decode("utf-8", errors="ignore"))
                        if isinstance(parsed, dict):
                            parsed_rows.append(parsed)
                    except Exception:
                        continue

                if parsed_rows:
                    rows = parsed_rows + rows
                    if start_ts is not None:
                        oldest_ts = pd.to_datetime(parsed_rows[0].get("ts"), utc=True, errors="coerce")
                        if pd.notna(oldest_ts) and oldest_ts <= start_ts:
                            break

            if carry.strip():
                try:
                    parsed = json.loads(carry.decode("utf-8", errors="ignore"))
                    if isinstance(parsed, dict):
                        rows.insert(0, parsed)
                except Exception:
                    pass
    except Exception as exc:
        print(f"WARN data.read_jsonl_recent_until path={path} error={exc}")

    return rows


def load_ohlcv_cache(path: Path | None, ttl_sec: int | None = None) -> pd.DataFrame | None:
    if path is None:
        return None
    path = Path(path)
    if not path.exists():
        return None
    try:
        if ttl_sec is not None and time.time() - path.stat().st_mtime > ttl_sec:
            return None
        df = pd.read_pickle(path)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return sanitize_ohlcv(df)
    except Exception as exc:
        print(f"WARN data.load_ohlcv_cache path={path} error={exc}")
    return None


def save_ohlcv_cache(path: Path | None, df: pd.DataFrame) -> None:
    if path is None or df is None or df.empty:
        return
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        sanitize_ohlcv(df).to_pickle(path)
    except Exception as exc:
        print(f"WARN data.save_ohlcv_cache path={path} error={exc}")


def merge_ohlcv_frames(*frames: pd.DataFrame | None) -> pd.DataFrame:
    """Merge OHLCV frames, keeping the latest row for duplicate candle timestamps."""
    clean_frames = [sanitize_ohlcv(df) for df in frames if df is not None and not df.empty]
    clean_frames = [df for df in clean_frames if not df.empty]
    if not clean_frames:
        return pd.DataFrame()
    merged = pd.concat(clean_frames, axis=0)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    return sanitize_ohlcv(merged)


def _list_to_float_dict(v: Any) -> dict[float, float]:
    if not isinstance(v, list):
        return {}
    out: dict[float, float] = {}
    for item in v:
        try:
            p, q = item[0], item[1]
            pf, qf = float(p), float(q)
            if np.isfinite(pf) and np.isfinite(qf) and qf > 0:
                out[pf] = qf
        except Exception:
            continue
    return out


def _dict_to_float_dict(v: Any) -> dict[float, float]:
    if not isinstance(v, dict):
        return {}
    out: dict[float, float] = {}
    for p, q in v.items():
        try:
            pf, qf = float(p), float(q)
            if np.isfinite(pf) and np.isfinite(qf) and qf > 0:
                out[pf] = qf
        except Exception:
            continue
    return out


def load_book_data_with_stats_ws(market: str, hours: int, inputs: dict[str, Path]) -> pd.DataFrame:
    if market != "Futures":
        return pd.DataFrame()

    book_jsonl = inputs["book_jsonl"]
    book_raw_jsonl = inputs["book_raw_jsonl"]
    book_bucket_jsonl = inputs["book_bucket_jsonl"]
    src = book_bucket_jsonl if book_bucket_jsonl.exists() else (book_jsonl if book_jsonl.exists() else book_raw_jsonl)

    start_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours) if hours and hours > 0 else None
    rows = read_jsonl_recent_until(src, start_ts, BOOK_RECENT_CHUNK_BYTES, BOOK_RECENT_MAX_BYTES)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if "ts" not in df.columns:
        return pd.DataFrame()
    df["timestamp"] = pd.to_datetime(df["ts"], utc=True, errors="coerce", format="mixed")
    df.dropna(subset=["timestamp"], inplace=True)
    if df.empty:
        return pd.DataFrame()

    if hours and hours > 0:
        end_ts = df["timestamp"].max()
        df = df[df["timestamp"] >= end_ts - pd.Timedelta(hours=hours)]

    out = pd.DataFrame(index=df["timestamp"])
    out["mid_price"] = pd.to_numeric(df.get("mid", np.nan), errors="coerce").to_numpy()

    if "bids_bucketed" in df.columns and "asks_bucketed" in df.columns:
        out["bids_json"] = df["bids_bucketed"].apply(_dict_to_float_dict).to_numpy()
        out["asks_json"] = df["asks_bucketed"].apply(_dict_to_float_dict).to_numpy()
    else:
        fallback = pd.Series([[]] * len(df), index=df.index)
        out["bids_json"] = df.get("bids", fallback).apply(_list_to_float_dict).to_numpy()
        out["asks_json"] = df.get("asks", fallback).apply(_list_to_float_dict).to_numpy()

    is_bucket_src = src == book_bucket_jsonl

    def sanitize_book_levels(row: pd.Series) -> pd.Series:
        mid = row.get("mid_price", np.nan)
        bids = row.get("bids_json", {}) if isinstance(row.get("bids_json", {}), dict) else {}
        asks = row.get("asks_json", {}) if isinstance(row.get("asks_json", {}), dict) else {}
        if np.isfinite(mid):
            guard = 5.0 if is_bucket_src else 0.0
            bids = {p: q for p, q in bids.items() if p <= mid - guard}
            asks = {p: q for p, q in asks.items() if p >= mid + guard}
        return pd.Series({"bids_json": bids, "asks_json": asks})

    out[["bids_json", "asks_json"]] = out.apply(sanitize_book_levels, axis=1)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    check_data_freshness(out.index, "book", DATA_FRESHNESS_SEC)
    return out


def _plot_weight(sum_qty: pd.Series, max_qty: pd.Series, trade_count: pd.Series) -> pd.Series:
    cluster_boost = 1.0 + 0.35 * np.log1p(np.clip(trade_count - 1.0, 0.0, None))
    return np.sqrt(np.maximum(sum_qty, 0.0) * np.maximum(max_qty, 0.0)) * cluster_boost


def _finalize_aggregated_trade_frame(out: pd.DataFrame) -> pd.DataFrame:
    out = out.replace([np.inf, -np.inf], np.nan)
    fill_cols = [
        "buy_sum_quantity", "sell_sum_quantity", "buy_max_quantity", "sell_max_quantity",
        "buy_trade_count", "sell_trade_count",
    ]
    out[fill_cols] = out[fill_cols].fillna(0.0)
    out["buy_quantity"] = _plot_weight(out["buy_sum_quantity"], out["buy_max_quantity"], out["buy_trade_count"])
    out["sell_quantity"] = _plot_weight(out["sell_sum_quantity"], out["sell_max_quantity"], out["sell_trade_count"])
    out["close_price"] = out["vwap_price"].fillna(out["close_price"])
    out.index = pd.to_datetime(out.index, utc=True)
    return out.sort_index()


def load_aggregated_trade_data_ws(market: str, hours: int, inputs: dict[str, Path]) -> pd.DataFrame:
    if market != "Futures":
        return pd.DataFrame()

    start_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours) if hours and hours > 0 else None
    compact_path = inputs.get("trade_compact_jsonl")
    if compact_path and compact_path.exists():
        rows = read_jsonl_recent_until(compact_path, start_ts, TRADE_RECENT_CHUNK_BYTES, TRADE_RECENT_MAX_BYTES)
        compact_df = _aggregate_compact_trades(rows, hours)
        if not compact_df.empty:
            check_data_freshness(compact_df.index, "agg", DATA_FRESHNESS_SEC)
            return compact_df

    rows = read_jsonl_recent_until(inputs["trade_jsonl"], start_ts, TRADE_RECENT_CHUNK_BYTES, TRADE_RECENT_MAX_BYTES)
    if not rows:
        return pd.DataFrame()
    result = _aggregate_raw_trades(rows, hours)
    if not result.empty:
        check_data_freshness(result.index, "agg", DATA_FRESHNESS_SEC)
    return result


def _aggregate_compact_trades(rows: list[dict[str, Any]], hours: int) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "ts" not in df.columns:
        return pd.DataFrame()
    df["timestamp"] = pd.to_datetime(df["ts"], utc=True, errors="coerce", format="mixed")
    df.dropna(subset=["timestamp"], inplace=True)
    if df.empty:
        return pd.DataFrame()
    if hours and hours > 0:
        end_ts = df["timestamp"].max()
        df = df[df["timestamp"] >= end_ts - pd.Timedelta(hours=hours)]

    for col in ["price_bucket", "qty_sum", "notional_sum", "trade_count", "max_qty", "vwap_price", "high_price", "low_price"]:
        df[col] = pd.to_numeric(df.get(col, np.nan), errors="coerce")
    side_series = df["side"] if "side" in df.columns else pd.Series("unknown", index=df.index)
    df["side"] = side_series.astype(str).str.lower()
    df.dropna(subset=["price_bucket", "qty_sum", "trade_count"], inplace=True)
    if df.empty:
        return pd.DataFrame()

    grp = df.groupby("timestamp", sort=True)
    out = pd.DataFrame(index=sorted(df["timestamp"].unique()))
    out["open_price"] = grp["vwap_price"].first()
    out["high_price"] = grp["high_price"].max()
    out["low_price"] = grp["low_price"].min()
    out["close_price"] = grp["vwap_price"].last()
    out["vwap_price"] = grp["notional_sum"].sum() / grp["qty_sum"].sum()
    out["total_quantity"] = grp["qty_sum"].sum()
    out["max_trade_quantity"] = grp["max_qty"].max()
    out["number_of_trades"] = grp["trade_count"].sum().astype(float)
    out["buy_sum_quantity"] = grp.apply(lambda g: g.loc[g["side"] == "buy", "qty_sum"].sum())
    out["sell_sum_quantity"] = grp.apply(lambda g: g.loc[g["side"] == "sell", "qty_sum"].sum())
    out["buy_max_quantity"] = grp.apply(lambda g: g.loc[g["side"] == "buy", "max_qty"].max())
    out["sell_max_quantity"] = grp.apply(lambda g: g.loc[g["side"] == "sell", "max_qty"].max())
    out["buy_trade_count"] = grp.apply(lambda g: float(g.loc[g["side"] == "buy", "trade_count"].sum()))
    out["sell_trade_count"] = grp.apply(lambda g: float(g.loc[g["side"] == "sell", "trade_count"].sum()))

    bucket_rows = []
    for ts, g in grp:
        bucket_rows.append((ts, g[["side", "price_bucket", "qty_sum", "max_qty", "trade_count", "vwap_price", "high_price", "low_price"]].rename(columns={"max_qty": "qty_max"}).to_dict("records")))
    out["price_bucket_rows"] = pd.Series(index=out.index, dtype=object)
    for ts, rows_at_ts in bucket_rows:
        out.at[ts, "price_bucket_rows"] = rows_at_ts
    out["price_bucket_rows"] = out["price_bucket_rows"].apply(lambda v: v if isinstance(v, list) else [])
    return _finalize_aggregated_trade_frame(out)


def _aggregate_raw_trades(rows: list[dict[str, Any]], hours: int) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "ts" not in df.columns:
        return pd.DataFrame()
    df["timestamp"] = pd.to_datetime(df["ts"], utc=True, errors="coerce", format="mixed")
    df.dropna(subset=["timestamp"], inplace=True)
    if df.empty:
        return pd.DataFrame()
    if hours and hours > 0:
        end_ts = df["timestamp"].max()
        df = df[df["timestamp"] >= end_ts - pd.Timedelta(hours=hours)]

    df["price"] = pd.to_numeric(df.get("price", np.nan), errors="coerce")
    df["qty"] = pd.to_numeric(df.get("qty", np.nan), errors="coerce")
    df["notional"] = pd.to_numeric(df.get("notional", np.nan), errors="coerce")
    side_series = df["side"] if "side" in df.columns else pd.Series("unknown", index=df.index)
    df["side"] = side_series.astype(str).str.lower()
    df.dropna(subset=["price", "qty"], inplace=True)
    if df.empty:
        return pd.DataFrame()
    df["notional"] = df["notional"].where(np.isfinite(df["notional"]), df["price"] * df["qty"])
    df["bucket_price"] = (np.round(df["price"] / TRADE_PRICE_BUCKET_USD) * TRADE_PRICE_BUCKET_USD).astype(float)
    df["ts_min"] = df["timestamp"].dt.floor(TRADE_AGGREGATION_RESOLUTION)

    grp = df.groupby("ts_min", sort=True)
    out = pd.DataFrame({
        "open_price": grp["price"].first(),
        "high_price": grp["price"].max(),
        "low_price": grp["price"].min(),
        "close_price": grp["price"].last(),
        "vwap_price": grp["notional"].sum() / grp["qty"].sum(),
        "total_quantity": grp["qty"].sum(),
        "max_trade_quantity": grp["qty"].max(),
        "number_of_trades": grp.size().astype(float),
        "buy_sum_quantity": grp.apply(lambda g: g.loc[g["side"] == "buy", "qty"].sum()),
        "sell_sum_quantity": grp.apply(lambda g: g.loc[g["side"] == "sell", "qty"].sum()),
        "buy_max_quantity": grp.apply(lambda g: g.loc[g["side"] == "buy", "qty"].max()),
        "sell_max_quantity": grp.apply(lambda g: g.loc[g["side"] == "sell", "qty"].max()),
        "buy_trade_count": grp.apply(lambda g: float((g["side"] == "buy").sum())),
        "sell_trade_count": grp.apply(lambda g: float((g["side"] == "sell").sum())),
    })

    bucket_rows = []
    bucket_grp = df.groupby(["ts_min", "side", "bucket_price"], sort=True)
    for (ts_min, side, bucket_price), g in bucket_grp:
        qty_sum = float(g["qty"].sum())
        bucket_rows.append({
            "timestamp": ts_min,
            "side": side,
            "price_bucket": float(bucket_price),
            "qty_sum": qty_sum,
            "qty_max": float(g["qty"].max()),
            "trade_count": int(len(g)),
            "vwap_price": float(g["notional"].sum() / qty_sum) if qty_sum > 0 else np.nan,
            "high_price": float(g["price"].max()),
            "low_price": float(g["price"].min()),
        })
    out["price_bucket_rows"] = pd.Series(index=out.index, dtype=object)
    if bucket_rows:
        bucket_df = pd.DataFrame(bucket_rows)
        bucket_map = bucket_df.groupby("timestamp").apply(lambda g: g.to_dict("records"))
        out.loc[bucket_map.index, "price_bucket_rows"] = bucket_map
    out["price_bucket_rows"] = out["price_bucket_rows"].apply(lambda v: v if isinstance(v, list) else [])
    return _finalize_aggregated_trade_frame(out)


def generate_ohlcv_from_trades(inputs: dict[str, Path], hours: int, interval: str = "5min") -> pd.DataFrame:
    """Generate OHLCV from receiver trade JSONL, preferring compact trades."""
    agg = load_aggregated_trade_data_ws("Futures", hours, inputs)
    if agg.empty:
        return pd.DataFrame()

    work = agg.copy()
    work.index = pd.to_datetime(work.index, utc=True, errors="coerce")
    work = work[work.index.notna()].sort_index()
    if work.empty:
        return pd.DataFrame()

    # Remove invalid zero lows/highs from compact receiver data before resampling.
    for col in ["open_price", "high_price", "low_price", "close_price", "vwap_price", "total_quantity"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    work["high_clean"] = work["high_price"].where(work["high_price"] > 0)
    work["low_clean"] = work["low_price"].where(work["low_price"] > 0)
    work["price"] = work["close_price"].fillna(work["vwap_price"])
    work = work.dropna(subset=["price"])
    if work.empty:
        return pd.DataFrame()

    ohlcv = work.resample(interval).agg(
        open=("price", "first"),
        high=("high_clean", "max"),
        low=("low_clean", "min"),
        close=("price", "last"),
        volume=("total_quantity", "sum"),
    )
    ohlcv = sanitize_ohlcv(ohlcv)
    return ohlcv


def sanitize_ohlcv(ohlcv_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize OHLCV dtypes and repair impossible high/low/open values."""
    if ohlcv_df is None or ohlcv_df.empty:
        return pd.DataFrame()
    required = ["open", "high", "low", "close"]
    if not all(col in ohlcv_df.columns for col in required):
        return pd.DataFrame()

    df = ohlcv_df.copy()
    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    df = df[df.index.notna()].sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

    df = df.replace([np.inf, -np.inf], np.nan)
    # Treat non-positive prices as missing, then repair from neighboring/valid
    # prices. This avoids zero lows from compact receiver data collapsing the
    # y-axis while preserving rows that still have a valid close.
    for col in required:
        df.loc[df[col] <= 0, col] = np.nan

    df["close"] = df["close"].ffill().bfill()
    df["open"] = df["open"].fillna(df["close"].shift(1)).fillna(df["close"])
    df["high"] = df["high"].fillna(df[["open", "close"]].max(axis=1))
    df["low"] = df["low"].fillna(df[["open", "close"]].min(axis=1))
    df = df.dropna(subset=required)
    if df.empty:
        return pd.DataFrame()

    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df["volume"] = df["volume"].fillna(0.0).clip(lower=0.0)
    return df[["open", "high", "low", "close", "volume"] + [c for c in df.columns if c not in {"open", "high", "low", "close", "volume"}]]
