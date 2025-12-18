# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Structure

Scriptoza is a collection of utility scripts organized by category:
- Each category has its own directory (e.g., `video/`)
- Each category directory contains:
  - Python scripts (`.py`) or shell scripts (`.sh`)
  - Category-specific `README.md` with detailed documentation
- Main `README.md` lists all categories with brief descriptions and script names

## Adding New Scripts

When adding new scripts to this repository:

1. **Create category directory** if it doesn't exist (e.g., `audio/`, `network/`)
2. **Place script** in the category directory with descriptive name
3. **Create category README.md** with:
   - Script name as header
   - Features list
   - Requirements
   - Installation steps (if dependencies needed)
   - Usage examples with all options
   - Runtime controls (if interactive)
   - Output format/location
   - Technical features
   - Performance characteristics
4. **Update main README.md**:
   - Add category section if new
   - Add script entry with one-line description
5. **Update .gitignore** if category needs special exclusions

## Video Category Architecture

### vbc.py

VBC (Video Batch Compression) - Multi-threaded video compression script with real-time interactive controls, YAML configuration, and deep camera metadata analysis.

**Key components:**
- `ThreadController`: Condition variable-based dynamic thread control (min: 1, max: 16)
- `CompressionStats`: Thread-safe statistics tracking with deque for recent completions and dedicated `hw_cap` (Hardware Capability) error counter
- `VideoCompressor`: Main orchestrator class managing compression workflow and `ExifToolHelper` instance

**Metadata & Dynamic CQ:**
- Uses `pyexiftool` for deep metadata analysis (GPS, Lens, Camera Model)
- **Dynamic CQ**: Maps specific camera models (DJI, Sony, GH7) to different quality (CQ) settings via `conf/vbc.yaml`
- **Camera Filtering**: Ability to process only specific hardware models via `--camera` or config
- **Deep EXIF Copy**: Uses `exiftool` to copy all tags from source to MP4 (XMP/QuickTime mapping)

**Threading model:**
- Uses `ThreadPoolExecutor` with up to 16 workers
- Actual concurrency controlled by `ThreadController.acquire()` blocking
- Keyboard listener runs in separate daemon thread
- UI auto-refresh thread updates display every 1.0s

**Runtime controls implementation:**
- Keyboard listener uses `termios` raw mode with `select()` polling
- Keys: `,` or `<` (decrease), `.` or `>` (increase), `S` (graceful shutdown), `R` (refresh file list)
- Thread changes apply immediately; decrease waits for active tasks to complete
- Graceful shutdown sets `shutdown_requested` flag, preventing new task acquisition

**UI architecture:**
- `rich.Live` context with auto-refresh
- 6 panels: Status (includes `hw_cap` and `cam` skip counters), Progress, Currently Processing, Last Completed (5), Next in Queue (5, with **Camera Model** column), Summary
- ETA calculated from throughput (bytes/second) of completed files

**Error handling:**
- Failed compressions logged to `<output>/<filename>.err`
- **Hardware Capability Check**: Detects GPU limits (e.g., 10-bit support) and tracks them in `hw_cap` counter
- Temporary `.tmp` files and color-fix remuxes cleaned on startup
- Already compressed files automatically skipped (resume capability)

## Testing Scripts

Since scripts are standalone utilities:
- Test manually with sample inputs in each category
- For `vbc.py`:
  ```bash
  # Test with small set of videos and specific camera filter
  uv run video/vbc.py /path/to/test/videos --threads 2 --cq 45 --camera Sony

  # Test rotation and deep metadata
  uv run video/vbc.py /path/to/test/videos --cpu --rotate-180
  ```

## Git Workflow

Repository uses aggressive `.gitignore` (ignore everything by default):
- Only committed: `.gitignore`, `README.md`, `*.sh`, `*.yaml`, category directories with their scripts
- Python cache, logs (`.log`), temporary files (`.tmp`), error files (`.err`), output directories (`*_out/`) are ignored

When committing:
```bash
git add <category>/  # Will only add allowed files
git commit -m "Category: Brief description

- Bullet point details
- For multi-line messages"
git push
```

## Dependencies

Python scripts may require external dependencies:
- Always document in category README.md
- Include `pip install` command (or `uv add`)
- Check for missing imports at script startup with helpful error message

Current dependencies:
- `vbc.py`: `rich`, `pyyaml`, `pyexiftool` (requires system `exiftool`)
- `rename_video.py`: `exiftool` system binary
- git push after every commit