# vendor/orderflow_pack

canonical の内部 renderer 実装置き場です。旧 `chartProt3_*` renderer と旧 `run_plot*` wrapper は削除済みです。

正規経路:

```text
orderflow/renderer.py
  -> orderflow/current_engine.py
  -> orderflow/engine.py
```

現役モジュール:

- `orderflow/current_engine.py` — stable internal alias
- `orderflow/engine.py` — orchestration
- `orderflow/data.py` — receiver JSONL / OHLCV cache / fallback / sanitize
- `orderflow/chart_config.py` — production-safe constants and Binance OHLCV fetch
- `orderflow/runtime.py` — shared calculations and base plot layers
- `orderflow/absorption.py` — absorption marker logic
- `orderflow/oi.py` — OI processing
- `orderflow/plot.py` — final chart composition

このディレクトリ直下に renderer 起動 script は置きません。shell 入口は repo root の `run_orderflow_once.sh` / `run_orderflow_loop.sh` または `bin/` / `scripts/` を使用します。
