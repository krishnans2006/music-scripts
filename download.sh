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

# Commit + Push
git update-index --refresh -q

if git diff-index --quiet HEAD
then
    echo "No changes to commit"
else
    touch .commit_msg
    echo "Add songs from Spotify" > .commit_msg
    echo "" >> .commit_msg
    git diff --name-status HEAD >> .commit_msg

    sleep 5000

    git add .
    git commit -F .commit_msg
    git push
fi

# Teardown
ulimit -n 1024

deactivate
cd - > /dev/null
