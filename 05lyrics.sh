#!/usr/bin/env bash

# This script fetches lyrics with beets and exports Jellyfin-compatible sidecars.
# Synchronized lyrics use .lrc; unsynchronized lyrics use .txt.

set -euo pipefail

readonly BEETS_CONFIG="./beets-generated.yaml"
readonly LRC_TIMESTAMP='\[[0-9]{2,}:[0-9]{2}(\.[0-9]{1,3})?\]'

if [ ! -f "$BEETS_CONFIG" ]; then
    echo "Error: beets-generated.yaml not found. Run ./03process.sh first."
    exit 1
fi

beet -c "$BEETS_CONFIG" lyrics

for item_id in $(beet -c "$BEETS_CONFIG" ls -f '$id' 'lyrics::.'); do
    audio_file="$(beet -c "$BEETS_CONFIG" ls -f '$path' "id:$item_id")"
    if [ ! -f "$audio_file" ]; then
        continue
    fi

    lyrics="$(beet -c "$BEETS_CONFIG" ls -f '$lyrics' "id:$item_id")"
    if [ -z "$lyrics" ]; then
        continue
    fi

    if [[ "$lyrics" =~ $LRC_TIMESTAMP ]]; then
        extension="lrc"
    else
        extension="txt"
    fi

    printf '%s\n' "$lyrics" > "${audio_file%.*}.$extension"
done
