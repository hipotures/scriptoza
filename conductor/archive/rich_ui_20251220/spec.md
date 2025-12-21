# Track Specification: Implement Rich Interactive UI & Keyboard Controls

## Objective
Port the advanced real-time dashboard from the original `vbc.py` to the new modular architecture. The UI will be decoupled from the processing logic, interacting solely through the `EventBus`. It will also include keyboard-driven runtime controls for dynamic thread adjustment and graceful shutdown.

## Scope
1.  **Event-Driven Dashboard:** Implement `Dashboard` in `vbc/ui/dashboard.py` using `rich.live`.
2.  **Panels Implementation:** Recreate the 6 status panels (Status, Progress, Processing, Recent, Queue, Summary).
3.  **Keyboard Listener:** Implement a non-blocking keyboard listener in `vbc/ui/keyboard.py`.
4.  **State Tracking:** A thread-safe `UIState` to store accumulated statistics and current activity for rendering.
5.  **Thread Control logic:** Emit events to trigger thread count changes in the Orchestrator (requires Orchestrator update).

## Detailed Requirements

### 1. UI State (`vbc/ui/state.py`)
-   Thread-safe counters for: `completed`, `failed`, `skipped`, `hw_cap`.
-   Accumulators for bytes processed (total input vs. total output).
-   List of "Currently Processing" jobs.
-   Queue of "Recently Completed" jobs (max 5).
-   ETA calculation logic based on throughput.

### 2. Dashboard Components (`vbc/ui/dashboard.py`)
-   Use `rich.Live` with `auto_refresh=True`.
-   **Layout:**
    -   Header with global status and thread count.
    -   Progress bar for the entire batch.
    -   Scrollable/List area for active jobs with spinners.
    -   Table for recently completed files.
    -   Table for upcoming queue (requires Orchestrator to expose queue).
    -   Footer summary (Space saved, throughput).

### 3. Keyboard Controls (`vbc/ui/keyboard.py`)
-   Keys to support:
    -   `,` / `<`: Decrease threads.
    -   `.` / `>`: Increase threads.
    -   `S`: Signal graceful shutdown.
    -   `R`: Refresh (optional for now).
-   Must run in a separate daemon thread to avoid blocking the main UI/logic.

### 4. Dynamic Concurrency (Orchestrator Update)
-   The Orchestrator must listen for `ThreadCountChanged` events and adjust its `ThreadPoolExecutor` (or use a dynamic acquiring mechanism like the original script's `ThreadController`).

## Testing Strategy
-   **Unit Tests:** Verify `UIState` calculations (ETA, space saved).
-   **Mock Verification:** Mock the `Live` context and verify that event handlers update the state correctly.
-   **Manual Verification:** Run the CLI with dummy/real videos to observe UI behavior and keyboard responsiveness.
