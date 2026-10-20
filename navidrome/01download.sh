#!/usr/bin/env bash

# This script uses yt-dlp to download music from YouTube Music and tags it for Navidrome

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAYLIST_URL="https://music.youtube.com/playlist?list=LM"
FIREFOX_PROFILE_DIR=$(find ~/.var/app/app.zen_browser.zen/.zen -name '*.Default (release)' -type d | head -n 1)

PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

# Ensure staging directory exists
mkdir -p ./staging

yt-dlp \
    -t aac \
    --audio-quality 0 \
    --embed-thumbnail --convert-thumbnail jpg \
    --ppa "ThumbnailsConvertor+FFmpeg_o:-c:v mjpeg -qmin 1 -qscale:v 1 -vf crop=\"'if(gt(ih,iw),iw,ih)':'if(gt(iw,ih),ih,iw)'\"" \
    --embed-metadata \
    --write-info-json \
    -o "./staging/%(playlist_count+1-playlist_index)04d - %(title)s - %(artist)s.%(ext)s" \
    --exec "$PYTHON_BIN $SCRIPT_DIR/postprocess_navidrome.py %(filepath)q" \
    --cookies-from-browser "firefox:$FIREFOX_PROFILE_DIR" \
    --download-archive "./yt-dlp-archive.txt" \
    "$PLAYLIST_URL"

# Harmonize library once at the end of the entire download run
echo "Running library-wide Navidrome harmonization..."
"$PYTHON_BIN" "$SCRIPT_DIR/postprocess_navidrome.py" "$SCRIPT_DIR/staging" --harmonize-only
