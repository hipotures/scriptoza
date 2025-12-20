# Track Plan: Scaffold Modular Architecture & Port Domain Models

## Phase 1: Project Skeleton & Configuration
- [x] Task: Create Directory Structure (e9633e4)
    - Create `scriptoza/vbc` and subdirectories (`config`, `domain`, `infrastructure`, `pipeline`) with `__init__.py` files.
- [x] Task: Implement Pydantic Configuration Models (3dcbf48)
    - [ ] Sub-task: Write Tests for Config Models (Test valid/invalid YAML data)
    - [ ] Sub-task: Implement `scriptoza/vbc/config/models.py`
    - [ ] Sub-task: Implement `scriptoza/vbc/config/loader.py` (YAML to Pydantic)
- [ ] Task: Conductor - User Manual Verification 'Project Skeleton & Configuration' (Protocol in workflow.md)

## Phase 2: Domain Modeling & Events
- [ ] Task: Implement Domain Entities
    - [ ] Sub-task: Write Tests for Domain Models (VideoFile, JobStatus transitions)
    - [ ] Sub-task: Implement `scriptoza/vbc/domain/models.py`
- [ ] Task: Implement Event Bus
    - [ ] Sub-task: Write Tests for Event Bus (Subscribe/Publish)
    - [ ] Sub-task: Implement `scriptoza/vbc/infrastructure/event_bus.py`
    - [ ] Sub-task: Define Core Events in `scriptoza/vbc/domain/events.py`
- [ ] Task: Conductor - User Manual Verification 'Domain Modeling & Events' (Protocol in workflow.md)

## Phase 3: CLI Entry Point Scaffold
- [ ] Task: Create Typer Entry Point
    - [ ] Sub-task: Implement minimal `scriptoza/vbc/main.py`
    - [ ] Sub-task: Verify it runs (`python -m scriptoza.vbc.main --help`)
- [ ] Task: Conductor - User Manual Verification 'CLI Entry Point Scaffold' (Protocol in workflow.md)
