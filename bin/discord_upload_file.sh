#!/usr/bin/env bash
# discord_upload_file.sh
# Usage: ./discord_upload_file.sh <channel_id> <file_path> [message]

if [ "$#" -lt 2 ]; then
    echo "Usage: ./discord_upload_file.sh <channel_id> <file_path> [message]"
    exit 1
fi

TOKEN="MTQ3NDU5OTE4NDMzNzM0MjYyNQ.Gvt-bx.oWJYQ1d2soavlziHIYyWYk7G8q47S3AzPR_zDE"
CHANNEL_ID=$1
FILE_PATH=$2
MESSAGE=${3:-""}

curl -X POST "https://discord.com/api/v10/channels/$CHANNEL_ID/messages" \
     -H "Authorization: Bot $TOKEN" \
     -F "file=@$FILE_PATH" \
     -F "payload_json={\"content\": \"$MESSAGE\"}"
