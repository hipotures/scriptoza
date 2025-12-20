# Track Plan: Scaffold Modular Architecture & Port Domain Models

## Phase 1: Project Skeleton & Configuration
- [x] Task: Create Directory Structure (e9633e4)
    - Create `vbc` and subdirectories (`config`, `domain`, `infrastructure`, `pipeline`) with `__init__.py` files.
- [x] Task: Implement Pydantic Configuration Models (3dcbf48)
    - [ ] Sub-task: Write Tests for Config Models (Test valid/invalid YAML data)
    - [ ] Sub-task: Implement `vbc/config/models.py`
    - [ ] Sub-task: Implement `vbc/config/loader.py` (YAML to Pydantic)
- [ ] Task: Conductor - User Manual Verification 'Project Skeleton & Configuration' (Protocol in workflow.md)

## Phase 2: Domain Modeling & Events
- [x] Task: Implement Domain Entities (dc6b3d9)
    - [ ] Sub-task: Write Tests for Domain Models (VideoFile, JobStatus transitions)
    - [ ] Sub-task: Implement `vbc/domain/models.py`
- [ ] Task: Implement Event Bus
    - [ ] Sub-task: Write Tests for Event Bus (Subscribe/Publish)
    - [ ] Sub-task: Implement `vbc/infrastructure/event_bus.py`
    - [ ] Sub-task: Define Core Events in `vbc/domain/events.py`
- [ ] Task: Conductor - User Manual Verification 'Domain Modeling & Events' (Protocol in workflow.md)

## Phase 3: CLI Entry Point Scaffold
- [ ] Task: Create Typer Entry Point
    - [ ] Sub-task: Implement minimal `vbc/main.py`
    - [ ] Sub-task: Verify it runs (`python -m vbc.main --help`)
- [ ] Task: Conductor - User Manual Verification 'CLI Entry Point Scaffold' (Protocol in workflow.md)
