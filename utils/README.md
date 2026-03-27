# Utils - General Utilities

Collection of utility scripts for various tasks.

## Event Media Workflow

### generate_photo_proxy_jpg.py

Generate fast proxy JPG files from exported photo CSV rows into the day workspace.

**Features:**
- Reads exported `p-*.csv` files from `DAY/_workspace/`
- Writes proxy JPG files to `DAY/_workspace/proxy_jpg/<stream>/`
- Uses `magick` with `-auto-orient` when available
- Resizes to a configurable longer-edge target instead of percentage scaling
- Supports stream filtering and `--max-files` limits for quick review passes
- Writes `photo_proxy_manifest.csv` with source/proxy/status rows

**Usage:**

```bash
# Generate 100 sample proxies for one stream
python3 utils/generate_photo_proxy_jpg.py /path/to/day/20260323 --streams p-a7r5 --max-files 100

# Generate all proxies for one stream with a larger review size
python3 utils/generate_photo_proxy_jpg.py /path/to/day/20260323 --streams p-a7r5 --long-edge 1200

# Regenerate existing proxies after confirmation
python3 utils/generate_photo_proxy_jpg.py /path/to/day/20260323 --streams p-a7r5 --overwrite
```

**Notes:**
- By default the script continues and skips existing proxy JPG files without prompting
- In continue mode, `--max-files N` means "create up to N new missing proxy files"
- In overwrite mode, `--max-files N` means "process the first N selected rows"

**Output:**
- Proxy JPG files: `DAY/_workspace/proxy_jpg/<stream>/*.jpg`
- Manifest: `DAY/_workspace/photo_proxy_manifest.csv`

### build_performance_proxy_index.py

Build a JSON index that groups assigned proxy JPG files by performance.

**Features:**
- Reads `DAY/_workspace/photo_assignments.csv`
- Resolves proxy JPG paths from `DAY/_workspace/proxy_jpg/<stream>/`
- Groups photos by performance number
- Stores the first available proxy path for each performance
- Writes one JSON file for the desktop review GUI

**Usage:**

```bash
python3 utils/build_performance_proxy_index.py /path/to/day/20260323
```

**Output:**
- `DAY/_workspace/performance_proxy_index.json`

### review_performance_proxy_gui.py

Open a simple PySide6 desktop viewer for browsing assigned proxy JPG files per performance.

**Features:**
- Left tree grouped by performance number
- First proxy preview icon shown per performance
- `Space` expands or collapses the current performance
- `Left` and `Right` move to the previous or next performance
- `1` switches to single-preview mode
- `2` switches to dual-preview mode with the first and last proxy side by side for the selected performance
- `I` toggles the info panel with metadata for the selected performance or photo
- `H` shows a keyboard help dialog
- `R` asks for confirmation and resets `review_state.json` to the first-run state
- `S` splits the current set from the selected photo into a new named set
- Preloads first and last performance previews in the background
- Unreviewed performances are shown in bold until they are opened once
- Saves review state to `DAY/_workspace/review_state.json`
- Autosaves every 10 seconds and writes a `.old` backup before replacing the current state file

**Usage:**

```bash
python3 utils/review_performance_proxy_gui.py /path/to/day/20260323
```

**Output:**
- `DAY/_workspace/review_state.json`
- `DAY/_workspace/review_state.json.old`

## 📊 Claude Code Session Management

Suite of tools for tracking, analyzing, and managing Claude Code sessions with SQLite-based logging.

### statusline.py

Custom colorful status line for Claude Code with Rich formatting and automatic SQLite logging.

**Features:**
- 2-line Rich-formatted status display
- Real-time session metrics (tokens, cost, duration)
- Git branch and diff stats
- Automatic logging to SQLite database
- Demo mode for testing

**Usage:**

```bash
# Normal operation (called by Claude Code via statusline hook)
echo '{"model": {...}, "cost": {...}}' | python utils/statusline.py

# Test with demo data
python utils/statusline.py --demo
```

**Output Example:**

```
 Sonnet 4.5     In:  14.8k  Ctx: 49.9k  ⎇ main
 DEV/scriptoza  Out:  4.3k  USD:  0.31  (+112,-20)
```

**Database:**

