#!/usr/bin/env bash

# This script uses yt-dlp to download music from YouTube Music

set -e

PLAYLIST_URL="https://music.youtube.com/playlist?list=LM"
FIREFOX_PROFILE_DIR=$(find ~/.var/app/app.zen_browser.zen/.zen -name '*.Default (release)' -type d | head -n 1)

# Ensure staging directory exists
mkdir -p ./staging

yt-dlp \
    -t aac \
    --audio-quality 0 \
    --embed-thumbnail --convert-thumbnail jpg \
    --ppa "ThumbnailsConvertor+FFmpeg_o:-c:v mjpeg -qmin 1 -qscale:v 1 -vf crop=\"'if(gt(ih,iw),iw,ih)':'if(gt(iw,ih),ih,iw)'\"" \
    --embed-metadata --parse-metadata "playlist_index:%(track_number)s" \
    -o "./staging/%(playlist_count+1-playlist_index)04d - %(title)s - %(artist)s.%(ext)s" \
    --cookies-from-browser "firefox:$FIREFOX_PROFILE_DIR" \
    --download-archive "./yt-dlp-archive.txt" \
    "$PLAYLIST_URL"
