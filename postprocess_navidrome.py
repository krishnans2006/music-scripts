#!/usr/bin/env python3
"""
postprocess_navidrome.py

Enhances M4A/AAC files downloaded via yt-dlp with rich, native Navidrome tags:
1. Multi-valued artist atoms (----:com.apple.itunes:artists) using YouTube Music's
   raw structured artist array (completely immune to comma splitting; no hardcoded lists).
2. High-fidelity UI display artist tag (©ART).
3. Album Artist (aART & ----:com.apple.itunes:albumartists) to eliminate album splitting.
4. Dynamic compilation tagging (cpil) for soundtracks and various artist releases.
5. Title cleanup (stripping YouTube promotional labels like "(Official Video)", etc.).
6. Album fallback for singles to prevent "Unknown Album" grouping.
7. ISO 8601 date formatting (YYYY-MM-DD) for ©day and originaldate.
8. Standard "Music" genre tagging (©gen).
9. Library-level album harmonization:
   - Unifies release dates across tracks sharing the same (Album, AlbumArtist) to the earliest date,
     preventing date-based album splitting in Navidrome.
   - Unifies Album Artists (aART) on collaborative/soundtrack tracks dynamically without hardcoding.
10. Automatic synchronization with a Navidrome-compatible Liked_Music.m3u8 playlist.
"""

import sys
import os
import re
import json
import glob
from collections import defaultdict
from pathlib import Path
from mutagen.mp4 import MP4, MP4FreeForm

# Video clutter regex patterns to clean song titles
TITLE_CLEANUP_PATTERNS = [
    re.compile(r'\s*[\(\[]\s*official\s+(?:music\s+)?video\s*[\)\]]', re.IGNORECASE),
    re.compile(r'\s*[\(\[]\s*official\s+(?:lyric\s+)?video\s*[\)\]]', re.IGNORECASE),
    re.compile(r'\s*[\(\[]\s*official\s+audio\s*[\)\]]', re.IGNORECASE),
    re.compile(r'\s*[\(\[]\s*lyric\s+video\s*[\)\]]', re.IGNORECASE),
    re.compile(r'\s*[\(\[]\s*lyrics?\s*[\)\]]', re.IGNORECASE),
    re.compile(r'\s*[\(\[]\s*visualizer\s*[\)\]]', re.IGNORECASE),
    re.compile(r'\s*[\(\[]\s*audio\s*[\)\]]', re.IGNORECASE),
    re.compile(r'^\s*【(?:Official|MV|Music Video)】\s*', re.IGNORECASE),
    re.compile(r'\s*【(?:Official|MV|Music Video)】\s*$', re.IGNORECASE),
]

GENERIC_GENRES = {"people & blogs", "gaming", "entertainment", "general"}

# Standard industry compilation terms
COMPILATION_KEYWORDS = [
    "soundtrack", "original motion picture", "various artists",
    "motion picture soundtrack", "original cast", "compilation"
]


def clean_title(raw_title: str) -> str:
    """Removes YouTube promotional fluff from track titles."""
    title = raw_title.strip()
    for pat in TITLE_CLEANUP_PATTERNS:
        title = pat.sub('', title).strip()
    return title or raw_title.strip()


def format_iso_date(raw_date: str) -> str | None:
    """Converts YYYYMMDD or YYYY to standard ISO-8601 (YYYY-MM-DD or YYYY)."""
    if not raw_date:
        return None
    raw_date = str(raw_date).strip()
    if len(raw_date) == 8 and raw_date.isdigit():
        return f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    if len(raw_date) == 4 and raw_date.isdigit():
        return raw_date
    if re.match(r'^\d{4}-\d{2}-\d{2}$', raw_date):
        return raw_date
    return None


def format_display_artist(artists: list[str], raw_artist: str | None = None) -> str:
    """
    Constructs a clean, human-readable display string for player UIs.
    e.g.:
      ['Tyler, The Creator'] -> 'Tyler, The Creator'
      ['Madeline Merlo', 'Dustin Lynch'] -> 'Madeline Merlo & Dustin Lynch'
      ['A', 'B', 'C'] -> 'A, B & C'
    """
    if not artists:
        return raw_artist or "Unknown Artist"

    if len(artists) == 1:
        return artists[0]

    # If the raw artist already has featuring or ampersand formatting, preserve it
    if raw_artist and any(delim in raw_artist for delim in [" feat. ", " ft. ", " & "]):
        return raw_artist

    if len(artists) == 2:
        return f"{artists[0]} & {artists[1]}"

    return f"{', '.join(artists[:-1])} & {artists[-1]}"


