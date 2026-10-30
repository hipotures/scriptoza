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
bash utils/bootsel.sh --debug
bash utils/bootsel.sh ubuntu
bash utils/bootsel.sh ubuntu --run
bash utils/bootsel.sh 3 --run
bash utils/bootsel.sh proxmox --once --run
bash utils/bootsel.sh "Windows Boot Manager" --once
```

Selecting a label previews changes by default; add `--run` to apply them. Writes automatically request root through `sudo`; if reading EFI variables also requires root, launch the script with `sudo`. Permanent selection moves the entry to the front of `BootOrder`, preserves the relative order of other entries, and clears an existing `BootNext`. `--once` only sets `BootNext`. The script shows the current state and never reboots. Some firmware drops `BootNext` after a full power cut. Selecting an inactive entry does not activate it; firmware may skip it in `BootOrder`.

A numeric selector chooses the position in the currently displayed boot order: `3` selects its third entry, not EFI ID `0003`. Positions change when the boot order changes; use labels in automation. Numeric selectors are reserved for positions. They also allow choosing between duplicate labels. Dry runs label the final summary as the unchanged current firmware state.

Running without arguments shows usage and a readable summary: the current bootloader, the next boot override, the ordered list of boot labels, and available entries with EFI file paths. Firmware applications and network entries get short descriptions; inactive entries are marked. Add `--debug` to include the raw `efibootmgr -v` output with full device paths and optional boot data recorded in firmware. Kernel arguments stored separately in bootloader configuration (such as GRUB or Limine) are not part of these EFI entries.

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

## YubiKey Touch Sounds

See [sound sources and reinstall instructions](../docs/yubikey-sound-sources.md) for both download links, asset IDs, and exact local filenames.

`yubikey_touch_sound.py` plays distinct sounds when touch waiting starts and ends, at 15% volume. An end event does not prove authentication succeeded. Requires Python 3, `ffplay` (FFmpeg), and a working `yubikey-touch-detector` user service exposing its Unix socket.

The installer includes the script and `yubikey-touch-sound.service`. Audio files are intentionally excluded from the repository; download them separately from Pixabay. The source for `universfield-new-notification-064-494547.mp3` is [New Notification 064 by Universfield](https://pixabay.com/sound-effects/technology-new-notification-064-494547/), offered under the [Pixabay Content License](https://pixabay.com/service/license-summary/). That license restricts standalone redistribution, so these unchanged MP3s are not bundled here. Supply `universfield-new-notification-066-494545.mp3` and `universfield-new-notification-064-494547.mp3` in `~/.local/share/sounds/` yourself; the existing local files are left untouched.

```bash
python3 utils/install.py          # Preview without changing files
python3 utils/install.py --run    # Install utilities, and services
systemctl --user daemon-reload
systemctl --user enable --now yubikey-touch-sound.service
```

The installed script is `~/.local/bin/yubikey_touch_sound.py`, the unit is in `~/.config/systemd/user/`, and sounds are in `~/.local/share/sounds/`. Adjust the `ffplay -volume` argument in the source and reinstall to change loudness. Reinstalling an already running service requires `systemctl --user restart yubikey-touch-sound.service`. The installer copies units but does not activate them.
