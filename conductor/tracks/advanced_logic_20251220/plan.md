# Track Plan: Implement Advanced Logic, Hardware Checks & Error Handling

## Phase 1: Specialized Error Handling & HW Caps
- [x] Task: Implement HW Capability Detection (691ea19)
    - [ ] Sub-task: Define `HardwareCapabilityExceeded` event and update `UIState`
    - [ ] Sub-task: Update `vbc/infrastructure/ffmpeg.py` to detect HW errors in output
- [ ] Task: Implement Error Markers logic
    - [ ] Sub-task: Update Orchestrator to create `.err` files on failure
    - [ ] Sub-task: Implement logic to skip files with existing `.err` markers
- [ ] Task: Conductor - User Manual Verification 'Specialized Error Handling' (Protocol in workflow.md)

## Phase 2: Smart Skipping & Space Optimization
- [ ] Task: Implement Codec Skipping (`--skip-av1`)
    - [ ] Sub-task: Update Orchestrator to check metadata before submission
- [ ] Task: Implement Compression Ratio Guard
    - [ ] Sub-task: Add logic to compare input/output size and keep the best version
- [ ] Task: Conductor - User Manual Verification 'Smart Skipping' (Protocol in workflow.md)

## Phase 3: Compatibility & Housekeeping
- [ ] Task: Implement Housekeeping Service
    - [ ] Sub-task: Create `vbc/infrastructure/housekeeping.py` for `.tmp` cleanup
- [ ] Task: Implement Automatic Color Fix
    - [ ] Sub-task: Port the multi-stage FFmpeg logic for fixing reserved color spaces
- [ ] Task: Final Integration & CLI Flags
    - [ ] Sub-task: Add missing options (`--clean-errors`, `--skip-av1`, etc.) to `vbc/main.py`
- [ ] Task: Conductor - User Manual Verification 'Compatibility & Housekeeping' (Protocol in workflow.md)
