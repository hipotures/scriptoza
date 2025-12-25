# Scriptoza

Collection of useful scripts organized by category. Each category has its own directory with detailed documentation.

## 🎬 VBC - Video Batch Compression

**Modern, modular video compression tool with AV1/NVENC support.**

### Quick Start

```bash
# Compress videos with GPU acceleration
uv run vbc/main.py /path/to/videos --gpu --threads 8

# CPU mode with high quality
uv run vbc/main.py /path/to/videos --cpu --cq 35
```

### Features

- 🚀 **Multi-threaded**: Dynamic concurrency control (adjust with `<`/`>` keys)
- 🎯 **Smart Compression**: Camera-specific quality settings, auto-rotation
- 🎨 **Rich UI**: Real-time dashboard with 6 panels
- 🔧 **Flexible**: YAML config + CLI overrides
- 📦 **Deep Metadata**: Full EXIF/GPS preservation with ExifTool

### Documentation

**📚 [Full Documentation](docs/)** - Comprehensive guides and API reference

- [Getting Started](docs/getting-started/installation.md) - Installation & quick start
- [Configuration](docs/getting-started/configuration.md) - All settings explained
- [Runtime Controls](docs/user-guide/runtime-controls.md) - Keyboard shortcuts
- [Advanced Features](docs/user-guide/advanced.md) - Dynamic CQ, auto-rotation
- [Architecture](docs/architecture/overview.md) - System design
- [API Reference](docs/api/) - Auto-generated from code

**🌐 Build docs:** `./serve-docs.sh` → http://127.0.0.1:8000

### Architecture

VBC uses **Clean Architecture** with event-driven design:

```
UI Layer (Rich dashboard, keyboard controls)
    ↓ Events (EventBus)
Pipeline Layer (Orchestrator, queue management)
    ↓ Domain Models
Infrastructure Layer (FFmpeg, ExifTool, FFprobe)
```

See [Architecture Overview](docs/architecture/overview.md) for details.

---

## Other Scripts

### [Video](video/) - Video Utilities

- **rename_video.py** - Universal video renaming (DJI, Panasonic, Sony)
- **check_4k.py** - Scans MP4 tree for 4K/non-4K classification
- **check_collisions.py** - Detects basename collisions
- **sort_video_qvr.sh** - Organizes QVR files by date
- **sort_video_sr.sh** - Organizes Screen Recordings by date

**VBC Utilities** (moved to `vbc/utils/`):
- **move_err_files.py** - Moves failed compression sources
- **copy_failed_videos.py** - Copies failed compression sources

### [Utils](utils/) - General Utilities

- **safe_rename_tt.py** - Safe, multi-format date-based renamer for TikTok downloads. Uses parent directory as prefix, supports dry-run by default, and prevents overwriting.

### [Photo](photo/)

- **rename_photo.py** - Universal photo renaming tool (Sony RAW/JPG, Panasonic JPG) with standardized format: `YYYYMMDD_HHMMSS_MMM.ext` (with milliseconds)