All sessions are automatically logged to `~/.claude/db/sessions.db` with:
- Session metadata (model, project, version)
- Cost and duration metrics
- Token usage (input, output, cache)
- Full JSON for future reference

**Schema:**

```sql
sessions (
    session_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    model_id TEXT,
    model_name TEXT,
    project_dir TEXT,
    total_cost_usd REAL,
    total_input_tokens INTEGER,
    total_output_tokens INTEGER,
    raw_json TEXT NOT NULL,
    ...
)
```

### session_stats.sh

Comprehensive session statistics and analytics dashboard.

**Features:**
- Top 10 most expensive sessions
- Cost per project summary
- Daily cost and token breakdown
- Active sessions today
- Model usage statistics
- Overall totals

**Usage:**

```bash
./utils/session_stats.sh
```

**Output Sections:**

**1. Top 10 najdroższych sesji**
```
┌──────────┬─────────────────────────┬────────┬────────┬─────────────────────┐
│    id    │         project         │  cost  │ tokens │     last_update     │
├──────────┼─────────────────────────┼────────┼────────┼─────────────────────┤
│ 8552743b │ /path/to/project-a      │ $12.41 │ 141k   │ 2025-12-25 18:30:50 │
│ f2af13c2 │ /path/to/project-a      │ $8.03  │ 102k   │ 2025-12-25 17:55:31 │
```

**2. Suma kosztów per projekt**
```
┌─────────────────────────┬────────────┬──────────┬──────────────┐
│         project         │ total_cost │ sessions │ total_tokens │
├─────────────────────────┼────────────┼──────────┼──────────────┤
│ /path/to/project-a      │ $34.04     │ 12       │ 376k         │
│ /path/to/project-b      │ $1.60      │ 1        │ 24k          │
```

**3. Cost & Tokens per day**
```
┌────────────┬──────────┬────────┬───────────┬────────────┬──────┐
│    date    │ sessions │  cost  │ in_tokens │ out_tokens │ time │
├────────────┼──────────┼────────┼───────────┼────────────┼──────┤
│ 2025-12-25 │ 13       │ $35.80 │ 421k      │ 403k       │ 9.5h │
│ 2025-12-24 │ 8        │ $18.20 │ 245k      │ 198k       │ 5.2h │
```

**4. Sesje dzisiaj**
```
┌──────────┬────────────┬────────┬────────┐
│    id    │ model_name │  cost  │ tokens │
├──────────┼────────────┼────────┼────────┤
│ 8552743b │ Sonnet 4.5 │ $12.41 │ 141k   │
│ f2af13c2 │ Sonnet 4.5 │ $8.03  │ 102k   │
```

**5. Podsumowanie całkowite**
```
┌────────────────┬────────────┬──────────┬───────────┬────────────┐
│ total_sessions │ total_cost │ total_in │ total_out │ total_time │
├────────────────┼────────────┼──────────┼───────────┼────────────┤
│ 13             │ $35.64     │ 418k     │ 401k      │ 9.5h       │
```

**6. Statystyki per model**
```
┌────────────┬──────────┬────────────┬──────────┐
│ model_name │ sessions │ total_cost │ avg_cost │
├────────────┼──────────┼────────────┼──────────┤
│ Sonnet 4.5 │ 11       │ $33.73     │ $3.0661  │
│ Opus 4.5   │ 2        │ $1.91      │ $0.9554  │
```

**Requirements:**
- SQLite3
- Bash with box table formatting support

### claude_usage_report.py

Aggregate token usage from Claude Code JSONL history by session, model, and day.

**Features:**
- Scans `~/.claude/projects/**.jsonl`
- Outputs CSV/TSV with input/output + cache read/write tokens
- Optional estimated cost based on hardcoded pricing

**Usage:**

```bash
# CSV output (default)
uv run python utils/claude_usage_report.py > /tmp/claude_usage.csv

# TSV output
uv run python utils/claude_usage_report.py --format tsv

# Include estimated cost
uv run python utils/claude_usage_report.py --include-cost > /tmp/claude_usage_with_cost.csv
```

**Output Columns:**
- `date`
- `session_id`
- `model`
- `input_tokens`
- `output_tokens`
- `cache_write_tokens`
- `cache_read_tokens`
- `cost_usd` (only with `--include-cost`)

