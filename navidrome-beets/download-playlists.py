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
    r"\s*\((?:(?:feat(?:uring)?\.?|ft\.?)\s+(?P<feature>[^)]+)"
    r"|remaster(?:ed)?(?:\s+(?P<remaster>\d{4}))?"
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


def title_details(title):
    return {
        match.lastgroup: key(match[match.lastgroup])
        for match in TITLE_DETAILS.finditer(title)
        if match.lastgroup
    }


def search_candidates(catalog, video_id, title, artist, duration, channel_id):
    if not (title and artist and duration):
        return []

    artist_key = key(artist)
    search_title = TITLE_DETAILS.sub("", title)
    title_key = key(search_title)
    details = title_details(title)
    matches = []
    for song in catalog.search(f"{artist} {search_title}", filter="songs", limit=10):
        alternative = song.get("videoId")
        length = song.get("duration_seconds")
        if not alternative or alternative == video_id or length is None or abs(length - duration) > 5:
            continue
        candidate_title = song.get("title") or ""
        if key(TITLE_DETAILS.sub("", candidate_title)) != title_key:
            continue
        candidate_details = title_details(candidate_title)
        if any(details[name] != candidate_details[name] for name in details.keys() & candidate_details.keys()):
            continue

        credits = song.get("artists")
        if not credits:
            try:
                video = catalog.get_song(alternative).get("videoDetails") or {}
            except (RequestException, YTMusicError) as error:
                print(f"Could not verify the artist for {alternative}: {error}", file=sys.stderr)
                continue
            credits = [{"id": video.get("channelId"), "name": video.get("author")}]
        if any(
            (channel_id and credit.get("id") == channel_id)
            or key(credit.get("name") or "") == artist_key
            for credit in credits
        ):
            matches.append(alternative)
    return matches


def candidates(catalog, source):
    video_id = source["id"]
    title = source.get("title") or ""
    artist = source.get("artist") or source.get("channel") or source.get("uploader") or ""
    artist = ARTIST_SUFFIX.sub("", artist)
    duration = source.get("duration")
    channel_id = source.get("channel_id")
    metadata = (title, artist, duration, channel_id)
    matches = search_candidates(catalog, video_id, *metadata)
    if matches:
        return matches

    # A playlist uploader can differ from the recording's catalog artist.
    original = catalog.get_song(video_id).get("videoDetails") or {}
    enriched = (
        title or original.get("title"),
        original.get("author") or artist,
        duration or int(original.get("lengthSeconds") or 0),
        original.get("channelId") or channel_id,
    )
    if enriched == metadata:
        return []
    return search_candidates(catalog, video_id, *enriched)


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
    unidentified = sum(len(playlist["entries"]) for playlist in playlists) - len(entries)
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

    missing = [
        f"{track.get('title', vid)} ({vid})"
        for vid, track in plans.items()
        if selected[vid] not in downloaded
    ]
    for track in missing:
        print(f"No audio downloaded for {track}", file=sys.stderr)
    if unidentified:
        print(f"No video ID for {unidentified} playlist entries", file=sys.stderr)
    return bool(missing or unidentified)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
