# Utils - General Utilities

Collection of generic helper scripts.

## Current Scope

The `utils/` directory now contains only non-pipeline helpers.

The event workflow pipeline was moved out of the active utility set:

- compatibility copy: `deprecated/pipeline/`
- migration target: the `vocatio` repository

If you still need the old event workflow scripts, run them from `deprecated/pipeline/`.

## Active Scripts

- `bootsel.sh` - Selects a UEFI boot entry by label, permanently or for the next boot only
- `statusline.py` - Rich status line for Claude Code with SQLite session logging
- `session_stats.sh` - Session statistics
- `claude_usage_report.py` - Aggregates JSONL history into per-session and per-day totals
- `organize_by_date.py` - Safe universal organizer that groups files into `YYYYMMDD` folders from filename dates
- `safe_rename_tt.py` - Safe date-based renamer for TikTok downloads
- `scan_mp4_to_json.py` - Scans MP4 files and outputs metadata as JSON
- `delete-google-chat-messages.js` - Controlled Google Chat message cleanup through a browser CDP session and private match rules
- `musescore_export_mp3_with_tags.py` - Exports MuseScore `.mscz` files to tagged MP3s named from `workTitle`
- `wav_to_mp3.py` - Recursively converts WAV files to high-quality VBR MP3 next to the originals without overwriting or deleting anything
- `install.py` - Installs selected utility scripts into a local bin directory
  and copies the optional `codex-resume` systemd user unit to
  `~/.config/systemd/user/`
- `migrate.py` - Small migration helper for local data transformations

## UEFI Boot Selection

`bootsel.sh` requires Bash 4+, `efibootmgr`, and Linux booted in UEFI mode with access to EFI variables. It accepts any exact UEFI label, case-insensitively, including quoted labels with spaces. Duplicate labels are rejected rather than choosing an arbitrary entry. Disk names and boot entry numbers are not hardcoded.

```bash
bash utils/bootsel.sh
bash utils/bootsel.sh ubuntu
bash utils/bootsel.sh ubuntu --run
bash utils/bootsel.sh proxmox --once --run
bash utils/bootsel.sh "Windows Boot Manager" --once
```

Selecting a label previews changes by default; add `--run` to apply them. Writes automatically request root through `sudo`; if reading EFI variables also requires root, launch the script with `sudo`. Permanent selection moves the entry to the front of `BootOrder`, preserves the relative order of other entries, and clears an existing `BootNext`. `--once` only sets `BootNext`. The script shows the current state and never reboots. Some firmware drops `BootNext` after a full power cut. Selecting an inactive entry does not activate it; firmware may skip it in `BootOrder`.

Running without arguments shows usage and verbose EFI entries, including loader device paths and optional boot data recorded in firmware. Kernel arguments stored separately in GRUB configuration are not part of these EFI entries.

To make the command available as `bootsel`:

```bash
install -Dm755 utils/bootsel.sh ~/.local/bin/bootsel
```

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
audiosettings.json -> MP3 comment summary and musescore:audiosettings custom tag
```

After export, the script prints the MP3 path and the readable MuseScore mixer summary, one mixer entry per line. Use `--print-mixer-json` to also print the full `audiosettings.json` value.

The MuseScore binary is read from `MUSESCORE_BIN`, `--musescore-bin`, or a MuseScore command available in `PATH`.

## WAV to MP3 Conversion

`wav_to_mp3.py` finds WAV files (any extension case) under a directory and converts each to a VBR MP3 (`libmp3lame -q:a 0`, roughly 220-260 kb/s) in the same directory. It is a dry run by default and only converts when `--run` is passed:

```bash
python3 utils/wav_to_mp3.py /path/to/audio
python3 utils/wav_to_mp3.py /path/to/audio --run
```

Existing files are never overwritten; a name collision produces the next free name:

```text
recording.wav                  -> recording.mp3
music.wav + music.mp3          -> music_1.mp3
voice.wav + voice.mp3 + voice_1.mp3 -> voice_2.mp3
```

Each file is encoded to a hidden temporary file and verified with `ffprobe` (MP3 stream present, duration within one second of the source) before it is moved to its final name. Each MP3 gets `wav2mp3_source` (name and size), `wav2mp3_source_md5`, `wav2mp3_settings` and `wav2mp3_date` tags (readable with `ffprobe -show_entries format_tags`), and a re-run skips every WAV whose MD5 matches an MP3 made by this script anywhere under the scanned directory, so renamed WAV or MP3 files are still recognised and a changed WAV is converted again. Re-runs therefore read each WAV once to hash it. The WAV files are never modified or deleted, so you can check the results and remove them yourself. The exit status is non-zero if any conversion failed. The startup line shows the selected VBR quality with its typical bitrate, each converted file is reported with its actual bitrate, and the summary shows the average. Use `--quality 0-9` to change the LAME VBR quality. Requires `ffmpeg` and `ffprobe`.

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
