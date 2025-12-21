# Track Plan: Implement Infrastructure Adapters

## Phase 1: File Scanner
- [x] Task: Implement File Scanner (8feffda)
    - [ ] Sub-task: Write Tests for File Scanner (mock file system)
    - [ ] Sub-task: Implement `vbc/infrastructure/file_scanner.py`
- [ ] Task: Conductor - User Manual Verification 'File Scanner' (Protocol in workflow.md)

## Phase 2: Metadata Extraction (ExifTool & FFprobe)
- [x] Task: Implement ExifTool Adapter (87f8ed2)
    - [ ] Sub-task: Write Tests for ExifTool Adapter (mock pyexiftool)
    - [ ] Sub-task: Implement `vbc/infrastructure/exif_tool.py`
- [x] Task: Implement FFprobe Helper (412c457)
    - [ ] Sub-task: Write Tests for FFprobe parsing
    - [ ] Sub-task: Implement `vbc/infrastructure/ffprobe.py` (or integrate into `ffmpeg.py`)
- [ ] Task: Conductor - User Manual Verification 'Metadata Extraction' (Protocol in workflow.md)

## Phase 3: FFmpeg Compression Adapter
- [x] Task: Implement FFmpeg Compressor (ad54307)
    - [ ] Sub-task: Write Tests for FFmpeg command generation
    - [ ] Sub-task: Implement `vbc/infrastructure/ffmpeg.py` (focus on command building and execution)
    - [ ] Sub-task: Implement Progress Parsing (emit events)
- [ ] Task: Conductor - User Manual Verification 'FFmpeg Compression Adapter' (Protocol in workflow.md)
