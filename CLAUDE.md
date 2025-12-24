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

## VBC Architecture

VBC uses modern modular architecture located at `vbc/main.py`. See `docs/architecture/overview.md` for details.

**Key features:**
- Event-driven architecture with EventBus
- Clean separation: UI → Pipeline → Infrastructure
- Modular adapters for FFmpeg, ExifTool, FFprobe
- Thread-safe orchestration with dynamic concurrency

**VBC Utilities (vbc/utils/):**
- `move_err_files.py` - Relocates source videos for failed compressions
- `copy_failed_videos.py` - Copies source videos for failed compressions

## Testing Scripts

Since scripts are standalone utilities:
- Test manually with sample inputs in each category
- For VBC:
  ```bash
  # Test with small set of videos and specific camera filter
  uv run vbc/main.py /path/to/test/videos --threads 2 --cq 45

  # Test rotation and deep metadata
  uv run vbc/main.py /path/to/test/videos --cpu --rotate-180
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
- `vbc/main.py`: `rich`, `pyyaml`, `pyexiftool`, `typer` (requires system `exiftool`)
- `rename_video.py`: `exiftool` system binary
- git push after every commit
