# Track Specification: Scaffold Modular Architecture & Port Domain Models

## Objective
Establish the foundational directory structure for the new `vbc` package and implement the core Pydantic data models that will drive the configuration and processing pipeline. This phase sets the stage for the logic implementation by defining strictly typed data structures first.

## Scope
1.  **Directory Structure:** Create the package layout under a new `scriptoza/` root or `vbc_ng/` as per guidelines.
2.  **Configuration Models:** Port the existing `conf/vbc.yaml` structure into nested Pydantic models.
3.  **Domain Models:** Define `VideoFile`, `CompressionJob`, and `JobResult` models.
4.  **Events System:** Implement a lightweight event bus for decoupled communication.
5.  **Tests:** Create unit tests for the new models and event system.

## Detailed Requirements

### 1. Package Structure
Establish the following directory hierarchy:
```text
scriptoza/
├── __init__.py
└── vbc/                # New modular VBC package
    ├── __init__.py
    ├── main.py         # Entry point (Typer CLI)
    ├── config/         # Configuration loading & validation
    │   ├── __init__.py
    │   └── models.py   # Pydantic Config Models
    ├── domain/         # Core business entities
    │   ├── __init__.py
    │   ├── models.py   # VideoFile, Metadata, JobResult
    │   └── events.py   # Event definitions
    ├── infrastructure/ # External adapters (abstracted)
    │   ├── __init__.py
    │   ├── event_bus.py # Simple Pub/Sub implementation
    │   └── logging.py  # Logging configuration
    └── pipeline/       # Processing stages (scaffold only)
        ├── __init__.py
        └── orchestrator.py
```

### 2. Configuration Models (Pydantic)
Create `config/models.py` to strictly validate `vbc.yaml`.
-   **`GeneralConfig`**:
    -   `threads`: int (gt=0)
    -   `cq`: int (0-63)
    -   `gpu`: bool
    -   `copy_metadata`: bool
    -   `use_exif`: bool
    -   `filter_cameras`: List[str] (default empty)
    -   `dynamic_cq`: Dict[str, int]
    -   `extensions`: List[str]
    -   `min_size_bytes`: int
-   **`AutoRotateConfig`**:
    -   `patterns`: Dict[str, int] (Regex -> Angle)
-   **`AppConfig`**:
    -   Root model combining `GeneralConfig` and `AutoRotateConfig`.

### 3. Domain Models
Create `domain/models.py`.
-   **`VideoMetadata`**:
    -   Fields: `width`, `height`, `codec`, `fps`, `camera_model` (Optional), `bitrate` (Optional).
-   **`VideoFile`**:
    -   `path`: Path
    -   `size_bytes`: int
    -   `metadata`: Optional[VideoMetadata]
-   **`JobStatus`** (Enum):
    -   `PENDING`, `PROCESSING`, `COMPLETED`, `SKIPPED`, `FAILED`, `HW_CAP_LIMIT`.
-   **`CompressionJob`**:
    -   `source_file`: VideoFile
    -   `status`: JobStatus
    -   `output_path`: Optional[Path]
    -   `error_message`: Optional[str]

### 4. Event System
Create `infrastructure/event_bus.py`.
-   Simple synchronous Pub/Sub.
-   Ability to subscribe to specific Event types (e.g., `JobStarted`, `ProgressUpdated`).

## Testing Strategy
-   **Unit Tests:** Verify Pydantic validation rules (e.g., negative threads throw error, invalid CQ throws error).
-   **Event Bus Tests:** Verify subscribers receive events.
