# Photo Tools

## rename_photo.py

Universal photo file renaming tool supporting multiple camera brands (Sony, Panasonic) and formats (RAW, JPG).

### Features

- Automatic camera detection from EXIF metadata
- Multi-threaded processing (up to 24 threads)
- Standardized naming: `YYYYMMDD_HHMMSS_MMM.ext` (with milliseconds)
- Supports RAW (.arw), JPEG (.jpg, .jpeg) and HEIF (.hif) formats
- Automatic collision handling with numeric suffixes
- Preserves matching names for RAW+JPG pairs when possible
- Fallback to CreateDate when SubSecCreateDate unavailable

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
# Run in directory containing photo files
cd /path/to/photos
python /path/to/scriptoza/photo/rename_photo.py
```

### Output Format

Files are renamed to: `YYYYMMDD_HHMMSS_MMM.ext`

Examples:
- `20250104_173458_625.jpg` - Sony JPEG
- `20240317_105747_031.arw` - Sony RAW
- `20250307_134019_527.jpg` - Panasonic JPEG

When RAW+JPG pairs are taken at exactly the same time (same millisecond), they will have identical base names:
- `20250104_173458_625.arw`
- `20250104_173458_625.jpg`

If collision occurs (rare, during burst shooting), automatic counter is added:
- `20250104_173458_625.jpg`
- `20250104_173458_625_1.jpg`

### Technical Features

- SubSecCreateDate/SubSecDateTimeOriginal for precise timestamp extraction
- Thread-safe file operations
- Automatic lowercase extension normalization
- Handles missing or invalid EXIF data gracefully
- No dependency on filesize (allows RAW+JPG matching)

### Supported Cameras

- **Sony**: ILCE-7RM5, ILCE-7M3, and other E-mount cameras (ARW, JPG, HIF)
- **Fujifilm**: X-H2S (HIF, JPG)
- **Nikon**: Z 7 II, and other Z-series cameras (NEF, JPG)
- **Canon**: EOS R5, and other R-series cameras (CR3, JPG)
- **Panasonic**: DC-GH7, and other Lumix cameras (JPG)

### Supported File Types

- **RAW**: .arw (Sony), .nef (Nikon), .cr3 (Canon)
- **JPEG**: .jpg, .jpeg (Universal)
- **HEIF**: .hif, .heif (Sony, Fuji)
