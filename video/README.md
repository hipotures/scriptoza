# Video Tools

## vbc.py (Video Batch Compression)

Advanced batch video compression script with YAML configuration, auto-rotation, camera detection, and deep EXIF preservation. Supports both GPU (NVENC AV1) and CPU (SVT-AV1) encoding.

### Features

- **YAML Configuration** - `conf/vbc.yaml` for structured settings (threads, quality, filters, dynamic CQ)
- **Deep Camera Detection** - Uses `exiftool` to identify camera hardware (DJI, Sony, Panasonic/GH7)
- **Dynamic CQ** - Automatically applies specific quality settings based on detected camera model
- **Camera Filtering** - Process only videos from specific cameras using `--camera` or config filters
- **Deep EXIF Preservation** - Uses `exiftool` to copy GPS, Lens Info, and MakerNotes from source to MP4 (more reliable than FFmpeg mapping)
- **Hardware Cap Tracking** - Dedicated `hw_cap` counter for "Hardware is lacking required capabilities" errors (tracks GPU limits separately from file errors)
- **Auto-rotation** - Regex-based automatic video rotation (e.g., QVR files rotated 180° automatically)
- **Automatic color space fix** - Detects and fixes FFmpeg 7.x "reserved color space" errors (bug #11020)
- **Corrupted file detection** - Early detection and skip of corrupted files (moov atom missing)
- **Minimum size filter** - Skip files smaller than configurable threshold (default 1 MiB, `--min-size`, set 0 to include empty files)
- **Error marker skip** - Skip files that already have `.err` markers in output (retry only when `--clean-errors` is set)
- **AV1 codec skip** - Optionally skip files already using AV1 codec (`--skip-av1`) to avoid recompressing
- Batch compression of MP4 files to AV1 format using GPU or CPU
- Dynamic thread control during runtime (`,`/`.` keys to decrease/increase)
- Manual rotation override (`--rotate-180`)
- Automatic skip of already compressed files (resume after interruption)
- Interactive UI (rich) with panels:
  - Compression status with ETA based on throughput
  - Progress bar with active thread count
  - Currently processing files list with animated spinner
  - Recently completed files (5 most recent)
  - Next files in queue (5 upcoming) with detected **Camera Model** column
- Graceful shutdown (key `S`) - completes current tasks without starting new ones
- Detailed file logging
- Error handling with `.err` file output
- Automatic cleanup of temporary `.tmp`, `.err`, and `*_colorfix.mp4` files on restart

### Requirements

- Python 3.9+
- Linux/macOS terminal (uses termios/tty; Windows not supported)
- ffmpeg with AV1 support
- exiftool (required for metadata and camera detection)
- Python packages: `rich`, `pyyaml`, `pyexiftool`

### Installation

```bash
pip install rich pyyaml pyexiftool
```

### Configuration File

Default settings are stored in `conf/vbc.yaml`:

```yaml
general:
  threads: 4
  cq: 45
  gpu: true
  copy_metadata: true
  use_exif: true
  
  # Process only these cameras (empty = all)
  filter_cameras: ["DJI OsmoPocket3", "ILCE-7RM5"]
  
  # Specific quality for detected models
  dynamic_cq:
    "DJI OsmoPocket3": 35
    "DC-GH7": 30
    "ILCE-7RM5": 35

autorotate:
  'QVR_\d{8}_\d{6}\.mp4': 180
```

**CLI arguments override config file settings.**

### Usage

```bash
python video/vbc.py <input_directory> [options]

# Examples:
python video/vbc.py /path/to/videos  # Uses YAML defaults
python video/vbc.py /path/to/videos --camera "Sony, DJI"  # Filter specific cameras
python video/vbc.py /path/to/videos --threads 4 --cq 45
python video/vbc.py /path/to/videos --rotate-180 --no-metadata  # Override auto-rotation, strip EXIF
python video/vbc.py /path/to/videos --cpu  # Use CPU encoder instead of GPU
```

#### Options

- `--camera "MODEL"` - Filter by camera model (comma-separated, e.g., "Sony, GH7")
- `--threads N` - Number of parallel compression threads
- `--cq N` - Constant quality value for AV1 (lower=better quality)
- `--rotate-180` - Rotate ALL videos 180°
- `--cpu` - Use CPU encoder (SVT-AV1) instead of GPU (NVENC)
- `--use-exif` / `--no-exif` - Enable/disable deep metadata analysis
- `--no-metadata` - Do not copy EXIF metadata
- `--min-size BYTES` - Minimum input size to process
- `--clean-errors` - Remove existing `.err` markers and retry
- `--skip-av1` - Skip files already using AV1 codec
- `--config PATH` - Load settings from a specific YAML file

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
- **Cached metadata extraction** - Single `ffprobe` call per file with results cached for codec detection, resolution, and FPS display
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

## move_err_files.py

Helper script that relocates source MP4 files for which the compressor created `.err` markers.

### Features

- Derives output directory by appending `_out` to the input directory path
- Finds all `.err` files in the output tree and moves their source `.mp4` counterparts to a safe location
- Preserves relative directory structure under the destination (default: `/tmp/err`)
- Moves `.err` files alongside their source videos after a successful move
- Prompts for confirmation when more than 20 `.err` files are detected; otherwise runs without prompts

### Requirements

- Python 3.9+

### Usage

```bash
# Move all errored videos and .err markers to /tmp/err
python video/move_err_files.py /run/media/xai/.../QVR

# Custom destination
python video/move_err_files.py /run/media/xai/.../QVR --dest /path/to/quarantine
```

### Output

- Moved `.mp4` and `.err` files appear under the destination, keeping their original subdirectory structure.
- Summary printed with counts of moved files and any missing sources.

---

## check_4k.py

Classify MP4 files by resolution and write 4K/non-4K lists with bitrate and codec info.

### Features

- Recursively scans for `.mp4` files and probes width/height/codec/bitrate via `ffprobe`
- Writes tab-separated `files_4k.txt` and `files_non4k.txt` with resolution, bitrate (Mbps), and codec
- Prints progress with per-file summary

### Requirements

- Python 3.9+
- ffprobe available in `PATH`

### Usage

```bash
python video/check_4k.py /path/to/videos \
  --output-4k files_4k.txt \
  --output-non4k files_non4k.txt
```

### Output

- `files_4k.txt` and `files_non4k.txt` in current directory (paths, resolution, bitrate, codec)
- Console summary of counts and locations

---

## check_collisions.py

Find files that would collide after compression because they share a basename but have different extensions.

### Features

- Scans recursively for `.mp4` and `.flv` (extensions configurable in code)
- Reports directories where the same stem exists with multiple extensions
- Shows file sizes to help decide which to keep

### Requirements

- Python 3.9+

### Usage

```bash
python video/check_collisions.py /path/to/videos
```

### Output

- Console report listing each directory with collisions and the conflicting files
- Exit status `0` with printed warning or success message

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
