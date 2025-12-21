# Tech Stack

## Core Language & Runtime
- **Language:** Python 3.12+
    - Leveraging latest features like enhanced type hinting, `f-strings` improvements, and better performance.
- **Dependency Management:** `uv` (as indicated by the presence of `uv.lock` and `.uv_cache`).

## Frameworks & Libraries
- **CLI Framework:** `Typer`
    - Chosen for its modern approach based on Python type hints, providing excellent developer experience and automatic shell completion.
- **Data Validation & Settings:** `Pydantic` (v2)
    - Used for defining structured data models, validating configuration, and parsing complex outputs from external tools (FFmpeg/ExifTool).
- **UI & Interaction:** `rich`
    - Used to maintain full feature parity with the existing interactive dashboard, progress bars, and status panels.
- **Configuration:** `PyYAML`
    - Retained for compatibility with existing `conf/*.yaml` files, but integrated with Pydantic for schema-backed loading.

## External Tooling (System Dependencies)
- **Media Processing:** `ffmpeg` / `ffprobe`
    - Support for NVENC (AV1/HEVC) and SVT-AV1 encoders.
- **Metadata Management:** `exiftool`
    - Accessed via `pyexiftool` for deep EXIF/XMP analysis and preservation.

## Quality Assurance
- **Testing Framework:** `pytest`
    - Porting and expanding existing functional tests.
- **Static Analysis:** `ruff` or `mypy` (recommended for Python 3.12+ type safety).
