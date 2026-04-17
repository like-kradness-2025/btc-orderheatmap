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
