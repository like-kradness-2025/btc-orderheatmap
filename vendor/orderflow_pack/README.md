# Binance Orderflow Current Minimal Pack

今動いている receiver / plot をベースにした配布用の最小構成です。

## 同梱ファイル
- `orderflow_monitor.mjs` - 現行 receiver
- `orderflow/chartProt3_ws_compat.py` - 現行 plot ラッパー
- `chartProt3_orig.py` - ベース描画ロジック
- `run_receiver.ps1` - 受信起動
- `run_plot.ps1` - 描画実行
- `.env.example` - 任意の環境変数雛形
- `README.md`

## 同梱しないもの
- 受信データ
- png / ログ / キャッシュ
- 実験用スクリプト
- webhook 実値や秘密情報

## 必要環境
- Node.js 20+
- Python 3.11+
- Python packages: `numpy pandas matplotlib aiohttp pytz requests`

```powershell
pip install numpy pandas matplotlib aiohttp pytz requests
```

## 最短手順
### 受信
```powershell
powershell -ExecutionPolicy Bypass -File .\run_receiver.ps1
```

### 描画
```powershell
powershell -ExecutionPolicy Bypass -File .\run_plot.ps1
```

## 出力先
受信:
- `data\\live\\live_book.jsonl`
- `data\\live\\live_book_raw.jsonl`
- `data\\live\\live_book_bucketed.jsonl`
- `data\\live\\live_trades.jsonl`
- `data\\live\\live_trades_compact.jsonl`

描画:
- `tmp\\chart.png`

## セキュリティ
- `chartProt3_orig.py` 内の webhook 実値は配布版ではプレースホルダ化
- `.env.example` は雛形のみ
- API key / secret / webhook 実値は含めない

## 注意
- plot は `chartProt3_ws_compat.py` 経由で `chartProt3_orig.py` を読み込みます
- receiver は Binance Futures BTCUSDT 前提の最小構成です