### Custom SQL Queries

You can run custom queries directly on the database:

```bash
# Most expensive sessions
sqlite3 ~/.claude/db/sessions.db "
SELECT
    substr(session_id, 1, 8) as id,
    project_dir,
    total_cost_usd,
    total_output_tokens
FROM sessions
ORDER BY total_cost_usd DESC
LIMIT 5;"

# Sessions this week
sqlite3 ~/.claude/db/sessions.db "
SELECT
    date(timestamp) as date,
    COUNT(*) as sessions,
    SUM(total_cost_usd) as cost
FROM sessions
WHERE date(timestamp) >= date('now', '-7 days')
GROUP BY date(timestamp);"

# Extract full JSON for a session
sqlite3 ~/.claude/db/sessions.db "
SELECT raw_json
FROM sessions
WHERE session_id LIKE '8552743b%';" | jq .
```

### Setup for New Users

**1. Configure Claude Code statusline hook:**

Edit `~/.claude/settings.json` and add:

```json
{
  "hooks": {
    "statusline": "python ~/DEV/scriptoza/utils/statusline.py"
  }
}
```

**2. View statistics:**

```bash
./utils/session_stats.sh
```

Sessions are automatically logged to SQLite database on first run.

### Database Location

- **Database:** `~/.claude/db/sessions.db`
- **Old logs:** `~/.claude/log/statusline.log` (deprecated)

### Update Strategy

The system uses **INSERT OR REPLACE** strategy:
- One record per session (no duplicates)
- Each statusline call updates the session record
- `first_seen` preserved, `timestamp` updated
- Old logs had 100+ entries per session, new DB has 1 entry per session

---

## 🎵 Other Utilities

### export_event_media_csv.py

Export normalized media metadata for a single event day into per-stream CSV files stored in that day's `_workspace/` directory.

### Expected Day Layout

The script works on one day directory at a time, for example:

```bash
/path/to/day/20260323/
├── p-a7r5/
├── v-a7r5/
├── v-gh7/
├── v-pocket3/
└── _workspace/
```

- `p-a7r5` - Sony A7R5 photos
- `v-a7r5` - Sony A7R5 video
- `v-gh7` - Panasonic GH7 video
- `v-pocket3` - DJI Pocket 3 video
- `bvr/` is ignored on purpose

### Features

- Works on a single day directory, not the event root
- Writes one CSV per selected stream into `DAY/_workspace/`
- Supports selective rescan with `--targets`, for example `p-a7r5` or `v-gh7`
- Shows progress for both selected streams and processed files
- Exports raw timestamp tags alongside normalized fields so later merge steps can work only on CSV files
- Skips symlinked duplicate files inside stream folders

### Timestamp Mapping

Normalized fields are written with stable names like `start_local`, `end_local`, `duration_seconds`, `device`, and `stream_id`.

- `p-a7r5`: `start_local` comes from EXIF timestamps with fallback to file dates
- `v-a7r5`: `start_local` comes from normalized video metadata with fallback to file dates
- `v-pocket3`: `start_local` comes from normalized video metadata with fallback to file dates
- `v-gh7`: `start_local` comes from normalized video metadata with fallback to file dates

The CSV keeps raw fields such as:

- `create_date_raw`
- `track_create_date_raw`
- `media_create_date_raw`
- `datetime_original_raw`
- `subsec_datetime_original_raw`
- `subsec_create_date_raw`
- `file_modify_date_raw`
- `file_create_date_raw`

This allows a later merge step to use one normalized schema while preserving device-specific source tags for debugging.

For `2026-03-23` and `2026-03-24` in `Europe/Warsaw`, the working timeline should be treated as local time. The exporter does not use timestamps parsed from filenames.

### Usage

```bash
# List detected streams for one day
python utils/export_event_media_csv.py /path/to/day/20260323 --list-targets

# Export all detected streams into DAY/_workspace/
python utils/export_event_media_csv.py /path/to/day/20260323

# Rescan only selected streams
python utils/export_event_media_csv.py /path/to/day/20260323 --targets p-a7r5 v-gh7
```

### Output

- `DAY/_workspace/p-a7r5.csv`
- `DAY/_workspace/v-a7r5.csv`
- `DAY/_workspace/v-gh7.csv`
- `DAY/_workspace/v-pocket3.csv`
- `DAY/_workspace/summary.csv`

