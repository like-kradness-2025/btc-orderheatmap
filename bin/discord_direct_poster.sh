#!/usr/bin/env bash
# discord_direct_poster.sh
# Usage: ./discord_direct_poster.sh <channel_id> <file_path> [content]

if [ "$#" -lt 2 ]; then
    echo "Usage: ./discord_direct_poster.sh <channel_id> <file_path> [content]"
    exit 1
fi

TOKEN="MTQ3NDU5OTE4NDMzNzM0MjYyNQ.Gvt-bx.oWJYQ1d2soavlziHIYyWYk7G8q47S3AzPR_zDE"
CHANNEL_ID=$1
FILE_PATH=$2
CONTENT=${3:-""}

if [ ! -f "$FILE_PATH" ]; then
    echo "File not found: $FILE_PATH"
    exit 1
fi

curl -X POST "https://discord.com/api/v10/channels/$CHANNEL_ID/messages" \
     -H "Authorization: Bot $TOKEN" \
     -F "file=@$FILE_PATH" \
     -F "payload_json={\"content\": \"$CONTENT\"}"
