# Scriptoza

Collection of small utility scripts organized by category. Each category has its own README with requirements and usage.

## Categories

### Video (video/)

- `rename_video_univ.py` - Universal video renaming using robust EXIF tag fallback
- `rename_video.py` - Universal video renaming (DJI, Panasonic, Sony)
- `check_4k.py` - Scans MP4 tree for 4K/non-4K classification
- `check_collisions.py` - Detects basename collisions
- `sort_video_qvr.sh` - Organizes QVR files by date
- `sort_video_sr.sh` - Organizes Screen Recordings by date
- `sort_video_dated.py` - Organizes files starting with YYYYMMDD into date folders
- `sort_dji.py` - Sorts DJI Pocket files into a separate folder
- `find_vbc.py` - Lists videos with or without VBC metadata tags

### Photo (photo/)

- `rename_photo.py` - Universal photo renaming tool (Sony RAW/JPG, Panasonic JPG)

### Utils (utils/)

- `statusline.py` - Rich status line for Claude Code with SQLite session logging
- `session_stats.sh` - Session statistics (top sessions, costs, model usage)
- `claude_usage_report.py` - Aggregates JSONL history into per-session/per-day totals
- `safe_rename_tt.py` - Safe date-based renamer for TikTok downloads
- `scan_mp4_to_json.py` - Scans MP4 files and outputs metadata as JSON

## Notes

- Follow each category README for dependencies and usage details.
- VBC (Video Batch Compression) is maintained in a separate repository: https://github.com/hipotures/vbc
