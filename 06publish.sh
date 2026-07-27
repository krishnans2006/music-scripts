#!/usr/bin/env bash

rsync -av -O --no-o --no-g --no-p --delete ./final/ krishnan@krishnan-pi:/data/jellyfin/media/krishnan-music/

ssh krishnan@krishnan-pi "sudo chown -R jellyfin:jellyfin /data/jellyfin/media/krishnan-music/"
