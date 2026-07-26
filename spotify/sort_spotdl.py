import json
import os
import sys

if len(sys.argv) != 2:
    print("Usage: sort_spotdl.py <file>")
    sys.exit(1)

filename = sys.argv[1] + ".spotdl"

with open(os.path.join(os.path.dirname(__file__), filename), "r") as f:
    data = json.load(f)

new_songs = []

for song in data["songs"]:
    new_songs.append(song)

new_songs.sort(key=lambda x: x["list_position"])

data["songs"] = new_songs

with open(os.path.join(os.path.dirname(__file__), filename), "w") as f:
    json.dump(data, f, indent=4)
