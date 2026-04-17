#!/usr/bin/env bash
# discord_poster.sh
# Usage: ./discord_poster.sh <webhook_url> <file_path>

if [ "$#" -ne 2 ]; then
    echo "Usage: ./discord_poster.sh <webhook_url> <file_path>"
    exit 1
fi

WEBHOOK_URL=$1
FILE_PATH=$2

if [ ! -f "$FILE_PATH" ]; then
    echo "File not found: $FILE_PATH"
    exit 1
fi

curl -F "file=@$FILE_PATH" "$WEBHOOK_URL"
