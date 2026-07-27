#!/usr/bin/env bash

# This script uses beets (https://beets.io/) to:
# - Fingerprint music using AcoustID
# - Fetch metadata from MusicBrainz
# - Tag music files with the fetched metadata
# - Fetch lyrics
# - Move the processed music and lyrics to a Jellyfin-compatible directory structure (./final)
# - Generate playlist files (.m3u) using beets' smartplaylist plugin

set -e

if [ ! -d "./staging" ] || [ -z "$(ls -A ./staging)" ]; then
   echo "No new music downloaded in ./staging. Exiting."
   exit 0
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

if [ -f ".env" ]; then
    # Load variables into environment, ignoring comments
    export $(grep -v '^#' .env | xargs)
else
    echo "Error: .env file not found."
    exit 1
fi

if [ -z "$ACOUSTID_API_KEY" ]; then
    echo "Error: ACOUSTID_API_KEY is not set in the .env file."
    exit 1
fi

sed -e "s|SCRIPT_DIR|$SCRIPT_DIR|g" \
    -e "s|ACOUSTID_API_KEY|$ACOUSTID_API_KEY|g" \
    beets.yaml > beets-generated.yaml

beet -v -c ./beets.yaml import -q --set playlist_source="Liked Music" ./staging

beet -v -c ./beets.yaml splupdate
