# Scriptoza

Collection of small utility scripts organized by category. Each category has its own README with requirements and usage.

## Categories

### Video (video/)

- `rename_video_univ.py` - Universal video renaming using robust EXIF tag fallback
- `check_4k.py` - Scans MP4 tree for 4K/non-4K classification
- `check_collisions.py` - Detects basename collisions
- `sort_video_qvr.sh` - Organizes QVR files by date
- `sort_video_sr.sh` - Organizes Screen Recordings by date
- `sort_video_dated.py` - Organizes files starting with YYYYMMDD into date folders
- `sort_dji.py` - Sorts DJI Pocket files into a separate folder
- `find_vbc.py` - Lists videos with or without VBC metadata tags
- `review_large_mp4.py` - Interactively reviews and cleans up N largest MP4 files

### Photo (photo/)

- `rename_photo.py` - Universal photo renaming tool (Sony RAW/JPG, Panasonic JPG)
- `convert_hif_to_jpg.py` - Converts HIF/HEIF files from the current directory into resized JPG files in a `pX` subfolder

### Utils (utils/)

- `statusline.py` - Rich status line for Claude Code with SQLite session logging
- `session_stats.sh` - Session statistics (top sessions, costs, model usage)
- `claude_usage_report.py` - Aggregates JSONL history into per-session/per-day totals
- `organize_by_date.py` - Safe universal organizer that groups files into YYYYMMDD folders from filename dates
- `safe_rename_tt.py` - Safe date-based renamer for TikTok downloads
- `scan_mp4_to_json.py` - Scans MP4 files and outputs metadata as JSON
- `export_event_media_csv.py` - Exports per-day media metadata from `p-*/v-*` device folders into `_workspace/*.csv`
- `merge_event_media_csv.py` - Merges per-stream day CSV files from `_workspace/` into normalized video/photo/all day CSVs
- `estimate_video_sync_map.py` - Estimates constant audio-based sync corrections between video streams and writes `sync_map.csv`
- `apply_video_sync_map.py` - Applies `sync_map.csv` to merged video rows and writes `merged_video_synced.csv`
- `transcribe_video_batch.py` - Batch-runs WhisperX on synced video rows and writes transcripts plus a manifest
- `transcribe_video_batch_api.py` - Batch-runs WhisperX through the Python API and reuses one loaded model while writing into the normal transcript workspace
- `extract_announcement_candidates.py` - Parses WhisperX JSON transcripts and extracts candidate `numer X` announcement rows with absolute local timestamps
- `extract_announcement_candidates_semantic.py` - Builds semantic announcement candidates from transcript windows through `codex exec` or OpenAI-compatible backends, including a local preset
- `benchmark_semantic_announcement_models.py` - Prepares reviewed benchmark cases and compares announcement models with an `X/N` correctness score and total runtime
- `build_performance_timeline.py` - Converts announcement candidates into buffered performance intervals in `performance_timeline.csv`
- `build_semantic_announcement_demo.py` - Builds chunked transcript demo files and prompt-ready JSONL for semantic announcement extraction experiments
- `demo_semantic_announcement_classifier.py` - Prepares local transcript windows and classifies them through either `codex exec` or OpenAI-compatible backends, including a local preset
- `copy_reviewed_set_assets.py` - Copies photo and video files for one final reviewed set using GUI split/merge state
- `assign_photos_to_timeline.py` - Assigns exported photo rows to timeline intervals and writes review and unassigned CSVs without generating moves
- `generate_photo_proxy_jpg.py` - Generates rotated proxy JPG files from exported photo CSV rows into `_workspace/proxy_jpg/` for fast visual review
- `build_performance_proxy_index.py` - Builds a JSON index that groups assigned proxy JPG files by performance for the review GUI
- `review_performance_proxy_gui.py` - Opens a PySide6 desktop viewer for browsing performances and their assigned proxy JPG files
- `generate_mv_commands_from_timeline.py` - Generates `mkdir`/`mv` commands from exported photo CSV files and a performance timeline CSV

### Deprecated (deprecated/)

- `video/rename_video.py` - Deprecated legacy video renamer kept for reference and excluded from installation

## Notes

- Follow each category README for dependencies and usage details.
- VBC (Video Batch Compression) is maintained in a separate repository: https://github.com/hipotures/vbc
