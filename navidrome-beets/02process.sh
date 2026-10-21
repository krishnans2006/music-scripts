#!/usr/bin/env bash

# This script uses beets (https://beets.io/) to:
# - Fetch metadata from MusicBrainz and tag tracks for Navidrome
# - Embed synced lyrics
# - Move the processed music to a flat directory structure (./final)

set -e

if [ ! -d "./staging" ] || [ -z "$(ls -A ./staging)" ]; then
   echo "No new music downloaded in ./staging. Exiting."
   exit 0
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

sed -e "s|SCRIPT_DIR|$SCRIPT_DIR|g" beets.yaml > beets-generated.yaml

beet -c ./beets-generated.yaml import ./staging
