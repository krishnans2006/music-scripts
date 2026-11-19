#!/usr/bin/env bash

# This script uses beets (https://beets.io/) to:
# - Fetch metadata from MusicBrainz and tag tracks for Navidrome
# - Embed synced lyrics
# - Move the processed music to a flat directory structure (./final)
# - Generate ordered M3U8 files for the downloaded playlists
# - Calculate ReplayGain loudness normalization tags using ffmpeg

set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

sed -e "s|SCRIPT_DIR|$SCRIPT_DIR|g" beets.yaml > beets-generated.yaml

if [[ -d ./staging && -n $(ls -A ./staging) ]]; then
    beet -c ./beets-generated.yaml import ./staging
    beet -c ./beets-generated.yaml replaygain
fi

if [[ -f ./.playlists/sources.jsonl ]]; then
    beet -c ./beets-generated.yaml yt-playlists ./.playlists/sources.jsonl
fi
