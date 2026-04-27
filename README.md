# BTC Orderheatmap

BTC の orderflow / heatmap 生成専用。

## 現行推奨: v3.27 layered

- `bin/run_orderflow_once_v327.sh` で v3.27 を 1 回生成してアップロードする
- `bin/run_orderflow_loop_v327.sh` で v3.27 を 15 分間隔で定期実行する
- `vendor/orderflow_pack/run_plot_v327.sh` で v3.27 を直接実行できる
- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v327.py` が正式な Python entrypoint
- `artifacts/orderflow_chart_v327.png` が v3.27 の主な出力
- `logs/orderflow_once_v327.log` / `logs/orderflow_loop_v327.log` で運用確認する

v3.27 は orderbook heatmap / trade circles / absorption markers / OI subplot / price-direction background bands を統合した layered chart です。

## 入力データ

- デフォルトでは `data/live` を読む
- `BTC_LIVE_DATA_DIR` を明示するとその場所を固定で使う
- `live_*.jsonl` が空なら失敗する
- `live_features_1s.jsonl` があれば吸収マーカーに使う
- `live_oi.jsonl` があれば OI サブプロットに使う

## 吸収マーカー設定

- `vendor/orderflow_pack/orderflow/absorption_marker_config.json` で吸収判定しきい値やマーカーサイズを調整できる
- `ABSORPTION_CONFIG_PATH` を指定すると別設定ファイルを使える

## 旧バージョン / 互換入口

- `bin/run_orderflow_once.sh`
- `bin/run_orderflow_loop.sh`
- `bin/start_plot.sh`
- `bin/run_orderflow_once_v2.sh`
- `vendor/orderflow_pack/run_plot_v2.sh`
- `bin/run_orderflow_once_v323a.sh`
- `bin/run_orderflow_loop_v323a.sh`
- `vendor/orderflow_pack/run_plot_v323a.sh`

`v323a` 名の入口は互換用です。実体は v3.27 系なので、新規運用では `v327` 名を使ってください。

## orderheatmap 主責務外の互換ファイル

- `bin/start_receiver.sh`
- `bin/ensure_receiver.sh`
- `bin/monitor_receiver.sh`
- `bin/run_tpo*.sh`
- `bin/send_tpo*.sh`
- `artifacts/examples/tpo*.png`
- `artifacts/output/tpo_chart.png`

上の項目は旧統合版から混ざっているもので、orderheatmap の主責務ではありません。

## 起動例

```bash
./bin/run_orderflow_once_v327.sh
```

```bash
./bin/run_orderflow_loop_v327.sh
```

```bash
vendor/orderflow_pack/run_plot_v327.sh data/live artifacts/orderflow_chart_v327.png 24
```
