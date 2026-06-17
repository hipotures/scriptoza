# Utils - General Utilities

Collection of generic helper scripts.

## Current Scope

The `utils/` directory now contains only non-pipeline helpers.

The event workflow pipeline was moved out of the active utility set:

- compatibility copy: `deprecated/pipeline/`
- migration target: the `vocatio` repository

If you still need the old event workflow scripts, run them from `deprecated/pipeline/`.

## Active Scripts

- `statusline.py` - Rich status line for Claude Code with SQLite session logging
- `session_stats.sh` - Session statistics
- `claude_usage_report.py` - Aggregates JSONL history into per-session and per-day totals
- `organize_by_date.py` - Safe universal organizer that groups files into `YYYYMMDD` folders from filename dates
- `safe_rename_tt.py` - Safe date-based renamer for TikTok downloads
- `scan_mp4_to_json.py` - Scans MP4 files and outputs metadata as JSON
- `delete-google-chat-messages.js` - Controlled Google Chat message cleanup through a browser CDP session and private match rules
- `musescore_export_mp3_with_tags.py` - Exports MuseScore `.mscz` files to tagged MP3s named from `workTitle`
- `install.py` - Installs selected utility scripts into a local bin directory
- `migrate.py` - Small migration helper for local data transformations

## MuseScore MP3 Export

`musescore_export_mp3_with_tags.py` exports a MuseScore `.mscz` file through MuseScore Studio, reads meaningful score metadata from the embedded `.mscx` XML, and writes ID3 metadata to the final MP3 through `ffmpeg` without recompressing the audio.

The final filename is based on `workTitle`, not the source filename. If the target already exists, the script creates the next versioned name:

```bash
python3 utils/musescore_export_mp3_with_tags.py /path/to/score.mscz
```

```text
Lamento di Maggio.mp3
Lamento di Maggio_1.mp3
Lamento di Maggio_2.mp3
```

Metadata mapping:

```text
workTitle or movementTitle -> MP3 title and output filename
composer -> MP3 artist and composer
copyright -> MP3 copyright
subtitle and Alt Titles -> MP3 comment
audiosettings.json -> MP3 comment summary and musescore:audiosettings custom tag, also printed after export
```

The MuseScore binary is read from `MUSESCORE_BIN`, `--musescore-bin`, or a MuseScore command available in `PATH`.

## Google Chat Message Cleanup

`delete-google-chat-messages.js` connects to an already running Chrome or Chromium instance through the Chrome DevTools Protocol, scans the active Google Chat conversation, and deletes matching messages one at a time. It is scan-only by default; it only deletes when `--delete` is passed.

It expects Node.js plus the `playwright` package to be available in the environment where you run it.

Keep private deletion rules outside the repository. Copy the example file and put the real rule in your local env file:

```bash
cp utils/delete-google-chat-messages.env.example .env
```

Rule values are treated as literal text by default, so a normal string like `"https://example.com/"` works without escaping dots. The script matches the rule against visible message text and link URLs.

```bash
node utils/delete-google-chat-messages.js --reg DELETE_EXAMPLE --limit 20 --delay-ms 3000
node utils/delete-google-chat-messages.js --delete --reg DELETE_EXAMPLE --limit 20 --delay-ms 3000
```

Use `--url` to target a specific conversation, `--env PATH` to load rules from another file, and `--regex` only when the env value should be interpreted as a JavaScript regular expression.

## Notes

- Event workflow and review tools are no longer active under `utils/`
- Historical pipeline scripts remain available only under `deprecated/pipeline/`
