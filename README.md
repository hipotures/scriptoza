# Scriptoza

Collection of useful scripts organized by category. Each category has its own directory with detailed documentation.

## Categories

### [Video](video/)

- **vbc.py** (Video Batch Compression) - Batch video compression using AV1 with config file, auto-rotation, EXIF preservation, and interactive UI (`<`/`>` keys for thread control)
- **rename_video.py** - Universal video renaming tool (DJI, Panasonic, Sony) with standardized format: `YYYYMMDD_HHMMSS_WIDTHxHEIGHT_FPSfps_FILESIZE.ext`
- **sort_video_qvr.sh** - Organizes QVR video files into `QVR/YYYYMMDD/` directory structure
- **sort_video_sr.sh** - Organizes Screen Recording files into `SR/YYYYMMDD/` directory structure

### [Photo](photo/)

- **rename_photo.py** - Universal photo renaming tool (Sony RAW/JPG, Panasonic JPG) with standardized format: `YYYYMMDD_HHMMSS_MMM.ext` (with milliseconds)
