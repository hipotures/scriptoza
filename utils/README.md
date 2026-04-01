# Utils - General Utilities

Collection of generic helper scripts.

## Current Scope

The `utils/` directory now contains only non-pipeline helpers.

The event workflow pipeline was moved out of the active utility set:

- compatibility copy: `deprecated/pipeline/`
- migration target: `/home/xai/DEV/vocatio`

If you still need the old event workflow scripts, run them from `deprecated/pipeline/`.

## Active Scripts

- `statusline.py` - Rich status line for Claude Code with SQLite session logging
- `session_stats.sh` - Session statistics
- `claude_usage_report.py` - Aggregates JSONL history into per-session and per-day totals
- `organize_by_date.py` - Safe universal organizer that groups files into `YYYYMMDD` folders from filename dates
- `safe_rename_tt.py` - Safe date-based renamer for TikTok downloads
- `scan_mp4_to_json.py` - Scans MP4 files and outputs metadata as JSON
- `install.py` - Installs selected utility scripts into a local bin directory
- `migrate.py` - Small migration helper for local data transformations

## Notes

- Event workflow and review tools are no longer active under `utils/`
- Historical pipeline scripts remain available only under `deprecated/pipeline/`