def split_artist_string(artist_str: str) -> list[str]:
    """
    Splits an artist string using standard Navidrome delimiters: ' / ', '; ', ' feat. ', ' ft. ', ' & '.
    Used only as a fallback when YouTube Music structured JSON metadata is not available.
    """
    if not artist_str:
        return ["Unknown Artist"]

    parts = re.split(r'\s*/\s*|;\s*|\s+feat\.?\s+|\s+ft\.?\s+|\s+&\s+', artist_str.strip())
    result = [p.strip() for p in parts if p.strip()]
    return result or [artist_str.strip()]


def update_m3u8_playlist(playlist_path: Path, track_rel_path: str):
    """Maintains an M3U8 playlist with relative track paths."""
    playlist_path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = []
    if playlist_path.exists():
        with open(playlist_path, 'r', encoding='utf-8') as f:
            existing_lines = [line.strip() for line in f if line.strip()]

    # Ensure standard header
    if not existing_lines or existing_lines[0] != "#EXTM3U":
        existing_lines.insert(0, "#EXTM3U")

    if track_rel_path not in existing_lines:
        existing_lines.append(track_rel_path)
        with open(playlist_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(existing_lines) + "\n")


def process_audio_file(file_path: Path, keep_json: bool = False):
    """
    Tags a single M4A file for Navidrome.
    This function is executed per-track by yt-dlp --exec during downloads.
    It does NOT run library harmonization.
    """
    if not file_path.exists() or file_path.suffix.lower() not in ['.m4a', '.mp4', '.aac']:
        return

    # Check for accompanying .info.json from yt-dlp
    info_json_path = file_path.with_suffix('.info.json')
    meta = {}
    if info_json_path.exists():
        try:
            with open(info_json_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load info.json for {file_path.name}: {e}")

    try:
        audio = MP4(file_path)
    except Exception as e:
        print(f"Error opening MP4 {file_path}: {e}")
        return

    # --- 1. RESOLVE ARTISTS (Extract exact boundaries dynamically) ---
    raw_artists = meta.get('artists')
    if isinstance(raw_artists, list) and raw_artists:
        # Exact list directly from YouTube Music API - completely immune to comma splitting!
        artists = [str(a).strip() for a in raw_artists if str(a).strip()]
    elif '----:com.apple.itunes:artists' in audio and audio['----:com.apple.itunes:artists']:
        # Preserve already-embedded plural atoms if re-running without info.json
        artists = [bytes(a).decode('utf-8', errors='ignore').strip() for a in audio['----:com.apple.itunes:artists'] if bytes(a).strip()]
    elif meta.get('creator'):
        artists = [meta['creator'].strip()]
    elif meta.get('uploader'):
        artists = [meta['uploader'].strip()]
    else:
        # Fallback using standard music delimiters
        existing_art = audio.get('©ART', [''])[0]
        artists = split_artist_string(existing_art)

    raw_artist_str = meta.get('artist') or audio.get('©ART', [''])[0]

    # --- 2. MULTI-VALUED ATOMS (Navidrome) ---
    # Navidrome's official plural atom: ----:com.apple.itunes:artists
    audio['----:com.apple.itunes:artists'] = [MP4FreeForm(a.encode('utf-8')) for a in artists]

    # --- 3. SINGULAR DISPLAY ARTIST (©ART) ---
    display_artist = format_display_artist(artists, raw_artist_str)
    audio['©ART'] = [display_artist]

    # --- 4. TITLE CLEANUP (©nam) ---
    raw_title = meta.get('track') or meta.get('title') or audio.get('©nam', [''])[0] or file_path.stem
    track_title = clean_title(raw_title)
    audio['©nam'] = [track_title]

    # --- 5. ALBUM & ALBUM ARTIST ---
    raw_album = meta.get('album') or audio.get('©alb', [''])[0]
    if not raw_album or raw_album.strip().lower() in ['none', 'null', 'na', '']:
        album = f"{track_title} - Single"
    else:
        album = raw_album.strip()
    audio['©alb'] = [album]

    # Determine Compilation
    is_compilation = any(k in album.lower() for k in COMPILATION_KEYWORDS) or \
                     any(k in display_artist.lower() for k in COMPILATION_KEYWORDS) or \
                     any(k in str(artists).lower() for k in COMPILATION_KEYWORDS)

    raw_album_artist = meta.get('album_artist') or audio.get('aART', [''])[0]
    if raw_album_artist:
        album_artist = raw_album_artist.strip()
    elif is_compilation:
        album_artist = "Various Artists"
    else:
        album_artist = artists[0]

    audio['aART'] = [album_artist]
    audio['----:com.apple.itunes:albumartists'] = [MP4FreeForm(album_artist.encode('utf-8'))]

    if is_compilation:
        audio['cpil'] = True
    elif 'cpil' in audio and not is_compilation:
        del audio['cpil']

    # --- 6. DATE (ISO-8601: YYYY-MM-DD) ---
    raw_date = meta.get('release_date') or meta.get('upload_date') or audio.get('©day', [''])[0]
    iso_date = format_iso_date(raw_date)
    if iso_date:
        audio['©day'] = [iso_date]
        audio['----:com.apple.itunes:originaldate'] = [MP4FreeForm(iso_date.encode('utf-8'))]

    # --- 7. TRACK NUMBER ---
    # Only keep track numbers if they are authentic album track numbers
    track_num = meta.get('track_number')
    if isinstance(track_num, int) and track_num > 0:
        total_tracks = meta.get('n_entries') or 0
        audio['trkn'] = [(track_num, total_tracks)]

    # --- 8. GENRE ---
    # Default to "Music" or specific genre if provided
    raw_genre = meta.get('genre')
    if raw_genre and raw_genre.strip().lower() not in GENERIC_GENRES:
        audio['©gen'] = [raw_genre.strip()]
    else:
        audio['©gen'] = ["Music"]

    # --- 9. SAVE MP4 ---
    audio.save()
    print(f"[Navidrome Tagger] Processed: '{track_title}' by {display_artist} [Artists: {artists}]")

    # --- 10. PLAYLIST SYNC ---
    # Maintain Liked_Music.m3u8 playlist in the parent directory
    playlist_path = file_path.parent / "Liked_Music.m3u8"
    update_m3u8_playlist(playlist_path, file_path.name)

    # Clean up info.json
    if not keep_json and info_json_path.exists():
        try:
            info_json_path.unlink()
        except OSError:
            pass


def harmonize_library(directory_path: Path):
    """
    Performs dynamic, library-level harmonization to ensure Navidrome merges multi-track albums cleanly.
    Runs ONCE at the end of the entire batch download process:
    1. Standard Compilations / Soundtracks:
       If album matches generic industry terms ("soundtrack", "motion picture", "various artists", etc.),
       unifies aART to 'Various Artists' and flags cpil=True.
    2. Shared Artist Studio Albums:
       If tracks with the same album title share at least one common artist (e.g. Ed Sheeran on '+',
       The Weeknd on 'Dawn FM'), unifies aART to the shared artist.
       If tracks share the same album title but have ZERO shared artists and are not a compilation
       (e.g. Journey's 'Escape' vs Dean Lewis's 'Escape'), they are preserved as separate albums.
    3. Release Date Harmonization:
       For all tracks sharing the same (Album, AlbumArtist), harmonizes release dates to the earliest
       date, preventing Navidrome from splitting albums by differing video upload dates.
    """
    audio_files = sorted(list(directory_path.glob("*.m4a")) + list(directory_path.glob("*.mp4")))
    if not audio_files:
        return

    print(f"\n[Navidrome Harmonizer] Analyzing {len(audio_files)} files for album consistency...")

    records = []
    album_to_records = defaultdict(list)

    for f in audio_files:
        try:
            audio = MP4(f)
            alb = audio.get('©alb', [''])[0].strip()
            aart = audio.get('aART', [''])[0].strip() if 'aART' in audio else ''
            day = audio.get('©day', [''])[0].strip() if '©day' in audio else ''

            artists = []
            if '----:com.apple.itunes:artists' in audio:
                artists = [bytes(a).decode('utf-8', errors='ignore').strip() for a in audio['----:com.apple.itunes:artists'] if bytes(a).strip()]
            if not artists:
                disp_art = audio.get('©ART', [''])[0].strip()
                artists = [disp_art] if disp_art else []

            rec = {
                'path': f,
                'audio': audio,
                'album': alb,
                'aart': aart,
                'day': day,
                'artists': artists
            }
            records.append(rec)
            if alb and not alb.lower().endswith(' - single'):
                album_to_records[alb.lower()].append(rec)
        except Exception as e:
            print(f"Warning: Failed to inspect {f.name} for harmonization: {e}")

    harmonized_count = 0

    # Pass 1: Resolve Album Artist discrepancies within the same album title
    for alb_key, recs in album_to_records.items():
        if len(recs) < 2:
            continue

        sample_alb = recs[0]['album']
        is_comp = any(k in sample_alb.lower() for k in COMPILATION_KEYWORDS) or \
                  any(r['aart'].lower() == "various artists" for r in recs)

        if is_comp:
            for r in recs:
                changed = False
                if r['aart'] != "Various Artists":
                    r['audio']['aART'] = ["Various Artists"]
                    r['audio']['----:com.apple.itunes:albumartists'] = [MP4FreeForm(b"Various Artists")]
                    r['aart'] = "Various Artists"
                    changed = True
                if r['audio'].get('cpil') is not True:
                    r['audio']['cpil'] = True
                    changed = True
                if changed:
                    r['audio'].save()
                    harmonized_count += 1
            continue

        # Check for shared artists across tracks with this album title
        # Two tracks belong to the same studio album if they share at least one common artist
        all_artist_sets = [set(a.lower() for a in r['artists'] if a) for r in recs]
        shared_artists = set.intersection(*all_artist_sets) if all_artist_sets else set()

        if shared_artists:
            canonical_artist = None
            for r in recs:
                for a in r['artists']:
                    if a.lower() in shared_artists:
                        canonical_artist = a
                        break
                if canonical_artist:
                    break

            if canonical_artist:
                for r in recs:
                    if r['aart'] != canonical_artist:
                        r['audio']['aART'] = [canonical_artist]
                        r['audio']['----:com.apple.itunes:albumartists'] = [MP4FreeForm(canonical_artist.encode('utf-8'))]
                        r['aart'] = canonical_artist
                        r['audio'].save()
                        harmonized_count += 1
                        print(f"  [Harmonized aART] '{sample_alb}': Set '{r['path'].name}' aART='{canonical_artist}'")

    # Pass 2: Unify Release Dates within (Album, AlbumArtist) groups
    album_artist_groups = defaultdict(list)
    for r in records:
        alb = r['album']
        aart = r['aart']
        if alb and aart and not alb.lower().endswith(' - single'):
            album_artist_groups[(alb.lower(), aart.lower())].append(r)

    for (alb_key, aart_key), recs in album_artist_groups.items():
        if len(recs) < 2:
            continue

        valid_dates = [r['day'] for r in recs if r['day'] and re.match(r'^\d{4}', r['day'])]
        if not valid_dates:
            continue

        canonical_date = min(valid_dates)
        for r in recs:
            if r['day'] != canonical_date:
                r['audio']['©day'] = [canonical_date]
                r['audio']['----:com.apple.itunes:originaldate'] = [MP4FreeForm(canonical_date.encode('utf-8'))]
                r['day'] = canonical_date
                r['audio'].save()
                harmonized_count += 1
                print(f"  [Harmonized Date] '{r['album']}' by '{r['aart']}': '{r['path'].name}' -> Date='{canonical_date}'")

    print(f"[Navidrome Harmonizer] Complete. Harmonized {harmonized_count} item(s).")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 postprocess_navidrome.py <path_to_audio_or_directory> [--harmonize-only] [--keep-json]")
        sys.exit(1)

    keep_json = "--keep-json" in sys.argv
    harmonize_only = "--harmonize-only" in sys.argv or "--harmonize" in sys.argv

    # Filter out options to isolate target path
    positional_args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if not positional_args:
        print("Error: No target path specified.")
        sys.exit(1)

    target_path = Path(positional_args[0]).resolve()

    if target_path.is_file():
        # Single file execution (called per-download via yt-dlp --exec)
        # Harmonize is NEVER executed here.
        process_audio_file(target_path, keep_json=keep_json)
    elif target_path.is_dir():
        # Directory execution (called at the end of the download run)
        if not harmonize_only:
            audio_files = sorted(list(target_path.glob("*.m4a")) + list(target_path.glob("*.mp4")))
            print(f"Scanning directory: found {len(audio_files)} audio file(s)")
            for af in audio_files:
                process_audio_file(af, keep_json=keep_json)
        # Run library harmonization to resolve duplicate albums and mismatched dates
        harmonize_library(target_path)
    else:
        print(f"Error: Target path '{target_path}' not found.")
        sys.exit(1)


if __name__ == "__main__":
    main()
