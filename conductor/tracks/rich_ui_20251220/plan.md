# Track Plan: Implement Rich Interactive UI & Keyboard Controls

## Phase 1: UI State & Event Mapping
- [x] Task: Implement UI State Manager (efae25e)
    - [ ] Sub-task: Write Tests for `UIState` (statistics, ETA)
    - [ ] Sub-task: Implement `vbc/ui/state.py`
- [x] Task: Map Events to UI Updates (ce57710)
    - [ ] Sub-task: Create Event Handlers in `vbc/ui/manager.py` to update `UIState`
- [ ] Task: Conductor - User Manual Verification 'UI State & Event Mapping' (Protocol in workflow.md)

## Phase 2: Rich Dashboard Implementation
- [ ] Task: Recreate Dashboard Panels
    - [ ] Sub-task: Implement `vbc/ui/dashboard.py` with `rich.Live` layout
    - [ ] Sub-task: Port panel rendering logic from original script
- [ ] Task: Conductor - User Manual Verification 'Rich Dashboard Implementation' (Protocol in workflow.md)

## Phase 3: Runtime Controls & Orchestrator Sync
- [ ] Task: Implement Keyboard Listener
    - [ ] Sub-task: Implement `vbc/ui/keyboard.py` using `termios`/`select`
- [ ] Task: Enable Dynamic Thread Control
    - [ ] Sub-task: Update `vbc/pipeline/orchestrator.py` to support dynamic thread adjustment
    - [ ] Sub-task: Integrate keyboard events with Orchestrator via `EventBus`
- [ ] Task: Final Integration in CLI
    - [ ] Sub-task: Enable Rich UI in `vbc/main.py`
- [ ] Task: Conductor - User Manual Verification 'Runtime Controls & Orchestrator Sync' (Protocol in workflow.md)
