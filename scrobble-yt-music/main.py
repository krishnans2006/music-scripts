#!/usr/bin/env python3
"""YouTube Music Watch History Scrobbler Formatter.

Parses Google Takeout `watch-history.json` for YouTube Music listens,
enriches tracks with album names via YouTube Music API, and exports
chunked JSON files ready for Last.fm-Scrubbler-WPF.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any, Dict, List, Optional
import urllib.parse

try:
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeRemainingColumn,
    )

    console = Console()
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False

try:
    import ytmusicapi

    HAS_YTMUSICAPI = True
except ImportError:
    HAS_YTMUSICAPI = False


VIDEO_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def extract_video_id(url: Optional[str]) -> Optional[str]:
    """Extract YouTube 11-character video ID from a titleUrl."""
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
        if "youtube.com" in parsed.netloc:
            query = urllib.parse.parse_qs(parsed.query)
            if "v" in query and query["v"]:
                vid = query["v"][0]
                if VIDEO_ID_REGEX.match(vid):
                    return vid
        elif parsed.netloc == "youtu.be":
            vid = parsed.path.strip("/")
            if VIDEO_ID_REGEX.match(vid):
                return vid
    except Exception:
        pass

    # Fallback to regex pattern matching in url
    match = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})(?:[&?]|$)", url)
    if match:
        return match.group(1)
    return None


def clean_title(raw_title: Optional[str]) -> Optional[str]:
    """Clean track title by removing Takeout prefixes like 'Watched '."""
    if not raw_title:
        return None
    title = raw_title.strip()
    if title.startswith("Watched "):
        title = title[8:]
    elif title.startswith("A regardé "):
        title = title[10:]
    return title.strip() or None


def parse_watch_history(
    file_path: Path, only_topic: bool = False
) -> List[Dict[str, Any]]:
    """Parse Google Takeout watch-history.json and filter YouTube Music items.

    Args:
        file_path: Path to watch-history.json
        only_topic: If True, only include tracks where artist channel ends with ' - Topic'

    Returns:
        List of track dicts with artistName, trackName, ts, time, and video_id.
    """
    if not file_path.is_file():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Invalid JSON format: expected a top-level list of history items.")

    tracks: List[Dict[str, Any]] = []

    for item in data:
        if not isinstance(item, dict):
            continue

        # Check if item is YouTube Music
        header = item.get("header")
        products = item.get("products", [])
        is_yt_music = header == "YouTube Music" or "YouTube Music" in products
        if not is_yt_music:
            continue

        # Subtitles contains the artist / channel information
        subtitles = item.get("subtitles")
        if not subtitles or not isinstance(subtitles, list) or not subtitles[0]:
            continue

        raw_artist = subtitles[0].get("name", "").strip()
        if not raw_artist:
            continue

        is_topic_channel = raw_artist.endswith(" - Topic")
        if only_topic and not is_topic_channel:
            continue

        artist = raw_artist.removesuffix(" - Topic").strip()
        title = clean_title(item.get("title"))
        if not title:
            continue

        video_id = extract_video_id(item.get("titleUrl"))
        play_time = item.get("time", "")

        tracks.append(
            {
                "artistName": artist,
                "trackName": title,
                "albumName": "",
                "time": play_time,
                "ts": play_time,
                "video_id": video_id,
            }
        )

    return tracks


class AlbumResolver:
    """Thread-safe album name resolver with caching and rate-limiting."""

    def __init__(
        self,
        cache_path: Optional[Path] = None,
        max_workers: int = 5,
        request_delay: float = 0.05,
    ):
        self.cache_path = cache_path
        self.max_workers = max_workers
        self.request_delay = request_delay
        self._cache: Dict[str, str] = {}
        self._cache_lock = threading.Lock()
        self._local = threading.local()
        self._load_cache()

    def _get_ytmusic(self) -> ytmusicapi.YTMusic:
        """Get or initialize thread-local YTMusic instance."""
        if not hasattr(self._local, "ytmusic"):
            self._local.ytmusic = ytmusicapi.YTMusic()
        return self._local.ytmusic

    def _cache_key(self, video_id: Optional[str], artist: str, track: str) -> str:
        """Create cache lookup key preferring video_id or artist+track."""
        if video_id:
            return f"vid:{video_id}"
        return f"meta:{artist.strip().lower()}:{track.strip().lower()}"

    def _load_cache(self) -> None:
        if self.cache_path and self.cache_path.is_file():
            try:
                with self.cache_path.open("r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception:
                self._cache = {}

    def save_cache(self) -> None:
        if self.cache_path:
            with self._cache_lock:
                try:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.cache_path.open("w", encoding="utf-8") as f:
                        json.dump(self._cache, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    if console:
                        console.print(f"[yellow]Warning: Failed to save cache: {e}[/yellow]")
                    else:
                        print(f"Warning: Failed to save cache: {e}", file=sys.stderr)

    def get_cached(self, video_id: Optional[str], artist: str, track: str) -> Optional[str]:
        key = self._cache_key(video_id, artist, track)
        with self._cache_lock:
            return self._cache.get(key)

    def set_cached(
        self, video_id: Optional[str], artist: str, track: str, album: str
    ) -> None:
        key = self._cache_key(video_id, artist, track)
        with self._cache_lock:
            self._cache[key] = album

    def resolve_single(
        self, video_id: Optional[str], artist: str, track: str
    ) -> str:
        """Resolve album name for a track using YouTube Music API."""
        cached = self.get_cached(video_id, artist, track)
        if cached is not None:
            return cached

        yt = self._get_ytmusic()

        # Step 1: If video_id is available, search directly by video ID
        if video_id:
            try:
                results = yt.search(video_id, filter="songs")
                for r in results:
                    album = r.get("album")
                    if album and album.get("name"):
                        album_name = album["name"].strip()
                        self.set_cached(video_id, artist, track, album_name)
                        return album_name
            except Exception:
                pass

        # Step 2: Search by 'Artist Track'
        try:
            query = f"{artist} {track}"
            results = yt.search(query, filter="songs")
            for r in results:
                album = r.get("album")
                if album and album.get("name"):
                    album_name = album["name"].strip()
                    self.set_cached(video_id, artist, track, album_name)
                    return album_name
        except Exception:
            pass

        # Step 3: Broader search if still no album
        try:
            results = yt.search(f"{artist} {track}")
            for r in results:
                album = r.get("album")
                if album and album.get("name"):
                    album_name = album["name"].strip()
                    self.set_cached(video_id, artist, track, album_name)
                    return album_name
        except Exception:
            pass

        # If not found, cache empty string to prevent repeated unsuccessful lookups
        self.set_cached(video_id, artist, track, "")
        return ""

    def resolve_all(
        self, tracks: List[Dict[str, Any]]
    ) -> tuple[int, int]:
        """Resolve albums for all tracks, deduplicating requests.

        Returns (cache_hits, api_successes)
        """
        # Deduplicate unique tracks to query
        unique_queries: Dict[str, tuple[Optional[str], str, str]] = {}
        for t in tracks:
            key = self._cache_key(t["video_id"], t["artistName"], t["trackName"])
            if key not in unique_queries:
                unique_queries[key] = (t["video_id"], t["artistName"], t["trackName"])

        cache_hits = 0
        pending_queries: List[tuple[str, tuple[Optional[str], str, str]]] = []

        for key, (vid, artist, track) in unique_queries.items():
            cached = self.get_cached(vid, artist, track)
            if cached is not None:
                cache_hits += 1
            else:
                pending_queries.append((key, (vid, artist, track)))

        api_successes = 0

        if pending_queries:
            if HAS_RICH and console:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    MofNCompleteColumn(),
                    TimeRemainingColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task(
                        "[cyan]Fetching album names from YouTube Music...",
                        total=len(pending_queries),
                    )

                    with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                        future_to_key = {
                            executor.submit(
                                self.resolve_single, vid, artist, track
                            ): key
                            for key, (vid, artist, track) in pending_queries
                        }

                        for future in as_completed(future_to_key):
                            try:
                                album = future.result()
                                if album:
                                    api_successes += 1
                            except Exception:
                                pass
                            progress.advance(task)
                            if self.request_delay > 0:
                                time.sleep(self.request_delay / self.max_workers)
            else:
                total_pending = len(pending_queries)
                print(f"Fetching album names for {total_pending} unique tracks...")
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_key = {
                        executor.submit(
                            self.resolve_single, vid, artist, track
                        ): key
                        for key, (vid, artist, track) in pending_queries
                    }
                    completed = 0
                    for future in as_completed(future_to_key):
                        try:
                            album = future.result()
                            if album:
                                api_successes += 1
                        except Exception:
                            pass
                        completed += 1
                        if completed % 100 == 0 or completed == total_pending:
                            print(f"Progress: {completed}/{total_pending} tracks queried...")

        # Persist cache to disk
        self.save_cache()

        # Populate albumName on all tracks
        for t in tracks:
            album = self.get_cached(t["video_id"], t["artistName"], t["trackName"])
            t["albumName"] = album or ""

        return cache_hits, api_successes


def write_formatted_json(
    tracks: List[Dict[str, Any]],
    output_path: Path,
    chunk_size: int = 2800,
) -> List[Path]:
    """Write tracks to output file(s), chunking if necessary.

    Removes internal helper fields (like video_id) before serializing.
    """
    clean_tracks = []
    for t in tracks:
        record = {
            "artistName": t["artistName"],
            "trackName": t["trackName"],
            "albumName": t.get("albumName", ""),
            "time": t["time"],
            "ts": t["ts"],
        }
        clean_tracks.append(record)

    written_files: List[Path] = []

    if chunk_size <= 0 or len(clean_tracks) <= chunk_size:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(clean_tracks, f, indent=2, ensure_ascii=False)
        written_files.append(output_path)
    else:
        # Split into chunk files (e.g., formatted-1.json, formatted-2.json)
        stem = output_path.stem
        suffix = output_path.suffix or ".json"
        parent = output_path.parent
        parent.mkdir(parents=True, exist_ok=True)

        total_chunks = (len(clean_tracks) + chunk_size - 1) // chunk_size
        for idx in range(total_chunks):
            chunk = clean_tracks[idx * chunk_size : (idx + 1) * chunk_size]
            file_name = f"{stem}-{idx + 1}{suffix}"
            target_path = parent / file_name
            with target_path.open("w", encoding="utf-8") as f:
                json.dump(chunk, f, indent=2, ensure_ascii=False)
            written_files.append(target_path)

    return written_files


def print_instructions(written_files: List[Path]) -> None:
    """Print helpful instructions for importing into Last.fm-Scrubbler-WPF."""
    msg = (
        "\n[bold green]Processing complete![/bold green]\n"
        f"Generated {len(written_files)} file(s):\n"
    )
    for f in written_files:
        msg += f"  • {f.resolve()}\n"

    msg += (
        "\n[bold cyan]Next Steps with Last.fm-Scrubbler-WPF:[/bold cyan]\n"
        "  1. Download and open [link=https://github.com/SHOEGAZEssb/Last.fm-Scrubbler-WPF]Last.fm-Scrubbler-WPF[/link]\n"
        "  2. Select [bold]'File Parse Scrobbler'[/bold]\n"
        "  3. In Parser selection, choose [bold]JSON[/bold]\n"
        "  4. Click [bold]Open File[/bold] and select your formatted JSON file\n"
        "  5. Click [bold]Parse[/bold] and then [bold]Scrobble[/bold]\n"
        "\n[dim]Note: If scrobbling tracks older than 14 days, use 'Import Mode' in Scrubbler.[/dim]"
    )

    if console:
        console.print(msg)
    else:
        # Strip simple markup for plain terminal
        clean_msg = re.sub(r"\[/?(?:bold|green|cyan|dim|link=[^\]]+)\]", "", msg)
        print(clean_msg)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Google Takeout watch-history.json to Last.fm-Scrubbler JSON format."
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=Path("watch-history.json"),
        help="Path to Google Takeout watch-history.json (default: watch-history.json)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("formatted.json"),
        help="Path for formatted output JSON file(s) (default: formatted.json)",
    )
    parser.add_argument(
        "-c",
        "--chunk-size",
        type=int,
        default=2800,
        help="Maximum tracks per output file for Last.fm daily limit (default: 2800, 0 to disable)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=5,
        help="Concurrent API workers for album lookup (default: 5)",
    )
    parser.add_argument(
        "--skip-albums",
        action="store_true",
        help="Skip YouTube Music album lookup and export immediately",
    )
    parser.add_argument(
        "--only-topic",
        action="store_true",
        help="Only include tracks from 'Artist - Topic' channels (matches original JS behavior)",
    )
    parser.add_argument(
        "--cache-file",
        type=Path,
        default=Path(".ytmusic_cache.json"),
        help="Path to cache file for resolved albums (default: .ytmusic_cache.json)",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear existing album cache before running",
    )

    args = parser.parse_args()

    if not args.input.is_file():
        err = f"Error: Input file '{args.input}' not found."
        if console:
            console.print(f"[bold red]{err}[/bold red]")
            console.print(
                "[yellow]Tip: Download your YouTube watch history from Google Takeout (takeout.google.com)[/yellow]"
            )
        else:
            print(err, file=sys.stderr)
        return 1

    if args.clear_cache and args.cache_file.is_file():
        args.cache_file.unlink()
        if console:
            console.print("[dim]Album cache cleared.[/dim]")

    if console:
        console.print(f"[bold]Parsing[/bold] {args.input}...")
    else:
        print(f"Parsing {args.input}...")

    try:
        tracks = parse_watch_history(args.input, only_topic=args.only_topic)
    except Exception as e:
        if console:
            console.print(f"[bold red]Failed to parse history:[/bold red] {e}")
        else:
            print(f"Failed to parse history: {e}", file=sys.stderr)
        return 1

    if not tracks:
        msg = "No YouTube Music tracks found in watch history."
        if console:
            console.print(f"[yellow]{msg}[/yellow]")
        else:
            print(msg)
        return 0

    if console:
        console.print(
            f"Found [bold green]{len(tracks)}[/bold green] YouTube Music scrobbles."
        )
    else:
        print(f"Found {len(tracks)} YouTube Music scrobbles.")

    # Album lookup
    if not args.skip_albums:
        if not HAS_YTMUSICAPI:
            msg = (
                "[yellow]Warning: 'ytmusicapi' library is not installed. "
                "Skipping album lookup. Install it using 'pip install ytmusicapi'.[/yellow]"
            )
            if console:
                console.print(msg)
            else:
                print(msg, file=sys.stderr)
        else:
            resolver = AlbumResolver(
                cache_path=args.cache_file,
                max_workers=args.workers,
            )
            try:
                cache_hits, api_successes = resolver.resolve_all(tracks)
                resolved_total = sum(1 for t in tracks if t.get("albumName"))
                if console:
                    console.print(
                        f"Resolved albums for [bold green]{resolved_total}/{len(tracks)}[/bold green] tracks "
                        f"({cache_hits} cache hits, {api_successes} API fetches)."
                    )
                else:
                    print(
                        f"Resolved albums for {resolved_total}/{len(tracks)} tracks "
                        f"({cache_hits} cache hits, {api_successes} API fetches)."
                    )
            except KeyboardInterrupt:
                if console:
                    console.print("\n[yellow]Process interrupted by user. Saving cache and writing current progress...[/yellow]")
                else:
                    print("\nProcess interrupted. Saving cache and writing current progress...")
                resolver.save_cache()

    written_files = write_formatted_json(
        tracks, args.output, chunk_size=args.chunk_size
    )
    print_instructions(written_files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
