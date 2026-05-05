# BTC Orderheatmap

BTC の orderflow / heatmap 生成専用リポジトリです。canonical では、旧 renderer・旧 wrapper・重複 config を削除し、実行経路を一本化しています。

## 現行ランタイム

- 推奨: `canonical`
- ランタイム定義: `orderflow/version.py`
- 本番出力: `artifacts/orderflow_chart_latest.png`
- 既定の描画時間: `24h`
- ルート wrapper / `scripts/run_plot.sh` / `orderflow.renderer` / `engine.py` はすべて 24h を既定にしています。

## 24h 運用の考え方

このリポジトリは、**24h の長めの窓で orderflow / heatmap / OI / absorption をまとめて確認する**前提で運用します。

- 24h を基準にしておくと、吸収マーカーと OI の文脈が追いやすい
- 15 分ループで更新しても、表示窓は 24h のまま安定する
- 必要がある場合だけ `--hours` で短くできますが、通常運用は 24h を推奨します

## 正規実行入口

1 回実行:

```bash
./run_orderflow_once.sh
# または
./bin/run_orderflow_once.sh
```

15 分間隔ループ:

```bash
./run_orderflow_loop.sh
# または
./bin/run_orderflow_loop.sh
```

`run_orderflow_once.sh` / `run_orderflow_loop.sh` は運用向けのルート入口で、即座に `bin/` の正規 wrapper へ `exec` します。旧 renderer へ分岐する経路はありません。

## 本番実行経路

```text
run_orderflow_once.sh
  -> bin/run_orderflow_once.sh
  -> scripts/run_plot.sh
  -> python3 -m orderflow.renderer
  -> orderflow/renderer.py
  -> vendor/orderflow_pack/orderflow/current_engine.py
  -> vendor/orderflow_pack/orderflow/engine.py
  -> vendor/orderflow_pack/orderflow/data.py
  -> vendor/orderflow_pack/orderflow/runtime.py
  -> vendor/orderflow_pack/orderflow/absorption.py
  -> vendor/orderflow_pack/orderflow/oi.py
  -> vendor/orderflow_pack/orderflow/plot.py
  -> artifacts/orderflow_chart_latest.png
```

ループ実行は `bin/run_orderflow_loop.sh` が 900 秒ごとに同じ `bin/run_orderflow_once.sh` を呼びます。

## CLI

```bash
./bin/run_orderflow_once.sh \
  --data-dir data/live \
  --out artifacts/orderflow_chart_latest.png \
  --hours 24 \
  --absorption-config orderflow/config/absorption_marker_config.json \
  --no-discord
```

低レイヤーを直接確認する場合:

```bash
scripts/run_plot.sh data/live artifacts/orderflow_chart_latest.png 24 orderflow/config/absorption_marker_config.json
```

```bash
python3 -m orderflow.renderer \
  --hours 24 \
  --data-dir data/live \
  --out artifacts/orderflow_chart_latest.png \
  --ohlcv-cache runtime/cache/ohlcv_cache.pkl \
  --absorption-config orderflow/config/absorption_marker_config.json \
  --discord-channel-id ''
```

`current_engine.py` も直接実行できます。

```bash
python3 vendor/orderflow_pack/orderflow/current_engine.py --hours 24 --data-dir data/live --out artifacts/current_engine_test.png --discord-channel-id ''
```

## 入力データ

- デフォルト: `data/live`
- 上書き: `BTC_LIVE_DATA_DIR` または `--data-dir`
- 対応ファイル:
  - `live_book.jsonl`
  - `live_book_raw.jsonl`
  - `live_book_bucketed.jsonl`
  - `live_trades.jsonl`
  - `live_trades_compact.jsonl`
  - `live_features_1s.jsonl`
  - `live_oi.jsonl`
- `live_features_1s.jsonl` があれば吸収マーカーに使います。
- `live_oi.jsonl` があれば OI サブプロットに使います。
- OHLCV は cache を読み、Binance API の差分をマージして 1 つの cache に更新します。API が使えない場合のみ local trades から算出します。

### ローカル Receiver を使う場合

ホーム側の Receiver データを使うなら、`data/live` に置くか、`BTC_LIVE_DATA_DIR` で明示します。

```bash
export BTC_LIVE_DATA_DIR=/home/weed420/btc-receiver/data/live
./bin/run_orderflow_once.sh --no-discord
```

確認ポイント:

- `data/live/live_book.jsonl` が更新されていること
- `data/live/live_trades*.jsonl` が更新されていること
- `logs/orderflow_once.log` に `runtime=canonical` と `hours=24` が出ること
- `ohlcv_source=cache+binance_api` または `ohlcv_source=local_trades` が出ること

## 出力・実行状態

- 画像: `artifacts/orderflow_chart_latest.png`
- 1 回実行ログ: `logs/orderflow_once.log`
- ループ実行ログ: `logs/orderflow_loop.log`
- 起動ログ: `logs/plot.log`
- lock: `runtime/locks/orderflow_once.lock` / `runtime/locks/orderflow_loop.lock`
- OHLCV cache: `runtime/cache/ohlcv_cache.pkl`

## フォルダ構造

