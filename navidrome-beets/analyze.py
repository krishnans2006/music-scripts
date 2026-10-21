import os
import sys
from mutagen.mp4 import MP4
from collections import defaultdict


def analyze_results(final_dir: str):
    top_level_files = []
    subdir_files = []

    for root, dirs, files in os.walk(final_dir):
        for f in files:
            if not f.endswith(('.m4a', '.mp4')):
                continue
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, final_dir)
            if os.path.dirname(rel_path) == "":
                top_level_files.append(rel_path)
            else:
                subdir_files.append(rel_path)

    total_files = len(top_level_files) + len(subdir_files)
    print(f"Total processed files: {total_files}")
    print(f"  Top-level files:     {len(top_level_files)}")
    print(f"  Subdirectory files:  {len(subdir_files)}")

    # Tag analysis
    albums = defaultdict(list)
    tracks_with_lyrics = 0
    tracks_with_mbid = 0
    collab_tracks = 0

    for f in top_level_files + subdir_files:
        full_path = os.path.join(final_dir, f)
        m = MP4(full_path)
        artist = m.get('\xa9ART', [''])[0]
        title = m.get('\xa9nam', [''])[0]
        album = m.get('\xa9alb', [''])[0]
        albumartist = m.get('aART', [''])[0]
        date = m.get('\xa9day', [''])[0]

        artists_tag = m.get('----:com.apple.iTunes:ARTISTS')
        lyrics = m.get('\xa9lyr', [''])[0]

        mb_track_vals = m.get('----:com.apple.iTunes:MusicBrainz Track Id')
        mb_trackid = mb_track_vals[0] if mb_track_vals else None
        mb_artist_vals = m.get('----:com.apple.iTunes:MusicBrainz Artist Id')
        mb_artistid = mb_artist_vals[0] if mb_artist_vals else None
        mb_album_vals = m.get('----:com.apple.iTunes:MusicBrainz Album Id')
        mb_albumid = mb_album_vals[0] if mb_album_vals else None

        mb_trackid_str = mb_trackid.decode('utf-8', errors='ignore') if mb_trackid else None
        mb_artistid_str = mb_artistid.decode('utf-8', errors='ignore') if mb_artistid else None
        mb_albumid_str = mb_albumid.decode('utf-8', errors='ignore') if mb_albumid else None

        info = {
            "path": f,
            "title": title,
            "artist": artist,
            "album": album,
            "albumartist": albumartist,
            "date": date,
            "mb_trackid": mb_trackid_str,
            "mb_albumid": mb_albumid_str,
            "has_lyrics": bool(lyrics),
            "artists": [a.decode('utf-8', errors='ignore') if isinstance(a, bytes) else str(a) for a in artists_tag] if artists_tag else []
        }

        if info["mb_trackid"]:
            tracks_with_mbid += 1
        if info["has_lyrics"]:
            tracks_with_lyrics += 1
        if len(info["artists"]) > 1:
            collab_tracks += 1

        if album:
            albums[(album, albumartist)].append(info)

    print("\n=== MATCH & FEATURE STATISTICS ===")
    print(f"Total files:                           {total_files}")
    print(f"MusicBrainz Track Matched:             {tracks_with_mbid} ({tracks_with_mbid/total_files*100:.1f}%)")
    print(f"As-Is Fallback:                        {total_files - tracks_with_mbid} ({(total_files - tracks_with_mbid)/total_files*100:.1f}%)")
    print(f"Embedded Lyrics Present (©lyr):        {tracks_with_lyrics} ({tracks_with_lyrics/total_files*100:.1f}%)")
    print(f"Multi-Valued Artists Present:          {collab_tracks} collaboration tracks")

    print("\n=== MULTI-TRACK ALBUM GROUPING ===")
    multi_albums = {k: v for k, v in albums.items() if len(v) > 1}
    print(f"Multi-track albums count: {len(multi_albums)}")
    for (alb, art), items in sorted(multi_albums.items()):
        dates = set(i['date'] for i in items)
        matched = sum(1 for i in items if i['mb_trackid'])
        print(f"Album: '{alb}' by '{art}' ({len(items)} tracks, {matched}/{len(items)} MB-matched, Date: {dates})")
        for i in items:
            mb_str = f"MBID: {i['mb_trackid'][:8]}..." if i['mb_trackid'] else "NO_MBID"
            print(f"   - {i['title']} ({mb_str}, Lyrics: {'Yes' if i['has_lyrics'] else 'No'})")

    print("\n=== SAMPLE COLLABORATIONS (Navidrome Multi-Valued Tags) ===")
    sample_collabs = [f for f in top_level_files + subdir_files if len(MP4(os.path.join(final_dir, f)).get('----:com.apple.iTunes:ARTISTS', [])) > 1]
    for sc in sample_collabs[:5]:
        m = MP4(os.path.join(final_dir, sc))
        title = m.get('\xa9nam', [''])[0]
        artist = m.get('\xa9ART', [''])[0]
        albumartist = m.get('aART', [''])[0]
        artists = [a.decode('utf-8', errors='ignore') for a in m.get('----:com.apple.iTunes:ARTISTS', [])]
        print(f"   Track: '{title}'")
        print(f"     Display Artist (©ART): '{artist}'")
        print(f"     Album Artist (aART):   '{albumartist}'")
        print(f"     ARTISTS (Multi-Valued): {artists}")


if __name__ == "__main__":
    analyze_results(sys.argv[1] if len(sys.argv) > 1 else "navidrome-beets/final")
