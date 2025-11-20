# Video Tools

## video_batch_compression.py

Advanced batch video compression script utilizing NVENC AV1 (hardware encoding on NVIDIA GPU).

### Features

- Batch compression of MP4 files to AV1 format using GPU acceleration
- Dynamic thread control during runtime (`,` and `.` keys)
- Optional 180° video rotation (`--rotate-180`)
- Automatic skip of already compressed files (resume after interruption)
- NVENC session guard that backs off threads and retries when encoder rejects new sessions
- Interactive UI (rich) with panels:
  - Compression status with ETA based on throughput
  - Progress bar with active thread count
  - Currently processing files list
  - Recently completed files (5 most recent)
  - Next files in queue (5 upcoming)
- Graceful shutdown (key `S`) - completes current tasks without starting new ones
- Detailed file logging
- Error handling with `.err` file output
- Automatic cleanup of temporary `.tmp` files on restart

### Requirements

- Python 3.7+
- NVIDIA GPU with NVENC AV1 support
- ffmpeg with av1_nvenc support
- rich (`pip install rich`)

### Installation

```bash
pip install rich
```

### Usage

```bash
python video/video_batch_compression.py <input_directory> [options]

# Examples:
python video/video_batch_compression.py /path/to/videos --threads 4 --cq 45
python video/video_batch_compression.py /path/to/videos --threads 4 --cq 45 --rotate-180
```

#### Options

- `--threads N` - Number of parallel compression threads (default: 4)
- `--cq N` - Constant quality value for AV1 (default: 45, lower=better quality)
- `--rotate-180` - Rotate video 180 degrees (for upside-down phone recordings)

### Runtime Controls

During compression, you can control the process using keyboard shortcuts:

- **`<`** - Decrease thread count
- **`>`** - Increase thread count
- **`S`** - Graceful shutdown (finish current tasks and exit)
- **Ctrl+C** - Immediate interrupt
- NVENC backoff (automatic): when the encoder refuses a new session, the script halves the thread cap and retries twice with a short delay. Stay at or below the shown cap to avoid repeated `.err` files.

### Output

- **Compressed files:** `<input_directory>_out/`
- **Log file:** `<input_directory>_out/compression.log`
- **Error files:** `*.err` (for failed compressions; NVENC issues are annotated with a hint to lower concurrency)

### Technical Features

- Single-pass CQ (Constant Quality) encoding
- Preserves directory structure
- Thread-safe statistics tracking
- Automatic retry/backoff on NVENC session errors (reduces concurrent threads and retries twice)
- Condition variable for dynamic thread control
- Auto-refresh UI every 0.2s
- 6-hour timeout per file
- Maximum scan depth: 3 directory levels

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
