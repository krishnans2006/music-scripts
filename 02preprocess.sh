#!/usr/bin/env bash

if [ ! -d "./staging" ] || [ -z "$(ls -A ./staging)" ]; then
   echo "No new music downloaded in ./staging. Exiting."
   exit 0
fi

# Move files to a subfolder with the same name as the file
for file in ./staging/*.m4a; do
    if [[ -f "$file" ]]; then
        filename=$(basename "$file")
        foldername="${filename%.m4a}"
        mkdir -p "./staging/$foldername"
        mv "$file" "./staging/$foldername/"
    fi
done
