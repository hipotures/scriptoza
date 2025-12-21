# Product Guide

## Initial Concept
Refaktoryzacja monolitycznego skryptu `video/vbc.py` (Video Batch Compression) do nowoczesnej, modularnej architektury. Celem jest rozbicie "God Object", poprawa testowalności, umożliwienie łatwej wymiany komponentów (np. UI, enkodery) oraz ułatwienie przyszłego rozwoju projektu.

## Strategic Goals

### Primary User & Development Focus
- **Target Audience:** Developer / Power User (Self-use).
- **Core Objective:** Modularization for Maintainability & AI-Assisted Development.
- **Problem to Solve:** The current monolithic file structure (~2300 lines) exceeds the effective context window of AI coding agents, leading to high error rates and accidental code deletion during modifications.
- **Success Metric:** Breaking down the codebase into small, single-responsibility modules (<300 lines each) to facilitate safe and efficient editing by AI agents and humans.

### Future Extensibility
- **Architecture Requirement:** The architecture must be "open for extension, closed for modification."
- **Immediate Benefit:** Enabling safer refactoring and feature additions without risking the stability of the entire system.
- **Long-term Vision:** Easy integration of new encoders, complex orchestration logic, and alternative reporting mechanisms in the future.

### User Interface & Experience
- **Requirement:** Maintain full feature parity with the current interactive CLI (Rich-based).
- **Flexibility:** Decouple the UI logic from the core processing engine to allow for:
    - Independent evolution of the CLI.
    - Future addition of alternative interfaces (e.g., Web Dashboard) without rewriting the core logic.

### State Management Strategy
- **Approach:** Lightweight Service-Oriented State.
- **Rationale:** Given the transient nature of the compression tasks and quick refresh times, a persistent database is unnecessary. State will be managed via domain objects passed through the processing pipeline, balancing simplicity (OOP) with testability.

## Functional Scope (Refactoring Target)

The refactored application must retain all existing capabilities of `vbc.py`:
1.  **Batch Processing:** Recursive directory scanning with filtering (extensions, min-size).
2.  **Metadata Handling:** Deep EXIF preservation (GPS, Lens Info) and camera model detection.
3.  **Smart Compression:**
    -   Dynamic Constant Quality (CQ) based on camera model.
    -   Hardware capability tracking and error handling.
    -   Automatic rotation based on filename patterns.
    -   Corruption detection and skipping.
4.  **Concurrency:** Dynamic thread control (runtime adjustment).
5.  **Interactive UI:** Real-time dashboard with progress, ETA, and thread control.

## Technical Constraints & Safety
- **Side-by-Side Implementation:** The original `video/vbc.py` script and the existing `tests/` must remain **untouched**. The refactored version will be developed in a separate package/directory structure.
- **Verification Baseline:** Keeping the original code and tests intact is mandatory to allow direct comparison of feature parity, especially for UI behavior and compression results, during and after the refactoring process.

## Testing & Quality Assurance
- **Test Porting:** All existing tests in the `tests/` directory must be ported to the new modular architecture.
- **Verification:** The refactored code must pass all existing functional tests to ensure zero regression in compression quality, metadata preservation, and UI behavior.
- **Improved Coverage:** New modules must be accompanied by unit tests, taking advantage of the improved testability of the modular design.