### merge_event_media_csv.py

Merge per-stream CSV files from `DAY/_workspace/` into one normalized day-level CSV.

### Features

- Works on one day directory at a time
- Reads only `p-*.csv` and `v-*.csv` from `DAY/_workspace/`
- Supports `--media-type video|photo|all`, with `video` as the default
- Keeps `stream_id`, `device`, and `media_type` in the merged output
- Preserves normalized fields and raw source timestamp fields
- Supports selective merge with `--targets`

### Usage

```bash
# List mergeable stream CSV files
python utils/merge_event_media_csv.py /path/to/day/20260323 --list-targets

# Merge all video stream CSV files from DAY/_workspace/ into merged_video.csv
python utils/merge_event_media_csv.py /path/to/day/20260323

# Merge only selected video streams
python utils/merge_event_media_csv.py /path/to/day/20260323 --targets v-gh7 v-pocket3

# Merge photo streams into merged_photo.csv
python utils/merge_event_media_csv.py /path/to/day/20260323 --media-type photo

# Merge both photo and video streams into merged_media.csv
python utils/merge_event_media_csv.py /path/to/day/20260323 --media-type all
```

### Output

- `DAY/_workspace/merged_video.csv` for `--media-type video`
- `DAY/_workspace/merged_photo.csv` for `--media-type photo`
- `DAY/_workspace/merged_media.csv` for `--media-type all`

The merged file uses one stable schema across photo and video rows. Photo-only or video-only fields remain empty where they do not apply.

### estimate_video_sync_map.py

Estimate per-stream constant sync corrections for video using audio correlation on overlapping clips.

### Features

- Works on one day directory at a time
- Reads `DAY/_workspace/merged_video.csv`
- Auto-selects the reference stream with the longest total duration unless `--reference-stream` is provided
- Finds overlapping clip pairs between the reference stream and each target stream
- Extracts short audio windows with `ffmpeg` and estimates corrections with cross-correlation
- Writes both a filtered `sync_map.csv` and detailed `sync_diagnostics.csv`

### Usage

```bash
# Estimate sync corrections for all non-reference video streams
python utils/estimate_video_sync_map.py /path/to/day/20260323

# Use an explicit reference stream
python utils/estimate_video_sync_map.py /path/to/day/20260323 --reference-stream v-gh7
```

### Output

- `DAY/_workspace/sync_map.csv`
- `DAY/_workspace/sync_diagnostics.csv`

### apply_video_sync_map.py

Apply `sync_map.csv` corrections to `merged_video.csv` and write a synced video timeline CSV.

### Features

- Works on one day directory at a time
- Reads `DAY/_workspace/merged_video.csv` and `DAY/_workspace/sync_map.csv`
- Writes `start_synced` and `end_synced` per clip
- Preserves the original metadata-based `start_local` and `end_local`

### Usage

```bash
python utils/apply_video_sync_map.py /path/to/day/20260323
```

### Output

- `DAY/_workspace/merged_video_synced.csv`

### transcribe_video_batch.py

Batch transcription wrapper for WhisperX using synced video rows from `merged_video_synced.csv`.

### Features

- Works on one day directory at a time
- Uses `.venv/bin/whisperx` when available
- Defaults to `model=large`, `device=cuda`, `compute_type=float16`, `batch_size=16`, `chunk_size=10`, `threads=8`, `language=pl`, `output_format=json`, and disabled alignment
- Defaults to the reference stream from `sync_map.csv`; `--all-streams` or `--streams ...` can override that
- Writes transcripts to `DAY/_workspace/transcripts/<stream_id>/`
- Writes one manifest CSV for downstream processing
- Marks empty JSON transcripts as `done_empty` in the manifest when no segments are detected
- Uses fixed-width progress counters so `completed/total` stays vertically aligned across tasks
- Shows the current stream name on the `Streams` row while `Files` remains a global file counter
- Handles `Ctrl+C` gracefully by finishing the current file, writing the manifest, and stopping without a traceback
- Skips existing outputs unless `--force` is used

### Usage

