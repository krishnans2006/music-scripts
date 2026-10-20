#!/usr/bin/env bash

rsync -av --rsync-path="sudo rsync" --chown=jellyfin:jellyfin --delete ./final/ krishnan@krishnan-pi:/data/jellyfin/media/krishnan-music/

ssh krishnan@krishnan-pi "sudo chown -R jellyfin:jellyfin /data/jellyfin/media/krishnan-music/"
