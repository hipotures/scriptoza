# Video Tools

## rename_video_univ.py

Universal and robust video file renaming tool with deep EXIF tag fallback. Designed to handle various camera models and edge cases (like missing FPS or zeroed dates).

### Features

- **Robust Fallback**: Uses a wide range of EXIF tags for date, resolution, and FPS detection.
- **Handles "n/a"**: Specifically designed to handle cases where `VideoFrameRate` is reported as `n/a`.
- **Universal Format Support**: Works with `.mp4`, `.mov`, `.avi`, `.mkv`, `.m4v`, `.3gp`, `.mts`.
- **Multi-threaded**: Processes files in parallel for maximum speed.
- **Naming Convention**: `YYYYMMDD_HHMMSS_WIDTHxHEIGHT_FPSfps_SIZE.ext`
- **Collision Prevention**: Automatically adds numeric suffixes if a file with the target name already exists.

### Requirements

- Python 3.7+
- `exiftool` installed in system `PATH`.

### Usage

```bash
# Rename files in current directory
rename-video-univ

# Rename files in specific directory
rename-video-univ /path/to/videos
```

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

---

## find_vbc.py

Finds video files (.mp4, .mov) that either have or do not have VBC (Video Batch Compression) metadata tags.

### Features

- Scans for any of the VBC tags (specifically checks for `VBCEncoder`)
- Supports both inclusive and exclusive searches via flags
- Outputs full absolute paths of matching files
- Recursive by default (can be disabled)

### Requirements

- Python 3.7+
- exiftool

### Usage

```bash
# Find files WITH VBC tags
python video/find_vbc.py /path/to/videos --with-vbc

# Find files WITHOUT VBC tags
python video/find_vbc.py /path/to/videos --without-vbc

# Non-recursive search
python video/find_vbc.py . --with-vbc --no-recursive
```
