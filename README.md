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

## V3.22 layered renderer

V3.22 は、V3.21 の heatmap 欠損区間対策を維持しつつ、**吸収マーカーの価格アンカーを改善**した版です。

### V3.22 の変更点

- heatmap の欠損区間を明示的に空白として扱う
- one-shot 実行時の表示時間を環境変数で変更できるようにする
- 吸収マーカーは丸 (`o`) のまま維持する
- 取れる場合は best bid / ask や feature 側の価格文脈を優先し、取れない場合だけ bar 側の fallback へ落とす

必要ファイルは次の 6 つです。

- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v3.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_layered_v322.py`
- `vendor/orderflow_pack/orderflow/absorption_marker_config.json`
- `vendor/orderflow_pack/run_plot_v322.sh`
- `bin/run_orderflow_once_v322.sh`
- `bin/run_orderflow_once_v3.sh`

### 実行

```bash
./bin/run_orderflow_once_v322.sh
```

または直接:

```bash
./vendor/orderflow_pack/run_plot_v322.sh ../btc-receiver/data/live ./artifacts/orderflow_chart_v322.png 24 ./vendor/orderflow_pack/orderflow/absorption_marker_config.json
```

### 設定

- `ABSORPTION_CONFIG_PATH` で別設定ファイルを指定できる
- `BTC_LIVE_DATA_DIR` で receiver 側の入力ディレクトリを切り替えできる
- `ORDERHEATMAP_V322_OUT` で出力先を切り替えできる
- `ORDERHEATMAP_V322_HOURS` または `ORDERHEATMAP_V321_HOURS` または `ORDERHEATMAP_V3_HOURS` で表示時間を変更できる
- `plot.marker_price_mode=quote_first` で価格文脈優先
- `plot.marker_price_fallback=bar_extreme_offset|bar_body_edge|bar_body_mid` で fallback を切り替えできる

### V3.22 の狙い

- PNG 後合成をやめる
- 板 heatmap と約定円を維持する
- 吸収マーカーを同じ座標系で直接描く
- 欠損区間を stale な板で埋めて見せない
- マーカー位置を値幅の外に逃がしすぎず、価格文脈に寄せる
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
