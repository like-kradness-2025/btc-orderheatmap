# BTC Orderheatmap

BTC の orderflow / heatmap 生成専用リポジトリ。

## 現行推奨: v3.30.0

v3.30 は 5S 整理を進めた役割別分割版です。新規運用では、ファイル名にバージョンが入った入口を使わず、固定名入口だけを使います。

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
- 実行ログと CLI 出力で `v3.30.0` を確認します

## 互換入口

以下は互換ラッパーです。新規運用では使わないでください。

- `bin/run_orderflow_once_v327.sh` -> `bin/run_orderflow_once.sh`
- `bin/run_orderflow_loop_v327.sh` -> `bin/run_orderflow_loop.sh`

## legacy / 未整理領域

旧 v 系の描画ファイル、compat 系、TPO/receiver 系の混入物は本番経路から外す対象です。v3.30 では描画エンジンを以下の役割別モジュールへ分割しました。

```text
vendor/orderflow_pack/orderflow/current_engine.py
  -> engine_v330.py        # 実行制御
  -> runtime_v330.py       # 共通設定・データ helper・基本描画 helper
  -> absorption_v330.py    # 吸収マーカー計算
  -> oi_v330.py            # OI 読み込み・集計・背景バンド
  -> plot_v330.py          # 最終チャート合成
```

旧 `chartProt3_ws_layered_v3.py` / `v322.py` / `v323.py` / `v323a.py` の importlib 連鎖は廃止済みです。

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
