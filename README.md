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

## フォルダ構造

```text
btc-orderheatmap/
├── bin/                          # 本番実行スクリプト
│   ├── run_orderflow_once.sh     # 1 回実行（本番推奨）
│   ├── run_orderflow_loop.sh     # 15 分間隔定期実行（本番推奨）
│   ├── run_orderflow_once_v327.sh  # 互換ラッパー（非推奨）
│   ├── run_orderflow_loop_v327.sh  # 互換ラッパー（非推奨）
│   ├── send_orderflow.sh         # Discord 送信用
│   ├── discord_*.sh              # Discord 関連ユーティリティ
│   └── ...
├── scripts/
│   └── run_plot.sh               # 描画実行ラッパー
├── lib/
│   └── discord_uploader.py       # Discord ファイル送信モジュール
├── orderflow/                    # 本番エントリーポイント
│   ├── __init__.py
│   ├── renderer.py               # 本番エントリー（CLI）
│   ├── version.py                # バージョン定義
│   └── config/
│       └── absorption_marker_config.json  # 吸収マーカー設定
├── vendor/
│   ├── orderflow_pack/
│   │   ├── chartProt3_orig.py    # 元描画ライブラリ
│   │   └── orderflow/
│   │       ├── current_engine.py # v3.30 エントリー（エイリアス）
│   │       ├── engine_v330.py    # 実行制御
│   │       ├── runtime_v330.py   # 共通設定・データ処理・描画 helper
│   │       ├── absorption_v330.py # 吸収マーカー計算
│   │       ├── oi_v330.py        # OI データ処理・描画
│   │       ├── plot_v330.py      # 最終チャート合成
│   │       ├── chartProt3_ws_compat.py # 互換モジュール（使用中）
│   │       └── absorption_marker_config.json # 設定コピー
│   └── ...
├── data/
│   └── live/                     # 入力データ（live_*.jsonl）
├── artifacts/
│   └── orderflow_chart_latest.png # 本番出力画像
├── logs/
│   ├── orderflow_once.log
│   └── orderflow_loop.log
├── runtime/
│   ├── cache/
│   │   └── ohlcv_cache.pkl
│   └── locks/
│       ├── orderflow_once.lock
│       └── orderflow_loop.lock
├── legacy/                       # 旧バージョン関連（参照のみ）
├── README.md
└── orderflow/version.py          # バージョン定義（v3.30.0）
```

### 本番実行パス（推奨）
```text
bin/run_orderflow_once.sh
  -> scripts/run_plot.sh
  -> python3 -m orderflow.renderer
  -> vendor/orderflow_pack/orderflow/current_engine.py
  -> engine_v330.py
  -> runtime_v330.py / absorption_v330.py / oi_v330.py / plot_v330.py
  -> artifacts/orderflow_chart_latest.png
```

### 役割別モジュール（v3.30）
| モジュール | 責務 |
|-----------|------|
| `engine_v330.py` | データ読み込み・集計・全体フロー制御 |
| `runtime_v330.py` | 共通設定・価格関数・基本描画 helper（ヒートマップ・ローソク・VWAP など） |
| `absorption_v330.py` | 吸収マーカーのスコア計算・位置決定・サイズ計算 |
| `oi_v330.py` | OI データ読み込み・ローソク描画・背景バンド描画 |
| `plot_v330.py` | レイアウト設定・凡例描画・最終 PNG 出力 |

### 互換ラッパー（非推奨）
- `bin/run_orderflow_once_v327.sh` → `bin/run_orderflow_once.sh`
- `bin/run_orderflow_loop_v327.sh` → `bin/run_orderflow_loop.sh`
- `bin/run_orderflow_once_v323a.sh` → `bin/run_orderflow_once.sh`
- `bin/run_orderflow_loop_v323a.sh` → `bin/run_orderflow_loop.sh`

旧 `chartProt3_ws_layered_v3.py` / `v322.py` / `v323.py` / `v323a.py` の 5 層 importlib 連鎖は廃止済みです。

## 設定ファイル

- 標準設定: `orderflow/config/absorption_marker_config.json`
- 上書き: `ABSORPTION_CONFIG_PATH`
- Discord channel: `DISCORD_CHANNEL_ID`
- `DISCORD_CHANNEL_ID` が未指定の場合は既存 channel id を fallback として使います

## 吸収マーカー設定 (v3.30)

### マーカー表示
- **形状**: `buy_marker`: `o`、`sell_marker`: `o`（丸）
- **サイズ**: スコアに応じて連続変化（最小 80、最大 600）
- **スコア範囲**: 1.75（最小）〜 3.6（最大）

