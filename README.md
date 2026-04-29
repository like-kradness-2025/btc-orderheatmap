# BTC Orderheatmap

BTC の orderflow / heatmap 生成専用リポジトリ。

## 現行推奨: v3.29.0

v3.29 は 5S 整理版です。新規運用では、ファイル名にバージョンが入った入口を使わず、固定名入口だけを使います。

```bash
./bin/run_orderflow_once.sh
```

```bash
./bin/run_orderflow_loop.sh
```

## 本番経路

```text
bin/run_orderflow_once.sh
  -> scripts/run_plot.sh
  -> python3 -m orderflow.renderer
  -> artifacts/orderflow_chart_latest.png
```

ループ実行は 15 分ごとに `bin/run_orderflow_once.sh` を呼びます。

```text
bin/run_orderflow_loop.sh
  -> bin/run_orderflow_once.sh
```

## 入力データ

- デフォルト: `data/live`
- 上書き: `BTC_LIVE_DATA_DIR`
- `live_*.jsonl` が空なら失敗します
- `live_features_1s.jsonl` があれば吸収マーカーに使います
- `live_oi.jsonl` があれば OI サブプロットに使います

## 出力

- 本番出力: `artifacts/orderflow_chart_latest.png`
- ログ: `logs/orderflow_once.log` / `logs/orderflow_loop.log`
- lock: `runtime/locks/orderflow_once.lock` / `runtime/locks/orderflow_loop.lock`
- OHLCV cache: `runtime/cache/ohlcv_cache.pkl`

## 設定

- 標準設定: `orderflow/config/absorption_marker_config.json`
- 上書き: `ABSORPTION_CONFIG_PATH`
- Discord channel: `DISCORD_CHANNEL_ID`
- `DISCORD_CHANNEL_ID` が未指定の場合は既存 channel id を fallback として使います

## バージョン方針

- 本番ファイル名には `v327` / `v328` / `v323a` などを入れません
- バージョンは `orderflow/version.py` に一元化します
- 実行ログと CLI 出力で `v3.29.0` を確認します

## 互換入口

以下は互換ラッパーです。新規運用では使わないでください。

- `bin/run_orderflow_once_v327.sh` -> `bin/run_orderflow_once.sh`
- `bin/run_orderflow_loop_v327.sh` -> `bin/run_orderflow_loop.sh`

## legacy / 未整理領域

旧 v 系の描画ファイル、compat 系、TPO/receiver 系の混入物は本番経路から外す対象です。削除ではなく `legacy/` 分離を基本方針とします。

現時点で旧描画エンジンは互換維持のため `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v323a.py` を内部利用しています。ただし新しい外部入口は `python3 -m orderflow.renderer` に固定しています。

## 直接実行例

```bash
scripts/run_plot.sh data/live artifacts/orderflow_chart_latest.png 24 orderflow/config/absorption_marker_config.json
```

```bash
python3 -m orderflow.renderer \
  --hours 24 \
  --data-dir data/live \
  --out artifacts/orderflow_chart_latest.png \
  --absorption-config orderflow/config/absorption_marker_config.json
```
