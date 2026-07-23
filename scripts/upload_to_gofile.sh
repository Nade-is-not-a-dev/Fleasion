#!/usr/bin/env bash
# Upload a file to GoFile.io and print the download URL.
# Usage: ./upload_to_gofile.sh <file_path>

set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo "ERROR: No file specified." >&2
    exit 1
fi

FILE="$1"

if [[ ! -f "$FILE" ]]; then
    echo "ERROR: File not found: $FILE" >&2
    exit 1
fi

echo "Looking up GoFile server..."
SERVER="$(curl -s https://api.gofile.io/servers | python3 -c "
import sys, json
data = json.load(sys.stdin)
servers = data.get('data', {}).get('servers', [])
print(servers[0]['name'] if servers else 'store')
")"
echo "Using server: $SERVER"

echo "Uploading $FILE ..."
RESPONSE="$(curl -s -F "file=@$FILE" "https://${SERVER}.gofile.io/uploadFile")"

LINK="$(echo "$RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('data', {}).get('downloadPage', ''))
" 2>/dev/null || true)"

if [[ -z "$LINK" ]]; then
    echo "ERROR: Upload failed. Response:" >&2
    echo "$RESPONSE" >&2
    exit 1
fi

echo
echo "===== GoFile Upload Complete ====="
echo "File: $(basename "$FILE")"
echo "Size: $(du -h "$FILE" | cut -f1)"
echo "Download URL: $LINK"
echo "=================================="
echo
echo "$LINK"
