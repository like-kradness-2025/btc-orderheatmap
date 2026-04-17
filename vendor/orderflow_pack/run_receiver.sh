#!/usr/bin/env bash
export PATH="/home/weed420/.nvm/versions/node/v24.14.0/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")"
node orderflow_monitor.mjs --symbol=btcusdt --seconds=0 --bookOut=../../data/live/live_book.jsonl --bookRawOut=../../data/live/live_book_raw.jsonl --bookBucketOut=../../data/live/live_book_bucketed.jsonl --tradeOut=../../data/live/live_trades.jsonl --tradeCompactOut=../../data/live/live_trades_compact.jsonl --healthOut=../../runtime/health/receiver.json
