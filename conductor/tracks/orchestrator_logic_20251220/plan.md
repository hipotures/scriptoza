# Track Plan: Implement Pipeline Orchestrator & Batch Processing Logic

## Phase 1: Sequential Orchestration
- [x] Task: Implement Orchestrator Skeleton (fe3c658)
    - [ ] Sub-task: Write Tests for basic Orchestrator flow (mocked sequential execution)
    - [ ] Sub-task: Implement `vbc/pipeline/orchestrator.py` with sequential job execution
- [ ] Task: Implement Metadata & Decision Logic
    - [ ] Sub-task: Write Tests for Dynamic CQ and Auto-rotate matching
    - [ ] Sub-task: Port matching logic from original script to Orchestrator
- [ ] Task: Conductor - User Manual Verification 'Sequential Orchestration' (Protocol in workflow.md)

## Phase 2: Concurrent Execution
- [ ] Task: Implement Multi-threaded Execution
    - [ ] Sub-task: Write Tests for thread pool behavior (concurrency limits)
    - [ ] Sub-task: Update Orchestrator to use `ThreadPoolExecutor`
- [ ] Task: Conductor - User Manual Verification 'Concurrent Execution' (Protocol in workflow.md)

## Phase 3: Final Integration Scaffold
- [ ] Task: Integrate with CLI
    - [ ] Sub-task: Update `vbc/main.py` to instantiate adapters and run Orchestrator
    - [ ] Sub-task: Verify E2E flow with mocked adapters via CLI
- [ ] Task: Conductor - User Manual Verification 'Final Integration Scaffold' (Protocol in workflow.md)
