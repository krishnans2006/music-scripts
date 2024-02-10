#!/usr/bin/env zsh

LISTS=( 'songs' 'classical' 'jams' 'youtubers' 'movies' 'christmas' 'theme-songs' )

# Setup
cd "$(dirname "$0")"
source venv/bin/activate

ulimit -n 16384

# Argument parsing
if [[ "$1" != "" ]]
then
    lists=( "$@" )
else
    lists=( "${LISTS[@]}" )
fi

# Download
printf -v lists_str "%s, " "${lists[@]}"
echo "Downloading lists: ${lists_str%, }"

for list in "${lists[@]}"
do
    location="${list}/{list-position} - {artist} - {album} - {title}"
    python -m spotdl --log-level DEBUG --threads 16 --user-auth --dont-filter-results --output "$location" sync "${list}.spotdl"
    python sort_spotdl.py "$list"
done

# Teardown
ulimit -n 1024

deactivate
cd - > /dev/null
