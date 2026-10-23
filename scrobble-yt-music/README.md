# YouTube Music Watch History Scrobbler

A tool to parse Google Takeout YouTube Music watch history, enrich tracks with album names via YouTube Music's API, and format them for bulk scrobbling with [Last.fm-Scrubbler-WPF](https://github.com/SHOEGAZEssb/Last.fm-Scrubbler-WPF).

Python rewrite and improvement of [beebls/youtube-music-history-scrobbler](https://github.com/beebls/youtube-music-history-scrobbler).

## Improvements over the original JavaScript version

1. **Robust JSON Parsing & Extraction**:
   - Replaced fragile stringified array slicing (`JSON.stringify(subtitles).split(',')[0]...`) with native structured dict parsing.
   - Accurately parses URLs using `urllib.parse` rather than fixed 32-character slicing, preventing corrupted IDs on `music.youtube.com` URLs or URLs with query parameters (`&list=...`, `&t=...`).
   - Cleanly strips `" - Topic"` while preserving artists that do not have topic channels (Official Artist Channels / OACs).
   - Handles prefixes such as `"Watched "` and non-English counterparts without stripping valid song names.

2. **Deduplication & Local Caching**:
   - The original script re-queried the API for every single play (thousands of duplicate requests for popular songs).
   - The Python version deduplicates queries across plays and maintains a persistent cache (`.ytmusic_cache.json`). Repeated tracks resolve instantly.

3. **Rate Limiting & Concurrency Control**:
   - The original script fired 1,000 unbounded concurrent requests which caused deadlocks and API failures around ~1,900 requests.
   - The Python version uses `ThreadPoolExecutor` with controlled worker pools (default 5 workers), rate pacing, and thread-local sessions.
   - Supports graceful interrupts (`Ctrl+C` saves cached results immediately).

4. **Multi-tiered Album Resolution**:
   - Queries by video ID, and falls back to `Artist Track` song search if the video ID does not return an album.

5. **Flexible CLI & Chunking**:
   - Automatic chunking into 2,800-scrobble files (`formatted-1.json`, `formatted-2.json`, ...) respecting Last.fm's daily scrobble limit.
   - CLI flags for custom input/output paths, chunk sizes, worker counts, and skipping album lookups.
   - Progress bar via `rich`.

## Usage

```bash
# Basic run (reads watch-history.json and writes formatted.json)
python3 main.py

# Custom input/output
python3 main.py -i /path/to/watch-history.json -o formatted.json

# Skip album lookup if you only want artist + title + timestamp
python3 main.py --skip-albums

# Use more workers for faster lookups
python3 main.py -w 10
```

### CLI Options

| Flag | Description | Default |
| --- | --- | --- |
| `-i, --input` | Path to Google Takeout `watch-history.json` | `watch-history.json` |
| `-o, --output` | Path for formatted output JSON file(s) | `formatted.json` |
| `-c, --chunk-size` | Max tracks per output file (Last.fm daily cap) | `2800` (0 disables) |
| `-w, --workers` | Number of concurrent workers for API lookups | `5` |
| `--skip-albums` | Skip album lookup entirely and export immediately | `False` |
| `--only-topic` | Only include tracks from `" - Topic"` channels | `False` |
| `--cache-file` | Path to album cache file | `.ytmusic_cache.json` |
| `--clear-cache` | Clear existing album cache before running | `False` |

## How to Import to Last.fm

1. Download and run [Last.fm-Scrubbler-WPF](https://github.com/SHOEGAZEssb/Last.fm-Scrubbler-WPF).
2. Choose **File Parse Scrobbler**.
3. Select **JSON** as the parser.
4. Click **Open File** and select your generated `formatted.json` (or `formatted-1.json`).
5. Click **Parse** and then **Scrobble**.

> **Note:** Last.fm rejects scrobbles with original timestamps older than 14 days. If your history contains older tracks, enable **Import Mode** in Scrubbler to synthesize valid timestamps.
