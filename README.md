# BTC Orderheatmap

BTC の orderflow / heatmap 生成専用。

## いまの役割

- `bin/run_orderflow_once.sh` で 1 回生成してアップロードする
- `bin/run_orderflow_loop.sh` で定期実行する
- `bin/start_plot.sh` で手動バックグラウンド実行する
- `bin/discord_webhook_setup.sh` で `webhook/Orderheatmap` を作成・再設定する
- `../btc-receiver/data/live` を正規入力として読む。ここが空なら失敗する
- `BTC_LIVE_DATA_DIR` を明示するとその場所を固定で使う
- `artifacts/orderflow_chart.png` が主な出力
- `logs/orderflow_once.log` / `logs/orderflow_loop.log` で運用確認する

## V3 layered renderer

V3 は、板 heatmap・ローソク足・約定円・右の板バー・吸収マーカーを**同一座標系で 1 回描画**する最小構成です。

必要ファイルは次の 4 つです。

- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v3.py`
- `vendor/orderflow_pack/orderflow/absorption_marker_config.json`
- `vendor/orderflow_pack/run_plot_v3.sh`
- `bin/run_orderflow_once_v3.sh`

### 実行

```bash
./bin/run_orderflow_once_v3.sh
```

または直接:

```bash
./vendor/orderflow_pack/run_plot_v3.sh ../btc-receiver/data/live ./artifacts/orderflow_chart_v3.png 24 ./vendor/orderflow_pack/orderflow/absorption_marker_config.json
```

### 設定

- `ABSORPTION_CONFIG_PATH` で別設定ファイルを指定できる
- `BTC_LIVE_DATA_DIR` で receiver 側の入力ディレクトリを切り替えできる
- `ORDERHEATMAP_V3_OUT` で出力先を切り替えできる

### V3 の狙い

- PNG 後合成をやめる
- 板 heatmap と約定円を維持する
- 吸収マーカーを同じ座標系で直接描く
- 実データに合わせて閾値だけ後から調整できるようにする

## 互換用に残してあるもの

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
./bin/run_orderflow_once.sh
```