### マーカーオフセット
- **計算方式**: bps ベース（ベース価格 × (1 ± offset_bps/10000)）
- **設定**: `marker_offset_bps: 50.0`（0.5%）
- **Buy 마커**: 板価格 × 1.005
- **Sell 마커**: 板価格 × 0.995

### スコア計算要素
- 取引インバランス（Trade Imbalance）
- Ask/Bid 補充量（Replenishment）
- 最良 Ask/Bid 数量変化
- Ask/Bid depth 変化
- 価格動き（Mid-move）

## 解像度設定 (v3.30)

- **DPI**: 500 (`SAVEFIG_DPI_OVERRIDE`)
- **画像寸法**: 11250 x 7280 ピクセル
- **ファイルサイズ**: 約 1.4MB（24 時間データ）
- **Discord プレビュー**: 優先設定（巨大寸法を回避）
- **制限**: Discord 10MB 限度に余裕あり

## バージョン方針

- 本番ファイル名には `v327` / `v328` / `v323a` などを入れません
- バージョンは `orderflow/version.py` に一元化します
- 実行ログと CLI 出力で `v3.30.0` を確認します

## 互換入口

以下は互換ラッパーです。新規運用では使わないでください。

- `bin/run_orderflow_once_v327.sh` -> `bin/run_orderflow_once.sh`
- `bin/run_orderflow_loop_v327.sh` -> `bin/run_orderflow_loop.sh`

## モジュール構造 (v3.30)

v3.30 では描画エンジンを役割別モジュールへ分割しました。

```text
vendor/orderflow_pack/orderflow/current_engine.py
  -> engine_v330.py        # 実行制御
  -> runtime_v330.py       # 共通設定・データ helper・基本描画 helper
  -> absorption_v330.py    # 吸収マーカー計算
  -> oi_v330.py            # OI 読み込み・集計・背景バンド
  -> plot_v330.py          # 最終チャート合成
```

### 役割ごとの責務

- **engine_v330.py**: データ読み込み・集計・全体フロー制御
- **runtime_v330.py**: 共通設定・価格関数・基本描画 helper
- **absorption_v330.py**: 吸収マーカーのスコア計算・位置決定
- **oi_v330.py**: OI データ読み込み・ローソク描画・背景バンド描画
- **plot_v330.py**: レイアウト・凡例・最終 PNG 出力

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

## トラブルシューティング

### 生成失敗
- ログ確認: `tail -50 logs/orderflow_once.log`
- データ整合性: `wc -l data/live_*.jsonl`
- Python 構文: `python3 -m py_compile vendor/orderflow_pack/orderflow/*.py`

### マーカー表示されない
- `live_features_1s.jsonl` があるか確認
- `absorption_marker_config.json` の `enabled: true` 確認
- `minimum_score` など閾値設定の確認

### Discord 送信失敗
- `DISCORD_CHANNEL_ID` が正しいか確認
- Bot 権限（Attachments）の確認
- ファイルサイズが 10MB を超えていないか確認

### 画像が粗すぎる
- `SAVEFIG_DPI_OVERRIDE` 値を上げる（推奨範囲: 300〜600）
- figsize / GridSpec の余白設定を微調整（プレビュー崩れに注意）

## v3.30 主な変更点

- 吸収マーカーのオフセット計算を bps ベースに統一
- マーカーサイズをスコアに応じた連続変化に（3 段階固定 ⇒ 無段階）
- 解像度を 500 DPI に引き上げ（ディスク容量と画質のバランス）
- 未使用ファイル削除（`absorption_overlay_v2.py`, `chartProt3_ws_compat_v2.py`, `chartProt3_ws_layered_v327.py`）
- 未使用 config キー削除（`medium_size`）
- 描画エンジンを役割別モジュールへ再分割
- マーカー形状を ●（circle）に統一

## 開発者向け情報

### dependencies
- `matplotlib` >= 3.8
- `pandas` >= 2.0
- `numpy` >= 1.24
- `aiohttp` >= 3.9

### 変更前後の対応
- 旧 `chartProt3_ws_compat.py` は未使用に近いため削除対象
- 旧 5 層 importlib 連鎖は復活させない

### リファクタ時の注意
- バージョン番号ベースの wrapper 連鎖を復活させない
- 「1 ファイルに巨大統合」ではなく、役割別に分割して責務を明確化
- 変更後は `py_compile` と `scripts/run_plot.sh` の両方を通す
- `tight_layout` warning は既知。exit 0 で画像生成できていればブロッカーではない

## GitHub

https://github.com/like-kradness-2025/btc-orderheatmap