```bash
# List available streams
python utils/transcribe_video_batch.py /path/to/day/20260323 --list-streams

# Transcribe the reference stream only
python utils/transcribe_video_batch.py /path/to/day/20260323

# Transcribe specific streams
python utils/transcribe_video_batch.py /path/to/day/20260323 --streams v-pocket3 v-gh7

# Transcribe all video streams
python utils/transcribe_video_batch.py /path/to/day/20260323 --all-streams

# Skip very short clips during selection
python utils/transcribe_video_batch.py /path/to/day/20260323 --min-duration-seconds 60

# Re-enable alignment explicitly
python utils/transcribe_video_batch.py /path/to/day/20260323 --align
```

### Output

- `DAY/_workspace/transcripts/<stream_id>/<video_basename>.json`
- `DAY/_workspace/transcripts_manifest.csv`

Timestamp-bearing formats:

- `json` - best for automatic parsing
- `vtt` - yes, includes timestamps
- `srt` - yes, includes timestamps
- `tsv` - yes, includes timestamps
- `txt` - no timestamps

### transcribe_video_batch_api.py

Batch transcription wrapper for WhisperX using the Python API so one loaded model can be reused across many clips.

### Features

- Works on one day directory at a time
- Loads the WhisperX model once per run instead of once per clip
- Defaults to `model=large`, `device=cuda`, `compute_type=float16`, `batch_size=16`, `chunk_size=10`, `threads=8`, `language=pl`, `output_format=json`, and disabled alignment
- Defaults to the reference stream from `sync_map.csv`; `--all-streams` or `--streams ...` can override that
- Writes transcripts to `DAY/_workspace/transcripts/<stream_id>/`
- Writes one manifest CSV for downstream processing
- Handles `Ctrl+C` gracefully by finishing the current file, writing the manifest, and stopping without a traceback

### Usage

```bash
# List available streams
python utils/transcribe_video_batch_api.py /path/to/day/20260323 --list-streams

# Transcribe the reference stream only
python utils/transcribe_video_batch_api.py /path/to/day/20260323

# Transcribe specific streams
python utils/transcribe_video_batch_api.py /path/to/day/20260323 --streams v-pocket3

# Re-enable alignment explicitly
python utils/transcribe_video_batch_api.py /path/to/day/20260323 --align
```

### Output

- `DAY/_workspace/transcripts/<stream_id>/<video_basename>.json`
- `DAY/_workspace/transcripts_manifest.csv`

### extract_announcement_candidates.py

Parse WhisperX JSON transcripts and extract candidate performance announcements like `numer 1` into one CSV with absolute local timestamps.

### Features

- Works on one day directory at a time
- Reads `DAY/_workspace/merged_video_synced.csv`
- Scans transcript JSON files from `DAY/_workspace/transcripts/<stream_id>/`
- Converts segment-relative timestamps into absolute local timestamps using `start_synced`
- Extracts `numer` and `nr` matches with digits or Polish number words
- Writes one candidate CSV for downstream timeline building

### Usage

```bash
# List transcript streams that already have JSON files
python utils/extract_announcement_candidates.py /path/to/day/20260323 --list-streams

# Parse every available transcript stream
python utils/extract_announcement_candidates.py /path/to/day/20260323

# Parse only selected streams
python utils/extract_announcement_candidates.py /path/to/day/20260323 --streams v-pocket3
```

### Output

- `DAY/_workspace/announcement_candidates.csv`

### build_performance_timeline.py

Convert announcement candidates into performance intervals by starting each item after its announcement and ending it just before the next announcement.

### Features

- Works on one day directory at a time
- Reads `DAY/_workspace/announcement_candidates.csv`
- Merges duplicate candidate rows for the same performance number when they are close in time
- Writes `start_local` and `end_local` intervals with configurable start and end buffers
- Marks the last item as `open_end` until a later announcement is available

### Usage

```bash
python utils/build_performance_timeline.py /path/to/day/20260323
```

### Output

- `DAY/_workspace/performance_timeline.csv`

### assign_photos_to_timeline.py

Assign exported photo rows to performance intervals from `performance_timeline.csv` and write reviewable CSV outputs without generating any move commands.

### Features

