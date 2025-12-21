# Track Specification: Implement Advanced Logic, Hardware Checks & Error Handling

## Objective
Finalize the functional parity with the original `vbc.py` script by implementing specialized error handling, hardware capability detection, smart skipping logic, and system housekeeping.

## Scope
1.  **Hardware Capability Tracking:** Detect "Hardware is lacking required capabilities" from FFmpeg and handle it as a specific job status (`HW_CAP_LIMIT`).
2.  **Error Persistence:** Create `.err` files in the output directory for failed jobs.
3.  **Smart Skipping:** 
    -   `--skip-av1`: Skip files already encoded in AV1.
    -   `--min-compression-ratio`: If savings are below threshold, copy original instead of using compressed version.
4.  **Compatibility Fixes:** Re-implement the "reserved color space" fix for FFmpeg 7.x.
5.  **Housekeeping:** Cleanup of `.tmp` and `.err` files on startup (if requested).

## Detailed Requirements

### 1. Hardware Capability Detection (`vbc/infrastructure/ffmpeg.py`)
-   Update `FFmpegAdapter` to scan `ffmpeg` output for specific capability strings.
-   Raise or emit a `HardwareCapabilityError` (to be defined).
-   Update `UIState` to increment the `hw_cap` counter via a new event.

### 2. Error Markers (`vbc/pipeline/orchestrator.py`)
-   When a job fails, the Orchestrator must write a `<filename>.err` file containing the error message in the output directory.
-   On startup, the Orchestrator should check for existing `.err` markers and skip those files unless `--clean-errors` is set.

### 3. Smart Skipping Logic (`vbc/pipeline/orchestrator.py`)
-   Check `video_file.metadata.codec` before starting compression.
-   Calculate actual compression ratio after job completion and decide whether to keep the output or revert to original.

### 4. Color Fix Adapter (`vbc/infrastructure/ffmpeg.py`)
-   Detect FFmpeg 7.x errors related to color space.
-   Implement the remuxing step with `hevc_metadata` or `h264_metadata` filters if the primary compression fails with specific color errors.

### 5. Housekeeping Service (`vbc/infrastructure/housekeeping.py`)
-   A new service to find and remove stale `.tmp` files.
-   Optionally remove `.err` markers if `--clean-errors` is active.

## Testing Strategy
-   **Error Simulation:** Mock FFmpeg output to simulate hardware errors and color space errors.
-   **Skipping Tests:** Unit tests for codec-based and ratio-based skipping logic.
-   **I/O Tests:** Verify `.err` file creation and deletion.
