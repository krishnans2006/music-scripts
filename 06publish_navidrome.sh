#!/usr/bin/env bash

rsync -av --rsync-path="sudo rsync" --chown=navidrome:navidrome --delete ./staging/ krishnan@krishnan-pi:/data/navidrome/media/liked-music/

ssh krishnan@krishnan-pi "sudo chown -R navidrome:navidrome /data/navidrome/media/liked-music/"
