# Track Specification: Implement Infrastructure Adapters

## Objective
Implement the infrastructure layer services that interact with the file system and external tools (FFmpeg, ExifTool). These adapters will hide the low-level details of subprocess execution and file I/O behind clean, domain-aware classes.

## Scope
1.  **File Scanner:** Recursive directory scanning with filtering logic (extensions, min-size).
2.  **ExifTool Adapter:** Wrapper around `pyexiftool` to extract metadata and map it to `VideoMetadata` domain objects.
3.  **FFmpeg Adapter:** Wrapper around `subprocess` to handle video compression (AV1/NVENC) and probing, utilizing `CompressionStats` (to be ported) logic for progress tracking if possible, or emitting progress events.

## Detailed Requirements

### 1. File Scanner (`vbc/infrastructure/file_scanner.py`)
-   **Functionality:** Scan a root directory recursively.
-   **Filtering:**
    -   Match extensions (case-insensitive).
    -   Filter by minimum size (`min_size_bytes`).
    -   Ignore files that strictly match the output directory pattern (e.g., `_out/`).
-   **Output:** Yield `VideoFile` objects with `path` and `size_bytes` populated. `metadata` field remains `None` at this stage.

### 2. ExifTool Adapter (`vbc/infrastructure/exif_tool.py`)
-   **Dependency:** `pyexiftool` (already in `tech-stack.md`).
-   **Functionality:**
    -   `extract_metadata(file: VideoFile) -> VideoMetadata`: Extract Width, Height, FPS, Codec, Bitrate, and Camera Model.
    -   `copy_metadata(source: Path, target: Path)`: Copy EXIF tags from source to target.
-   **Safety:** Handle `exiftool` missing or crashing gracefully.

### 3. FFmpeg Adapter (`vbc/infrastructure/ffmpeg.py`)
-   **Functionality:**
    -   `probe(file: Path) -> dict`: Use `ffprobe` as a fallback or pre-check if needed (mostly ExifTool is preferred for metadata, but ffprobe is better for streams). *Decision: Use ffprobe for stream info (codec, resolution) and ExifTool for camera metadata.*
    -   `compress(job: CompressionJob, config: GeneralConfig) -> None`: Execute the compression command.
-   **Progress Monitoring:** Parse FFmpeg output to emit `JobProgressUpdated` events via the `EventBus` (injected or global).
-   **Hardware Checks:** Detect NVENC failures and raise specific exceptions.

## Testing Strategy
-   **Mocking:** Heavy use of `unittest.mock` to mock `subprocess.run`, `pyexiftool.ExifTool`, and file system calls.
-   **Integration:** Optional tests that run against real test files in `tests/data/` (marked as slow).
