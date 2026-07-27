#!/usr/bin/env bash

# This script uses beets (https://beets.io/) to:
# - Fingerprint music using AcoustID
# - Fetch metadata from MusicBrainz
# - Tag music files with the fetched metadata
# - Fetch lyrics
# - Move the processed music and lyrics to a Jellyfin-compatible directory structure (./final)

set -e

if [ ! -d "./staging" ] || [ -z "$(ls -A ./staging)" ]; then
   echo "No new music downloaded in ./staging. Exiting."
   exit 0
else
   beet -v -c ./beets.yaml import -q --set playlist_source="Liked Music" ./staging
fi