- Works on one day directory at a time
- Reads `DAY/_workspace/p-*.csv`
- Reads `DAY/_workspace/performance_timeline.csv`
- Supports a constant photo timestamp offset for clock correction
- Marks rows close to performance boundaries into a separate review CSV
- Keeps photos outside known intervals in an unassigned CSV

### Usage

```bash
# List available photo streams
python utils/assign_photos_to_timeline.py /path/to/day/20260323 --list-streams

# Assign photos with default settings
python utils/assign_photos_to_timeline.py /path/to/day/20260323

# Assign only one photo stream with a manual offset
python utils/assign_photos_to_timeline.py /path/to/day/20260323 --streams p-a7r5 --photo-offset-seconds 0
```

### Output

- `DAY/_workspace/photo_assignments.csv`
- `DAY/_workspace/photo_review.csv`
- `DAY/_workspace/photo_unassigned.csv`
- `DAY/_workspace/photo_assignment_summary.csv`

### generate_mv_commands_from_timeline.py

Generate a shell script with `mkdir -p` and `mv` commands from exported photo CSV files and a timeline CSV containing performance intervals.

### Timeline CSV Columns

- `day`
- `performance_number`
- `start_local`
- `end_local`
- optional `target_dir`

### Usage

```bash
python utils/generate_mv_commands_from_timeline.py \
  /path/to/day/20260323/_workspace \
  /path/to/performance_timeline.csv \
  --output-script /path/to/mv_commands.sh
```

### organize_by_date.py

Safe universal organizer that moves files into `YYYYMMDD/` folders based on date patterns found in filenames.

**Features:**
- Works with arbitrary regular files, not just media
- Recognizes dates anywhere in the filename
- Supports smart recursion prompt, `--recursive`, and `--no-recursive`
- Dry-run support
- Never overwrites or auto-resolves destination conflicts
- Reports conflicts and move errors for manual review

**Usage:**

```bash
# Dry run in current directory
python utils/organize_by_date.py --dry-run

# Organize a directory recursively
python utils/organize_by_date.py /path/to/files --recursive
```

**Supported Date Patterns:**
- `YYYYMMDD_HHMMSS`
- `YYYY-MM-DD`
- `YYYY_MM_DD`
- `YYYY.MM.DD`
- plain `YYYYMMDD`

**Examples:**

```
Screen_Recording_20260126_221000_TikTok.mp4 -> 20260126/
20250325_083514_5728x3024_60fps_4965761424.mov -> 20250325/
```

### safe_rename_tt.py

Safe, multi-format date-based renamer for TikTok downloads.

**Features:**
- Parent directory as filename prefix
- Multiple date format support
- Dry-run by default
- Prevents overwriting
- Sets file timestamps to match date

**Usage:**

```bash
# Dry run (default)
python utils/safe_rename_tt.py /path/to/tiktok/downloads/

# Execute renames
python utils/safe_rename_tt.py /path/to/tiktok/downloads/ --execute
```

**Supported Formats:**
- `YYYYMMDD` (e.g., `20231225`)
- `YYYY-MM-DD` (e.g., `2023-12-25`)
- `DD-MM-YYYY` (e.g., `25-12-2023`)

**Example:**

```
Input:  /downloads/tiktok/2023-12-25_video.mp4
Output: /downloads/tiktok/tiktok_20231225_000.mp4
```

### fix_vbc_tags.py

Adds missing VBC metadata tags to MP4 files.

**Features:**
- Adds VBC standard tags (Encoder, FinishedAt, OriginalName, OriginalSize)
- Uses file system dates as fallback
- Dry-run support
- Batch processing

**Tags Added:**
- `Encoder`: "VBC (Video Batch Compression)"
- `FinishedAt`: File modification time
- `OriginalName`: Current filename
- `OriginalSize`: Current file size

**Usage:**

```bash
# Dry run
python utils/fix_vbc_tags.py /path/to/videos/

# Execute
python utils/fix_vbc_tags.py /path/to/videos/ --execute
```

**Requirements:**
- ExifTool

---

## Dependencies

**Claude Code Session Management:**
- Python 3.12+
- Rich (for statusline formatting)
- SQLite3 (built-in)

**Other Utilities:**
- ExifTool (for fix_vbc_tags.py)

Install with:
```bash
uv add rich
# or
pip install rich
```

## License

Part of Scriptoza collection.