```text
btc-orderheatmap/
├── run_orderflow_once.sh          # ルート入口。bin/run_orderflow_once.sh へ exec
├── run_orderflow_loop.sh          # ルート入口。bin/run_orderflow_loop.sh へ exec
├── bin/
│   ├── run_orderflow_once.sh      # 本番 1 回実行 wrapper
│   ├── run_orderflow_loop.sh      # 本番 15 分ループ wrapper
│   ├── start_plot.sh              # loop を nohup 起動
│   └── report_runtime_status.sh   # 運用状態レポート
├── scripts/
│   └── run_plot.sh                # renderer CLI 呼び出し wrapper
├── orderflow/
│   ├── renderer.py                # stable public CLI
│   ├── version.py
│   └── config/
│       └── absorption_marker_config.json
├── vendor/orderflow_pack/orderflow/
│   ├── current_engine.py          # stable internal alias
│   ├── engine.py             # orchestration
│   ├── data.py               # JSONL / OHLCV / cache / fallback
│   ├── chart_config.py       # production-safe constants + Binance OHLCV fetch
│   ├── runtime.py            # shared calculations and base plot layers
│   ├── absorption.py         # absorption marker scoring / sizing / positioning
│   ├── oi.py                 # OI loading and subplot rendering
│   └── plot.py               # final layout and PNG composition
├── lib/
│   └── discord_uploader.py
├── data/live/
├── artifacts/
├── logs/
└── runtime/
    ├── cache/
    └── locks/
```

## 削除済みの旧経路

以下は canonical の正規経路から完全に外し、リポジトリから削除済みです。

- root の旧 `chartProt3_*` ファイル
- `vendor/orderflow_pack/chartProt3_orig.py`
- `vendor/orderflow_pack/orderflow/chartProt3_ws_compat.py`
- `vendor/orderflow_pack/run_plot.sh`
- `vendor/orderflow_pack/run_plot_v2.sh`
- `vendor/orderflow_pack/run_plot.ps1`
- `bin/run_orderflow_once_v2.sh`
- `bin/run_orderflow_once_v323a.sh`
- `bin/run_orderflow_loop_v323a.sh`
- `bin/run_orderflow_loop_v327.sh`
- `bin/send_orderflow.sh`
- `vendor/orderflow_pack/orderflow/absorption_marker_config.json`
- `legacy/` の旧経路メモ

## 役割別モジュール

| モジュール | 責務 |
|---|---|
| `engine.py` | データ取得順序、集計、描画、Discord upload の全体制御 |
| `data.py` | receiver JSONL 読み込み、trade 集計、OHLCV cache merge、local trades fallback、OHLCV sanitize |
| `chart_config.py` | 描画定数と Binance OHLCV API fetch。import 時のログ/ファイル副作用なし |
| `runtime.py` | 価格範囲、時間窓、heatmap/candle/VWAP/orderbook bar の基本描画 helper |
| `absorption.py` | 吸収マーカーのスコア計算・位置決定・サイズ計算 |
| `oi.py` | OI JSONL 読み込み・OHLC 化・背景バンド描画 |
| `plot.py` | GridSpec、凡例、タイトル、最終 PNG 合成 |

## 設定

- 吸収マーカー設定: `orderflow/config/absorption_marker_config.json`
- 上書き: `ABSORPTION_CONFIG_PATH` または `--absorption-config`
- Discord channel: `DISCORD_CHANNEL_ID` または `--discord-channel-id`
- Discord 送信なし: `--no-discord` または `--discord-channel-id ''`
- ループ間隔: `ORDERFLOW_LOOP_INTERVAL_SEC`（デフォルト 900）
- 描画時間: `ORDERFLOW_HOURS` または `--hours`

## 吸収マーカー設定 canonical

- 形状: `buy_marker: o` / `sell_marker: o`
- サイズ: スコアに応じた連続変化
- オフセット: `marker_offset_bps: 50.0`
- 計算方式: 板価格 × `(1 ± offset_bps / 10000)`

## 解像度設定

- `runtime.py` の `SAVEFIG_DPI_OVERRIDE` を使用
- canonical の現行値: `500`
- `figsize` / GridSpec / アスペクト比は、明示的なレイアウト変更方針なしに変更しません。

## 検証コマンド

```bash
git status --short --branch
python3 -m compileall -q orderflow vendor/orderflow_pack/orderflow lib
python3 -m orderflow.renderer --data-dir /tmp/btc-empty-live --out artifacts/review_test.png --ohlcv-cache runtime/cache/review_ohlcv.pkl --hours 1 --absorption-config orderflow/config/absorption_marker_config.json --discord-channel-id ''
./bin/run_orderflow_once.sh --data-dir /tmp/btc-empty-live --out artifacts/wrapper_test.png --hours 1 --no-discord
python3 vendor/orderflow_pack/orderflow/current_engine.py --data-dir /tmp/btc-empty-live --out artifacts/current_engine_direct.png --ohlcv-cache runtime/cache/current_engine_direct.pkl --hours 24 --absorption-config orderflow/config/absorption_marker_config.json --discord-channel-id ''
```

実データを使う確認をしたい場合:

```bash
BTC_LIVE_DATA_DIR=/home/weed420/btc-receiver/data/live ./bin/run_orderflow_once.sh --no-discord
tail -50 logs/orderflow_once.log
```

## トラブルシューティング

### 生成失敗

```bash
tail -50 logs/orderflow_once.log
python3 -m compileall -q orderflow vendor/orderflow_pack/orderflow lib
```

### 画像が生成されるが live 情報が薄い

- `data/live/live_book*.jsonl` と `data/live/live_trades*.jsonl` の更新を確認
- OHLCV だけなら Binance API fallback で描画できますが、板・約定・吸収マーカーは receiver データに依存します。

### Discord 送信失敗

- `DISCORD_CHANNEL_ID` が正しいか確認
- Bot の Attachments 権限を確認
- ファイルサイズが 10MB を超えていないか確認

## GitHub

https://github.com/like-kradness-2025/btc-orderheatmap
