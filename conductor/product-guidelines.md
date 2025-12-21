# Product Guidelines

## Architectural Principles
- **Pragmatic Modular Design:** Code should be structured into clear, logical feature modules (Services/Domains). While strict interfaces are not required, clear boundaries and responsibilities are mandatory.
- **Pipeline-Driven Processing:** The core workflow (File Discovery -> Metadata Extraction -> Processing -> Validation) should be modeled as a linear pipeline, making the flow of data explicit and easy to trace.
- **Type Safety:** Use Python 3.12+ type hinting extensively. Use Pydantic `BaseModel` for all data transfer objects (DTOs) passing between pipeline stages to ensure strict validation and context clarity for AI agents and developers.

## Coding Standards & Structure
- **Feature-Based Packaging:** Organize code by feature (e.g., `compression/`, `metadata/`, `ui/`).
    - Files should generally contain related functionality.
    - Avoid splitting code into tiny files unnecessarily; cohesive modules of 300-500 lines are acceptable if they encapsulate a complete feature.
- **Separation of Concerns:**
    - **Logic vs. UI:** Core processing logic MUST NOT directly import or interact with the UI library (`rich`).
    - **Observer Pattern:** The UI and Logging systems should act as observers/subscribers to domain events emitted by the processing pipeline.

## Error Handling & Stability
- **Centralized Exception Management:**
    - Do not scatter `try-except` blocks deeply within business logic for control flow.
    - Exceptions should propagate to the pipeline orchestrator, which decides on the strategy (Retry, Skip, Abort) and logs the event.
- **Stability:** The system must be robust against external tool failures (ffmpeg crashes, file system locks).

## Logging & Observability
- **Decoupled Reporting:**
    - **Event-Based:** The application should emit high-level events (e.g., `TaskStarted`, `ProgressUpdated`, `ErrorOccurred`).
    - **UI:** The Console Dashboard subscribes to these events to update counters and progress bars (no raw error text in UI).
    - **File Logger:** A separate subscriber writes detailed technical logs (including stack traces) to disk.

## Development Workflow
- **Side-by-Side Development:** New code goes into a new package in the root directory (`vbc/`) while keeping `video/vbc.py` intact.
- **Testing First:** Port existing logic by writing tests for the new modules first, ensuring they match the behavior of the original script.
