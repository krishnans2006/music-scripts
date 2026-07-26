#!/usr/bin/env bash

# This script triggers beets' smartplaylist plugin to generate playlist files (.m3u)

beet -c ./beets.yaml splupdate
