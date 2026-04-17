#!/usr/bin/env bash
# discord_direct_message.sh
# Usage: ./discord_direct_message.sh <channel_id> <content>

if [ "$#" -lt 2 ]; then
    echo "Usage: ./discord_direct_message.sh <channel_id> <content>"
    exit 1
fi

TOKEN="MTQ3NDU5OTE4NDMzNzM0MjYyNQ.Gvt-bx.oWJYQ1d2soavlziHIYyWYk7G8q47S3AzPR_zDE"
CHANNEL_ID=$1
shift
CONTENT="$*"

# Use Python to safely escape JSON
PAYLOAD=$(python3 -c 'import json, sys; print(json.dumps({"content": sys.argv[1]}))' "$CONTENT")

curl -X POST "https://discord.com/api/v10/channels/$CHANNEL_ID/messages" \
     -H "Authorization: Bot $TOKEN" \
     -H "Content-Type: application/json" \
     -d "$PAYLOAD"
