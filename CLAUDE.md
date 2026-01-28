## Repository Overview

Scriptoza is a collection of standalone utility scripts organized by category:

- `video/` - Video utilities
- `photo/` - Photo utilities
- `utils/` - General utilities

Each category has its own `README.md` with requirements and usage. VBC is maintained separately at https://github.com/hipotures/vbc.

## Conventions

- Keep scripts self-contained and easy to run.
- **Language:** All code, comments, and user interface text (messages, help, logs) must be exclusively in English.
- **DO NOT add comments** to the code unless explicitly requested by the user.
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

## UI/UX & Progress Bars

- **Use `rich.progress`** for any script processing more than one file.
- **Layout:** Use a left-justified, non-expanding layout (`expand=False`).
- **Standard Columns:** 
    - `SpinnerColumn()`
    - `TextColumn("[progress.description]{task.description}")`
    - `BarColumn(bar_width=40)`
    - `MofNCompleteColumn()`
    - `TaskProgressColumn()`
    - `TimeElapsedColumn()`
- **Alignment:** Ensure task descriptions have a consistent width (e.g., using `.ljust(25)`) to prevent the progress bar from shifting horizontally.

## Testing

Manual testing only. Run scripts with sample inputs and verify outputs. If you add automated tests later, document how to run them.
