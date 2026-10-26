"""
navidrome.py - Beets companion plugin for Navidrome integration.

1. MusicBrainz & Chroma matcher helper:
   - Normalizes Unicode compatibility characters (e.g. full-width punctuation) via standard NFKC.
   - Cleans generic feature/edition/video noise from title queries and distance checks.
   - Matches artist against canonical artist, credit name, or collaborator list (e.g. MILEY -> Miley Cyrus).
   - Evaluates track distance using primary artist and clean title.
2. Navidrome multi-valued, genre & album harmonization:
   - Ensures all tracks have a valid genre (falls back to ['Music'] for unmatched tracks).
   - Preserves MusicBrainz authoritative multi-valued artists (----:com.apple.iTunes:ARTISTS).
   - Sets primary albumartist on singletons so Navidrome never splits tracks.
   - Harmonizes album release dates across matching album names upon import completion.
   - Sets compilation flag (cpil = 1) only for multi-artist albums.
3. Playlist prefix preservation:
   - Preserves the 4-digit playlist numbering prefix in filename and track tags.
"""

import os
import re
import unicodedata
from collections import defaultdict

from beets.plugins import BeetsPlugin
from beets.autotag import match, TrackInfo
from beets.autotag.distance import string_dist
from beets.library import Item
import beetsplug.musicbrainz as mb


def clean_title_for_matching(title: str) -> str:
    """Strip generic feature tags, audio/video tags, or edition labels for cleaner matching."""
    if not title:
        return ""
    title = unicodedata.normalize("NFKC", title)
    title = re.sub(r"^[【\[](?:Official|公式|MV)[】\]]\s*", "", title, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\s*[\(\[](?:From|featuring|feat\.?|ft\.?|Official|Single Version|Album Version|Radio Edit|Remaster(?:ed)?(?:\s*\d+)?|Acoustic Version|Acoustic|Audio|Visualizer|Lyric(?:s)?(?:\s*Video)?|Video|Music Video|Full Spec Edition|Taxi Driver Edition).*?[\)\]]",
        "",
        title,
        flags=re.IGNORECASE
    ).strip()
    return cleaned if cleaned else title


def get_effective_artist_title(artist: str, title: str) -> tuple[str, str]:
    """
    If title is formatted as 'Artist - Title' (standard in YouTube uploads where
    the uploader channel was stored as the artist tag), split and extract them.
    """
    artist = unicodedata.normalize("NFKC", artist) if artist else ""
    title = unicodedata.normalize("NFKC", title) if title else ""
    if " - " in title and (not artist or artist.lower() not in title.lower()):
        parts = title.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return artist, title


def get_primary_artist(artist: str) -> str:
    if not artist:
        return ""
    artist = unicodedata.normalize("NFKC", artist)
    tokens = re.split(
        r'\s*(?:,|&|\bfeaturing\b|\bfeat\.?|\bft\.?|\bwith\b|\bvs\.?|\bx\b|\/|;)\s*',
        artist,
        flags=re.IGNORECASE
    )
    return tokens[0].strip() if tokens and tokens[0].strip() else artist


def best_artist_for_info(item_artist: str, track_info: TrackInfo) -> str:
    """Find the best-matching artist representation between canonical artist, credit, and member artists."""
    candidates = [track_info.artist, getattr(track_info, "artist_credit", None)]
    if getattr(track_info, "artists", None):
        candidates.extend(track_info.artists)

    best = track_info.artist or ""
    best_dist = 1.0
    clean_item = get_primary_artist(item_artist).lower()
    for cand in candidates:
        if not cand:
            continue
        primary = get_primary_artist(cand)
        d = string_dist(clean_item, primary.lower())
        if d < best_dist:
            best_dist = d
            best = primary
    return best


def parse_collaborators(artist: str) -> list[str]:
    if not artist:
        return []
    artist = unicodedata.normalize("NFKC", artist)
    parts = re.split(
        r'\s*(?:,|&|\bfeaturing\b|\bfeat\.?|\bft\.?|\bwith\b|\bvs\.?|\bx\b|\/|;)\s*',
        artist,
        flags=re.IGNORECASE
    )
    artists = []
    for p in parts:
        clean = p.strip().strip("'\"")
        if clean and clean not in artists:
            artists.append(clean)
    return artists


# 1. MusicBrainz query builder and track distance
_orig_get_search = mb.MusicBrainzPlugin.get_search_query_with_filters


def _smart_get_search_query_with_filters(self, query_type, items, artist, name, va_likely):
    if query_type == "track":
        eff_art, eff_name = get_effective_artist_title(artist, name)
        clean_art = get_primary_artist(eff_art)
        clean_tit = clean_title_for_matching(eff_name)
        criteria = {"artist": clean_art, "recording": clean_tit}
        return "", {k: v.lower().strip() for k, v in criteria.items() if v.strip()}
    return _orig_get_search(self, query_type, items, artist, name, va_likely)


mb.MusicBrainzPlugin.get_search_query_with_filters = _smart_get_search_query_with_filters


_orig_track_distance = match.track_distance


