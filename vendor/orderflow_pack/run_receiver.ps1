param(
  [string]$Symbol = 'btcusdt',
  [string]$DataDir = '.\data\live',
  [int]$Seconds = 0
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
node .\orderflow_monitor.mjs `
  --symbol=$Symbol `
  --seconds=$Seconds `
  --bookOut="$DataDir\live_book.jsonl" `
  --bookRawOut="$DataDir\live_book_raw.jsonl" `
  --bookBucketOut="$DataDir\live_book_bucketed.jsonl" `
  --tradeOut="$DataDir\live_trades.jsonl" `
  --tradeCompactOut="$DataDir\live_trades_compact.jsonl"
