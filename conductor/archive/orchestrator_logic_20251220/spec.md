# Track Specification: Implement Pipeline Orchestrator & Batch Processing Logic

## Objective
Implement the `Orchestrator` component, which serves as the "brain" of the application. It will coordinate the data flow between the infrastructure adapters (Scanner, ExifTool, FFmpeg) and the domain models, managing the concurrent execution of compression jobs and emitting events for the UI.

## Scope
1.  **Orchestrator Class:** Main class in `vbc/pipeline/orchestrator.py`.
2.  **Concurrency Management:** Use `concurrent.futures.ThreadPoolExecutor` to handle multiple jobs based on config.
3.  **Job Lifecycle Logic:** 
    -   Scanning -> Metadata Extraction -> Decision Logic (CQ/Rotation) -> Compression -> Post-verification.
4.  **Dynamic Logic Porting:** Port "Dynamic CQ" and "Auto-rotation" logic from the original `vbc.py`.
5.  **Event Emission:** Ensure all stages emit appropriate events via the `EventBus`.

## Detailed Requirements

### 1. Orchestrator (`vbc/pipeline/orchestrator.py`)
-   **Constructor:** Should accept `AppConfig`, `EventBus`, and instances of all infrastructure adapters (Dependency Injection).
-   **Method `run(input_dir: Path)`:**
    -   Emit `DiscoveryStarted`.
    -   Use `FileScanner` to find all candidates.
    -   Emit `DiscoveryFinished`.
    -   Submit jobs to a `ThreadPoolExecutor`.
    -   Manage gracefully shutdowns (KeyboardInterrupt handling support).

### 2. Job Execution Pipeline
For each `VideoFile` discovered:
1.  **Metadata Phase:** Use `ExifToolAdapter` and `FFprobeAdapter` to populate `VideoMetadata`.
2.  **Filter Phase:** Skip files based on `filter_cameras` or `min_size` (re-verification).
3.  **Decision Phase:** 
    -   **CQ Selection:** If camera model matches `dynamic_cq`, use that value; otherwise use default `cq`.
    -   **Rotation Selection:** Check filename against `autorotate` patterns.
4.  **Compression Phase:** Construct `CompressionJob`, determine `output_path`, and call `FFmpegAdapter.compress`.
5.  **Verification Phase:** (Optional) Check output file existence and size.

### 3. Events Integration
The Orchestrator must publish:
-   `JobStarted` before compression.
-   `JobCompleted` or `JobFailed` after.
-   (Future) Progress updates forwarded from the FFmpegAdapter.

## Testing Strategy
-   **Unit Tests:** Verify the decision logic (CQ matching, rotation regex).
-   **Integration Tests:** Mock all adapters and verify that `run()` calls them in the correct sequence with expected arguments.
-   **Concurrency Tests:** Verify that the orchestrator respects the `threads` limit from config.