def _smart_track_distance(item: Item, track_info: TrackInfo, incl_artist: bool = False):
    eff_art, eff_name = get_effective_artist_title(item.artist, item.title)
    clean_item_title = clean_title_for_matching(eff_name)
    primary_item_artist = get_primary_artist(eff_art)

    clean_info_title = clean_title_for_matching(track_info.title)
    primary_info_artist = best_artist_for_info(primary_item_artist, track_info)

    temp_item = Item(artist=primary_item_artist, title=clean_item_title, length=item.length)
    temp_info = TrackInfo(
        title=clean_info_title,
        track_id=track_info.track_id,
        artist=primary_info_artist,
        artist_id=track_info.artist_id,
        length=track_info.length,
        index=track_info.index,
        medium=track_info.medium,
        artist_sort=track_info.artist_sort,
        disctitle=track_info.disctitle,
        artist_credit=track_info.artist_credit,
        data_source=track_info.data_source,
        data_url=track_info.data_url,
    )
    return _orig_track_distance(temp_item, temp_info, incl_artist)


match.track_distance = _smart_track_distance


class NavidromePlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self._log.info("Navidrome plugin active: multi-artist, prefix, genre fallback, and harmonization enabled")
        self.template_fields["track_prefix"] = self._get_track_prefix
        self.register_listener("import_task_created", self.on_import_task_created)
        self.register_listener("item_imported", self.on_item_imported)
        self.register_listener("import", self.on_import_finished)

    def _get_track_prefix(self, item: Item) -> str:
        prefix = item._values_flex.get("track_prefix")
        if prefix:
            return str(prefix)
        path_str = item.path.decode("utf-8", "ignore") if isinstance(item.path, bytes) else str(item.path or "")
        m = re.match(r"^(\d{4})\s*-\s*", os.path.basename(path_str))
        if m:
            prefix = m.group(1)
            item._values_flex["track_prefix"] = prefix
            return prefix
        if getattr(item, "track", None):
            return f"{item.track:04d}"
        return "0000"

    def on_import_task_created(self, session, task):
        items = task.imported_items() if hasattr(task, "imported_items") else ([task.item] if hasattr(task, "item") else [])
        for item in items:
            path_str = item.path.decode("utf-8", "ignore") if isinstance(item.path, bytes) else str(item.path or "")
            m = re.match(r"^(\d{4})\s*-\s*", os.path.basename(path_str))
            if m:
                item._values_flex["track_prefix"] = m.group(1)

    def on_item_imported(self, lib, item: Item):
        changed = False

        # Set track number to playlist order index if track_prefix is present
        prefix = item._values_flex.get("track_prefix")
        if not prefix:
            path_str = item.path.decode("utf-8", "ignore") if isinstance(item.path, bytes) else str(item.path or "")
            m = re.match(r"^(\d{4})\s*-\s*", os.path.basename(path_str))
            if m:
                prefix = m.group(1)
                item._values_flex["track_prefix"] = prefix

        if prefix:
            try:
                new_track = int(prefix)
                if item.track != new_track:
                    item.track = new_track
                    item.tracktotal = None
                    changed = True
            except (ValueError, TypeError):
                pass

        # Prefer MusicBrainz authoritative multi-valued artists if already populated
        if not item.artists:
            collabs = parse_collaborators(item.artist)
            if len(collabs) > 1:
                item.artists = collabs
                changed = True
            elif item.artist:
                item.artists = [item.artist]
                changed = True

        # Ensure singletons have a primary albumartist so Navidrome doesn't split tracks
        primary_art = item.artists[0] if item.artists else get_primary_artist(item.artist)
        if not item.albumartist and primary_art:
            item.albumartist = primary_art
            item.albumartists = [primary_art]
            changed = True

        # Ensure all tracks have a genre tag (fallback to ['Music'] for unmatched tracks)
        if not getattr(item, "genres", None):
            item.genres = ["Music"]
            changed = True

        if changed:
            item.store()
            item.try_write()

    def on_import_finished(self, lib, paths):
        """Harmonize album release dates and compilation flag across imported albums."""
        albums = defaultdict(list)
        for item in lib.items():
            if item.album:
                albums[item.album].append(item)

        for album_name, items in albums.items():
            if len(items) <= 1:
                continue

            # Determine canonical date (earliest non-zero year)
            valid_years = [i.year for i in items if i.year and i.year > 0]
            canonical_year = min(valid_years) if valid_years else None

            # Check if multi-artist compilation based on primary artist
            primary_artists = {get_primary_artist(i.artist) for i in items}
            is_comp = len(primary_artists) > 1
            canonical_albumartist = "Various Artists" if is_comp else list(primary_artists)[0]

            for item in items:
                updated = False
                if canonical_year and item.year != canonical_year:
                    item.year = canonical_year
                    updated = True
                if is_comp and not item.comp:
                    item.comp = True
                    updated = True
                if item.albumartist != canonical_albumartist:
                    item.albumartist = canonical_albumartist
                    item.albumartists = [canonical_albumartist]
                    updated = True
                if updated:
                    item.store()
                    item.try_write()

        self._log.info("Navidrome album harmonization completed.")
