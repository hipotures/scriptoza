# Utils - General Utilities

Collection of utility scripts for various tasks.

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
│ 8552743b │ /home/xai/DEV/scriptoza │ $12.41 │ 141k   │ 2025-12-25 18:30:50 │
│ f2af13c2 │ /home/xai/DEV/scriptoza │ $8.03  │ 102k   │ 2025-12-25 17:55:31 │
```

**2. Suma kosztów per projekt**
```
┌─────────────────────────┬────────────┬──────────┬──────────────┐
│         project         │ total_cost │ sessions │ total_tokens │
├─────────────────────────┼────────────┼──────────┼──────────────┤
│ /home/xai/DEV/scriptoza │ $34.04     │ 12       │ 376k         │
│ /home/xai/ml/kaggle     │ $1.60      │ 1        │ 24k          │
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
