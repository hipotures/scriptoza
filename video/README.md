# Video Tools

## vbc.py (Video Batch Compression)

Advanced batch video compression script with configuration file, auto-rotation, and EXIF preservation. Supports both GPU (NVENC AV1) and CPU (SVT-AV1) encoding.

### Features

- **Configuration file support** - `conf/vbc.conf` with default settings (threads, quality, GPU/CPU, metadata copying)
- **Auto-rotation** - Regex-based automatic video rotation (e.g., QVR files rotated 180° automatically)
- **EXIF preservation** - GPS coordinates, camera info, and timestamps preserved by default (`-map_metadata`)
- **Automatic color space fix** - Detects and fixes FFmpeg 7.x "reserved color space" errors (bug #11020)
- **Corrupted file detection** - Early detection and skip of corrupted files (moov atom missing)
- Batch compression of MP4 files to AV1 format using GPU or CPU
- Dynamic thread control during runtime (`,`/`.` keys to decrease/increase)
- Manual rotation override (`--rotate-180`)
- Automatic skip of already compressed files (resume after interruption)
- Interactive UI (rich) with panels:
  - Compression status with ETA based on throughput
  - Progress bar with active thread count
  - Currently processing files list with animated spinner
  - Recently completed files (5 most recent)
  - Next files in queue (5 upcoming)
- Graceful shutdown (key `S`) - completes current tasks without starting new ones
- Detailed file logging
- Error handling with `.err` file output
- Automatic cleanup of temporary `.tmp`, `.err`, and `*_colorfix.mp4` files on restart

### Requirements

- Python 3.7+
- ffmpeg with AV1 support:
  - GPU mode: NVIDIA GPU with NVENC AV1 support + `av1_nvenc`
  - CPU mode: `libsvtav1` encoder
- rich (`pip install rich`)

### Installation

```bash
pip install rich
```

### Configuration File

Default settings are stored in `conf/vbc.conf`:

```ini
[general]
threads = 4          # Parallel compression threads
cq = 45              # Quality (lower = better, larger file)
prefetch_factor = 1  # Queue prefetch multiplier
gpu = True           # True = NVENC GPU, False = SVT-AV1 CPU
copy_metadata = True # Copy EXIF (GPS, camera info)

[autorotate]
# Regex patterns for auto-rotation
# NOTE: Use double backslash (\\d) for regex in INI files
QVR_\\d{8}_\\d{6}\\.mp4 = 180  # QVR files rotated 180°
```

**CLI arguments override config file settings.**

### Usage

```bash
python video/vbc.py <input_directory> [options]

# Examples:
python video/vbc.py /path/to/videos  # Uses config defaults
python video/vbc.py /path/to/videos --threads 4 --cq 45
python video/vbc.py /path/to/videos --rotate-180 --no-metadata  # Override auto-rotation, strip EXIF
python video/vbc.py /path/to/videos --cpu  # Use CPU encoder instead of GPU
```

#### Options

- `--threads N` - Number of parallel compression threads (default: from config)
- `--cq N` - Constant quality value for AV1 (default: from config, lower=better quality)
- `--rotate-180` - Rotate ALL videos 180° (overrides auto-rotation from config)
- `--cpu` - Use CPU encoder (SVT-AV1) instead of GPU (NVENC)
- `--prefetch-factor N` - Queue prefetch multiplier 1-5 (default: from config)
- `--no-metadata` - Do not copy EXIF metadata (strips GPS, camera info)

### Runtime Controls

During compression, you can control the process using keyboard shortcuts:

- **`<` or `,`** - Decrease thread count
- **`>` or `.`** - Increase thread count (max 8)
- **`R`** - Refresh file list (add newly discovered files to queue)
- **`S`** - Graceful shutdown (finish current tasks and exit)
- **Ctrl+C** - Immediate interrupt

### Output

- **Compressed files:** `<input_directory>_out/`
- **Log file:** `<input_directory>_out/compression.log`
- **Error files:** `*.err` (for failed compressions or corrupted input files)

### Technical Features

- **Submit-on-demand architecture** - Files submitted in batches (prefetch_factor × threads) for predictable FIFO processing
- **Auto color space fix** - Automatically detects and fixes FFmpeg 7.x "reserved color space" using `hevc_metadata`/`h264_metadata` bitstream filters
- **Early corruption detection** - Runs `ffprobe` before compression to skip corrupted files (moov atom missing)
- **EXIF preservation** - Uses `-map_metadata 0` to preserve GPS, camera info, timestamps
- **Regex-based auto-rotation** - Matches filenames against patterns in config for automatic rotation
- Single-pass CQ (Constant Quality) encoding
- Preserves directory structure
- Thread-safe statistics tracking with condition variables
- Submit-on-demand queue management with dynamic thread scaling
- Auto-refresh UI every 1 second with animated spinner
- 6-hour timeout per file
- Maximum scan depth: 3 directory levels
- Hard limit: 8 concurrent compression threads

### Performance

Typical compression achieves **85-95% space savings** at CQ45, depending on the source video compression:
- Lightly compressed sources: ~95% reduction
- Moderately compressed sources: ~90% reduction
- Already well-compressed sources: ~85% reduction

Average processing speed depends on GPU, but typically:
- ~10-15MB/s throughput on modern NVIDIA GPUs
- ~30-60 seconds per GB of video content

---

## rename_video.py

Universal video file renaming tool supporting multiple camera brands (DJI, Panasonic, Sony).

### Features

- Automatic camera detection from EXIF metadata
- Multi-threaded processing (up to 24 threads)
- Standardized naming: `YYYYMMDD_HHMMSS_WIDTHxHEIGHT_FPSfps_FILESIZE.ext`
- Supports multiple video formats (.mp4, .mov, .avi)
- Automatic collision handling with numeric suffixes
- Fallback to original filename when date is missing

### Requirements

- Python 3.7+
- exiftool

### Installation

```bash
# Install exiftool (Manjaro/Arch)
sudo pacman -S perl-image-exiftool

# Ubuntu/Debian
sudo apt install libimage-exiftool-perl
```

### Usage

```bash
# Run in directory containing video files
cd /path/to/videos
python /path/to/scriptoza/video/rename_video.py
```

### Output Format

Files are renamed to: `YYYYMMDD_HHMMSS_WIDTHxHEIGHT_FPSfps_FILESIZE.ext`

Example:
- `20251025_150032_3840x2160_60fps_785976622.mp4`
- `20251025_150757_5728x3024_60fps_412841693.mov`

### Technical Features

- TAG_ALIASES for flexible EXIF field detection
- Thread-safe file operations
- Automatic lowercase extension normalization
- Handles missing or invalid EXIF data gracefully

---

## sort_video_qvr.sh

Organizes QVR video files into date-based directory structure.

### Features

- Sorts QVR_*.mp4 files by date
- Creates `QVR/YYYYMMDD/` directory structure
- Safe file operations with existence checks

### Usage

```bash
# Run in directory containing QVR files
cd /path/to/videos
bash /path/to/scriptoza/video/sort_video_qvr.sh
```

### Output Structure

```
QVR/
├── 20241025/
│   ├── QVR_20241025_150032.mp4
│   └── QVR_20241025_151234.mp4
└── 20241026/
    └── QVR_20241026_090000.mp4
```

---

## sort_video_sr.sh

Organizes Screen Recording video files into date-based directory structure.

### Features

- Sorts Screen_Recording_*.mp4 files by date
- Creates `SR/YYYYMMDD/` directory structure
- Safe file operations with existence checks

### Usage

```bash
# Run in directory containing Screen Recording files
cd /path/to/videos
bash /path/to/scriptoza/video/sort_video_sr.sh
```

### Output Structure

```
SR/
├── 20241025/
│   ├── Screen_Recording_20241025_150032.mp4
│   └── Screen_Recording_20241025_151234.mp4
└── 20241026/
    └── Screen_Recording_20241026_090000.mp4
```
