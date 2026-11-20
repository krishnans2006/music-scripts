"""Download playlist entries and resolve unavailable uploads through YouTube Music."""

import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from tempfile import TemporaryFile

from requests.exceptions import RequestException
from ytmusicapi import YTMusic
from ytmusicapi.exceptions import YTMusicError


ARCHIVE = Path("yt-dlp-archive.txt")
SOURCES = Path(".playlists/sources.jsonl")
PENDING_SOURCES = SOURCES.with_suffix(".tmp")
UNAVAILABLE = re.compile(
    r"^ERROR: \[youtube\] ([\w-]{11}): (?:Video unavailable|This video is not available|Private video)\b",
    re.IGNORECASE,
)
ARTIST_SUFFIX = re.compile(r"\s+(?:- Topic|Official(?: Artist Channel)?|Videos)$", re.IGNORECASE)
TITLE_DETAILS = re.compile(
    r"\s*\((?:feat(?:uring)?\.?\s+[^)]*|ft\.?\s+[^)]*|remaster(?:ed)?(?:\s+\d{4})?"
    r"|studio(?: version| recording\b[^)]*)?)\)",
    re.IGNORECASE,
)


def archived_ids():
    if not ARCHIVE.exists():
        return set()
    return {
        line.removeprefix("youtube ")
        for line in ARCHIVE.read_text(encoding="utf-8").splitlines()
        if line.startswith("youtube ")
    }


def read_playlists(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def playlist_tracks(playlists):
    return [
        track for playlist in playlists for track in playlist["entries"] if track and track.get("id")
    ]


def download(video_ids, options):
    if not video_ids:
        return set()

    unavailable = set()
    with TemporaryFile(mode="w+t", encoding="utf-8") as urls:
        for video_id in video_ids:
            urls.write(f"https://music.youtube.com/watch?v={video_id}\n")
        urls.seek(0)
        with subprocess.Popen(
            [
                "yt-dlp", *options, "--color", "never", "--newline",
                "--no-abort-on-error", "--no-break-on-existing",
                "--download-archive", str(ARCHIVE), "--batch-file", "-",
            ],
            stdin=urls,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
        ) as process:
            for line in process.stdout:
                print(line, end="", flush=True)
                if match := UNAVAILABLE.match(line):
                    unavailable.add(match[1])
    return unavailable


def key(text):
    return "".join(char for char in unicodedata.normalize("NFKC", text).casefold() if char.isalnum())


def candidates(catalog, source):
    title = source.get("title") or ""
    artist = source.get("artist") or source.get("channel") or source.get("uploader") or ""
    artist = ARTIST_SUFFIX.sub("", artist)
    duration = source.get("duration")
    channel_ids = {source.get("channel_id")} - {None}
    original = None

    if not (title and artist and duration):
        original = catalog.get_song(source["id"]).get("videoDetails", {})
        title = title or original.get("title")
        artist = artist or original.get("author")
        duration = duration or int(original.get("lengthSeconds") or 0)
        if not (title and artist and duration):
            return []

    artist_names = {key(artist)}
    search_title = TITLE_DETAILS.sub("", title)
    matches = []
    for song in catalog.search(f"{artist} {search_title}", filter="songs", limit=10):
        video_id = song.get("videoId")
        length = song.get("duration_seconds")
        if not video_id or video_id == source["id"] or length is None or abs(length - duration) > 5:
            continue
        if key(TITLE_DETAILS.sub("", song.get("title") or "")) == key(search_title):
            matches.append(song)

    def matching_artist(song):
        return any(
            credit.get("id") in channel_ids or key(credit.get("name") or "") in artist_names
            for credit in song.get("artists") or []
        )

    for song in matches:
        if not song.get("artists"):
            details = catalog.get_song(song["videoId"]).get("videoDetails", {})
            song["artists"] = [{"id": details.get("channelId"), "name": details.get("author")}]

    if matches and not any(matching_artist(song) for song in matches):
        # The playlist channel can be branded differently from the catalog artist.
        if original is None:
            original = catalog.get_song(source["id"]).get("videoDetails", {})
        if channel_id := original.get("channelId"):
            channel_ids.add(channel_id)
        if author := original.get("author"):
            artist_names.add(key(author))

    return [song["videoId"] for song in matches if matching_artist(song)]


def resolve(plans, selected, unavailable, downloaded, options):
    catalog = YTMusic()
    for video_id, track in plans.items():
        if video_id not in unavailable or selected[video_id] in downloaded:
            continue
        try:
            alternatives = candidates(catalog, track)
        except (RequestException, YTMusicError) as error:
            print(f"Catalog lookup failed for {video_id}: {error}", file=sys.stderr)
            continue

        # Reuse an existing download before fetching another catalog upload.
        for alternative in sorted(dict.fromkeys(alternatives), key=lambda vid: vid not in downloaded):
            if alternative not in downloaded:
                download([alternative], options)
                downloaded.update(archived_ids())
            if alternative in downloaded:
                selected[video_id] = alternative
                print(f"Resolved {track.get('title', video_id)}: {video_id} -> {alternative}", flush=True)
                break


def main(options):
    playlists = read_playlists(PENDING_SOURCES)
    entries = playlist_tracks(playlists)
    plans = {track["id"]: track for track in entries}
    downloaded = archived_ids()
    selected = {video_id: video_id for video_id in plans}
    if SOURCES.exists():
        for track in playlist_tracks(read_playlists(SOURCES)):
            video_id = track["id"]
            previous = track.get("download_id")
            if video_id in selected and video_id not in downloaded and previous in downloaded:
                selected[video_id] = previous

    pending = [video_id for video_id in dict.fromkeys(selected.values()) if video_id not in downloaded]
    unavailable = download(pending, options)
    downloaded.update(archived_ids())
    if unavailable:
        resolve(plans, selected, unavailable, downloaded, options)

    for track in entries:
        video_id = track["id"]
        if selected[video_id] != video_id:
            track["download_id"] = selected[video_id]

    with PENDING_SOURCES.open("w", encoding="utf-8") as output:
        for playlist in playlists:
            output.write(json.dumps(playlist) + "\n")
    PENDING_SOURCES.replace(SOURCES)

    missing = [f"{track.get('title', vid)} ({vid})" for vid, track in plans.items() if selected[vid] not in downloaded]
    for track in missing:
        print(f"No audio downloaded for {track}", file=sys.stderr)
    return bool(missing)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
