# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Scriptoza is a collection of standalone utility scripts organized by category:

- `video/` - Video utilities
- `photo/` - Photo utilities
- `utils/` - General utilities

Each category has its own `README.md` with requirements and usage. VBC is maintained separately at https://github.com/hipotures/vbc.

## Conventions

- Keep scripts self-contained and easy to run.
- Avoid cross-category dependencies unless there is a clear shared need.
- Update the category `README.md` when you add or change scripts.
- Update the root `README.md` with a one-line description of new scripts.
- This repo uses an ignore-by-default `.gitignore`; update it if you add new directories or file types.

## Running Scripts

Use standard tools unless a category README says otherwise:

```bash
python3 video/rename_video.py /path/to/test/video.mp4
python3 photo/rename_photo.py /path/to/test/photo.jpg
python3 utils/safe_rename_tt.py /path/to/tiktok/downloads/
./utils/session_stats.sh
```

## Testing

Manual testing only. Run scripts with sample inputs and verify outputs. If you add automated tests later, document how to run them.
