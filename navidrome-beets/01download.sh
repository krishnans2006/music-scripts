#!/usr/bin/env bash

# This script uses yt-dlp to download music from YouTube Music

set -e

PLAYLIST_URLS=(
    "https://music.youtube.com/playlist?list=LM"
    "https://music.youtube.com/playlist?list=PLdRk0edErpmASvp1jwflNbSgbiLRrG6q1" # Christmas
)
FIREFOX_PROFILE_DIR="~/.config/zen/default"

mkdir -p ./staging ./.playlists

# Capture every playlist entry, including tracks already in the archive.
yt-dlp --flat-playlist --dump-single-json --no-download-archive --abort-on-error \
    --cookies-from-browser "firefox:$FIREFOX_PROFILE_DIR" \
    "${PLAYLIST_URLS[@]}" > ./.playlists/sources.tmp
mv ./.playlists/sources.tmp ./.playlists/sources.jsonl

yt-dlp \
    -t aac \
    --audio-quality 0 \
    --embed-thumbnail --convert-thumbnail jpg \
    --ppa "ThumbnailsConvertor+FFmpeg_o:-c:v mjpeg -qmin 1 -qscale:v 1 -vf crop=\"'if(gt(ih,iw),iw,ih)':'if(gt(iw,ih),ih,iw)'\"" \
    --embed-metadata \
    -o "./staging/%(id)s.%(ext)s" \
    --cookies-from-browser "firefox:$FIREFOX_PROFILE_DIR" \
    --download-archive "./yt-dlp-archive.txt" \
    "${PLAYLIST_URLS[@]}"
