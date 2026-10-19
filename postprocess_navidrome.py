#!/usr/bin/env python3
"""
postprocess_navidrome.py

Enhances M4A/AAC files downloaded via yt-dlp with rich, native Navidrome tags:
1. Multi-valued artist atoms (----:com.apple.itunes:artists) using YouTube Music's
   raw structured artist array to protect band names with commas (e.g. "Tyler, The Creator").
2. High-fidelity UI display artist tag (©ART).
3. Album Artist (aART & ----:com.apple.itunes:albumartists) to eliminate album splitting.
4. Compilation tagging (cpil) for soundtracks and various artist compilations.
5. Title cleanup (stripping YouTube promotional labels like "(Official Video)", etc.).
6. Album fallback for singles to prevent "Unknown Album" grouping.
7. ISO 8601 date formatting (YYYY-MM-DD) for ©day and originaldate.
8. Standard "Music" genre tagging (©gen).
9. Automatic synchronization with a Navidrome-compatible Liked_Music.m3u8 playlist.
"""

import sys
import os
import re
import json
import glob
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

COMPILATION_KEYWORDS = [
    "soundtrack", "original broadway cast", "original motion picture",
    "various artists", "motion picture soundtrack", "original cast recording"
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
    """Tags a single M4A file for Navidrome."""
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

    # --- 1. RESOLVE ARTISTS (Extract exact boundaries) ---
    raw_artists = meta.get('artists')
    if isinstance(raw_artists, list) and raw_artists:
        # Exact list from YouTube Music API - completely immune to comma splitting!
        artists = [str(a).strip() for a in raw_artists if str(a).strip()]
    elif '----:com.apple.itunes:artists' in audio and audio['----:com.apple.itunes:artists']:
        # Preserve already-embedded plural atoms if re-running without info.json
        artists = [bytes(a).decode('utf-8', errors='ignore').strip() for a in audio['----:com.apple.itunes:artists'] if bytes(a).strip()]
    elif meta.get('creator'):
        artists = [meta['creator'].strip()]
    elif meta.get('uploader'):
        artists = [meta['uploader'].strip()]
    else:
        # Fallback to existing MP4 artist atom
        existing_art = audio.get('©ART', [''])[0]
        if existing_art:
            # Respect Navidrome separators + standard featuring
            artists = [a.strip() for a in re.split(r'\s/\s|;\s|\sfeat\.?\s|\sft\.?\s|\s+&\s+', existing_art) if a.strip()]
        else:
            artists = ["Unknown Artist"]

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
                     any(k in display_artist.lower() for k in COMPILATION_KEYWORDS)

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
    elif 'cpil' in audio:
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


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 postprocess_navidrome.py <path_to_audio_or_directory> [--keep-json]")
        sys.exit(1)

    target_path = Path(sys.argv[1]).resolve()
    keep_json = "--keep-json" in sys.argv

    if target_path.is_file():
        process_audio_file(target_path, keep_json=keep_json)
    elif target_path.is_dir():
        audio_files = sorted(list(target_path.glob("*.m4a")) + list(target_path.glob("*.mp4")))
        print(f"Scanning directory: found {len(audio_files)} audio file(s)")
        for af in audio_files:
            process_audio_file(af, keep_json=keep_json)
    else:
        print(f"Error: Target path '{target_path}' not found.")
        sys.exit(1)


if __name__ == "__main__":
    main()
