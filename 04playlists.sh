#!/usr/bin/env bash

# This script uses beets' smartplaylist plugin to generate playlist files
# for Jellyfin in ./final.

set -e

if [ ! -f "./beets-generated.yaml" ]; then
    echo "Error: beets-generated.yaml not found. Run ./03process.sh first."
    exit 1
fi

beet -c ./beets-generated.yaml splupdate
