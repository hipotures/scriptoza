# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Scriptoza is a collection of utility scripts organized by category, with **VBC (Video Batch Compression)** as the primary project - a production-grade video compression tool with event-driven Clean Architecture.

**Project uses `uv` for dependency management** (Python 3.12+). All commands use `uv run`.

## Common Commands

### VBC Development
```bash
# Run VBC (main application)
uv run vbc/main.py /path/to/videos --gpu --threads 8
uv run vbc/main.py /path/to/videos --cpu --cq 35

# Test with small dataset
uv run vbc/main.py /path/to/test/videos --threads 2 --cq 45

# Build and serve documentation
./serve-docs.sh  # Opens http://127.0.0.1:8000

# Run tests (when available)
uv run pytest
uv run pytest tests/unit/
uv run pytest -m "not slow"
```

### Dependency Management
```bash
# Add new dependency
uv add <package>

# Add dev dependency
uv add --dev <package>

# Sync dependencies
uv sync
```

## VBC Architecture

VBC (`vbc/`) follows **Clean Architecture** with strict layer separation:

```
UI Layer (ui/)           → Rich dashboard, keyboard listener
    ↓ Events (EventBus)
Pipeline Layer (pipeline/) → Orchestrator (job lifecycle)
    ↓ Domain Models
Infrastructure Layer (infrastructure/) → FFmpeg, ExifTool, FFprobe adapters
```

### Directory Structure
```
vbc/
├── main.py              # Typer CLI entry point
├── config/              # Pydantic models + YAML loader
├── domain/              # Business logic (models.py, events.py)
├── infrastructure/      # External adapters (event_bus, ffmpeg, exiftool, ffprobe)
├── pipeline/            # Orchestrator (36KB, core processing logic)
└── ui/                  # Rich Live dashboard (state, manager, keyboard, dashboard)
```

### Key Components

**Orchestrator** (`pipeline/orchestrator.py`):
- Discovery, queue management, job lifecycle
- ThreadController pattern (Condition-based concurrency)
- Submit-on-demand pattern (deque with prefetch factor)
- Metadata caching (thread-safe ExifTool calls)
- Graceful shutdown, dynamic refresh

**EventBus** (`infrastructure/event_bus.py`):
- Synchronous Pub/Sub (16 event types)
- Decouples UI from business logic
- See `domain/events.py` for event definitions

**FFmpegAdapter** (`infrastructure/ffmpeg.py`):
- Builds CLI args (GPU/CPU, rotation, filters)
- Progress monitoring via stdout parsing
- Hardware capability error detection
- Color space remuxing

### VBC Design Patterns

1. **Event-Driven Communication**: All components interact via EventBus
2. **Dependency Injection**: Adapters injected into Orchestrator
3. **ThreadController Pattern**: Condition variable for dynamic concurrency
4. **Submit-on-Demand**: Don't queue 10K futures, submit as slots become available
5. **Type Safety**: Pydantic models for all config and domain entities

### VBC Modification Guidelines

- **UI changes**: Modify `ui/` components (dashboard panels, keyboard shortcuts)
- **New events**: Add to `domain/events.py`, subscribe in `ui/manager.py`
- **FFmpeg changes**: Update `infrastructure/ffmpeg.py` (command builder)
- **Job logic**: Modify `pipeline/orchestrator.py` (discovery, processing, lifecycle)
- **Config**: Add fields to `config/models.py`, update YAML loader

**Critical**: Preserve event-driven architecture. Don't create direct dependencies between layers.

## Other Scripts Organization

### Structure
- Each category has directory (`video/`, `photo/`, `utils/`)
- Each script documented in category `README.md`
- Main `README.md` lists all categories

### Adding New Scripts

1. Create/use category directory (e.g., `audio/`, `network/`)
2. Add script with descriptive name
3. Create/update category `README.md`:
   - Features, requirements, installation
   - Usage examples, runtime controls
   - Output format, performance notes
4. Update main `README.md` with one-line description
5. Update `.gitignore` if needed

### Standalone Script Testing
Test manually with sample inputs:
```bash
uv run video/rename_video.py /path/to/test/video.mp4
uv run utils/safe_rename_tt.py /path/to/tiktok/downloads/
```

## Git Workflow

**Aggressive `.gitignore`** (ignore-by-default):
- **Committed**: `.gitignore`, `README.md`, `*.sh`, `*.yaml`, `pyproject.toml`, category scripts
- **Ignored**: `__pycache__`, `.log`, `.tmp`, `.err`, `*_out/`, `.venv`

```bash
git add vbc/        # Only staged files match whitelist
git add video/

git commit -m "Category: Brief description

- Detail 1
- Detail 2"

git push            # Always push after commit
```

## Dependencies

**Package manager**: `uv` (defined in `pyproject.toml`)

**VBC dependencies**:
- `rich` - Dashboard UI
- `pyyaml` - Config loading
- `pyexiftool` - Metadata extraction/copying
- `typer` - CLI framework
- System: `ffmpeg`, `exiftool` binaries

**Dev dependencies**:
- `pytest`, `pytest-cov`, `pytest-mock` (testing)
- `mkdocs`, `mkdocs-material`, `mkdocstrings` (docs)

**Adding dependencies**:
```bash
uv add <package>              # Runtime
uv add --group dev <package>  # Development
```

Document all script dependencies in category `README.md` with installation commands.

## Documentation

**VBC has comprehensive MkDocs documentation** at `docs/`:
- `getting-started/` - Installation, quickstart, configuration
- `user-guide/` - CLI, runtime controls, advanced features
- `architecture/` - Overview, events, pipeline flow
- `api/` - Auto-generated from code

Build docs: `./serve-docs.sh`

For major VBC changes, update relevant docs in `docs/` alongside code.

## Testing

Currently manual testing. When adding tests:
```bash
uv run pytest                    # All tests
uv run pytest tests/unit/        # Unit tests only
uv run pytest -m "not slow"      # Skip integration tests
uv run pytest --cov=vbc          # With coverage
```

Mark slow tests with `@pytest.mark.slow` decorator.
