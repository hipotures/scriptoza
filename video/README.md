# Video Tools

## video_batch_compression.py

Advanced batch video compression script utilizing NVENC AV1 (hardware encoding on NVIDIA GPU).

### Features

- Batch compression of MP4 files to AV1 format using GPU acceleration
- Dynamic thread control during runtime (`,` and `.` keys)
- Optional 180° video rotation (`--rotate-180`)
- Automatic skip of already compressed files (resume after interruption)
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

- **`,`** (comma) - Decrease thread count
- **`.`** (period) - Increase thread count
- **`S`** - Graceful shutdown (finish current tasks and exit)
- **Ctrl+C** - Immediate interrupt

### Output

- **Compressed files:** `<input_directory>_out/`
- **Log file:** `<input_directory>_out/compression.log`
- **Error files:** `*.err` (for failed compressions)

### Technical Features

- Single-pass CQ (Constant Quality) encoding
- Preserves directory structure
- Thread-safe statistics tracking
- Condition variable for dynamic thread control
- Auto-refresh UI every 0.2s
- 6-hour timeout per file
- Maximum scan depth: 3 directory levels

### Performance

Typical compression achieves **94-95% space savings** while maintaining good quality at CQ45.

For example:
- 3.6GB video → ~180MB (95% reduction)
- 1.4GB video → ~70MB (95% reduction)
- 640MB video → ~32MB (95% reduction)

Average processing speed depends on GPU, but typically:
- ~10-15MB/s throughput on modern NVIDIA GPUs
- ~30-60 seconds per GB of video content
