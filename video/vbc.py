#!/usr/bin/env python3
# /// script
# dependencies = [
#   "rich",
#   "pyyaml",
#   "pyexiftool",
# ]
# ///
import sys
import os
from pathlib import Path

# --- DEDICATED VENV ACTIVATION ---
# Check if we are already in a virtual environment
if not os.environ.get('VIRTUAL_ENV') and not os.environ.get('UV_VENV_PATH'):
    # Look for .venv in the repository root (one level up from /video)
    venv_root = Path(__file__).resolve().parent.parent / '.venv'
    venv_python = venv_root / 'bin' / 'python'
    if venv_python.exists():
        # Set the environment variable so the next process knows it's active
        os.environ['VIRTUAL_ENV'] = str(venv_root)
        # Re-execute the script using the dedicated .venv python interpreter
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)
# --------------------------------

"""
Batch video compression script using NVENC AV1 with rich UI
Compresses video files (configurable extensions) to AV1/MP4 with specified quality
"""

import argparse
import yaml
import logging
import re
import select
import subprocess
import threading
import time
import termios
import tty
import shutil
import csv
import json
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timedelta
from typing import List, Set, Dict, Optional, Deque

# Optional deep metadata analysis
try:
    import exiftool
except ImportError:
    exiftool = None

try:
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import Progress, BarColumn, TextColumn
    from rich.table import Table
    from rich.console import Console, Group
    from rich.text import Text
except ImportError:
    print("Error: rich not installed. Install with: pip install rich")
    sys.exit(1)


def load_config(config_path: Optional[Path] = None) -> Dict:
    """
    Load configuration from conf/vbc.yaml or a provided path.
    Returns dict with default values if config file doesn't exist or can't be read
    """
    defaults = {
        'threads': 4,
        'cq': 45,
        'prefetch_factor': 1,
        'gpu': True,
        'copy_metadata': True,
        'extensions': ['mp4', 'flv', 'webm'],
        'min_size_bytes': 1024 * 1024,  # 1 MiB
        'clean_errors': False,
        'skip_av1': False,
        'strip_unicode_display': True,
        'use_exif': True,
        'dynamic_cq': {},
        'filter_cameras': [],
        'autorotate_patterns': {}
    }

    config_file = Path(config_path) if config_path else Path(__file__).resolve().parent.parent / 'conf' / 'vbc.yaml'

    if not config_file.exists():
        if config_path:
            print(f"Warning: Config file not found at {config_file}, using defaults.")
        return defaults

    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)

        if 'general' in config:
            gen = config['general']
            defaults.update({
                'threads': gen.get('threads', defaults['threads']),
                'cq': gen.get('cq', defaults['cq']),
                'prefetch_factor': gen.get('prefetch_factor', defaults['prefetch_factor']),
                'gpu': gen.get('gpu', defaults['gpu']),
                'copy_metadata': gen.get('copy_metadata', defaults['copy_metadata']),
                'extensions': gen.get('extensions', defaults['extensions']),
                'min_size_bytes': gen.get('min_size_bytes', defaults['min_size_bytes']),
                'clean_errors': gen.get('clean_errors', defaults['clean_errors']),
                'skip_av1': gen.get('skip_av1', defaults['skip_av1']),
                'strip_unicode_display': gen.get('strip_unicode_display', defaults['strip_unicode_display']),
                'use_exif': gen.get('use_exif', defaults['use_exif']),
                'dynamic_cq': gen.get('dynamic_cq', defaults['dynamic_cq']),
                'filter_cameras': gen.get('filter_cameras', defaults['filter_cameras'])
            })

        if 'autorotate' in config:
            defaults['autorotate_patterns'] = config['autorotate']

        return defaults
    except Exception as e:
        print(f"Warning: Failed to read config file {config_file}: {e}")
        return defaults


class ThreadController:
    """Dynamic thread control with condition variable"""
    def __init__(self, initial_threads: int, max_threads_limit: int = 8):
        self.condition = threading.Condition()
        self.max_threads_limit = max_threads_limit
        self.max_threads = min(initial_threads, max_threads_limit)
        self.active_threads = 0
        self.min_threads = 1
        self.shutdown_requested = False

    def acquire(self):
        """Acquire a thread slot - returns False if shutdown requested"""
        with self.condition:
            # Wait until we can start a new thread
            while True:
                if self.shutdown_requested:
                    return False
                if self.active_threads < self.max_threads:
                    self.active_threads += 1
                    return True
                # Wait for a slot to become available
                self.condition.wait(timeout=0.5)

    def release(self):
        """Release a thread slot"""
        with self.condition:
            self.active_threads -= 1
            # Notify waiting threads that a slot is available
            self.condition.notify()

    def increase(self):
        """Increase max threads by 1"""
        with self.condition:
            if self.shutdown_requested:
                return False
            if self.max_threads < self.max_threads_limit:
                self.max_threads += 1
                # Notify waiting threads that more slots are available
                self.condition.notify()
                return True
        return False

    def decrease(self):
        """Decrease max threads by 1"""
        with self.condition:
            if self.max_threads > self.min_threads:
                self.max_threads -= 1
                return True
        return False

    def graceful_shutdown(self):
        """Request graceful shutdown - no new tasks will start"""
        with self.condition:
            self.shutdown_requested = True
            self.max_threads = 0
            # Wake up all waiting threads so they can see shutdown flag
            self.condition.notify_all()
            return True


    def is_shutdown_requested(self) -> bool:
        """Check if shutdown was requested"""
        with self.condition:
            return self.shutdown_requested

    def get_current(self) -> int:
        """Get current max threads"""
        with self.condition:
            return self.max_threads

    def get_active(self) -> int:
        """Get current active threads"""
        with self.condition:
            return self.active_threads


class CompressionStats:
    """Thread-safe statistics tracking"""
    def __init__(self):
        self.lock = threading.Lock()
        self.success_count = 0
        self.error_count = 0
        self.skipped_count = 0
        self.camera_skip_count = 0
        self.av1_skip_count = 0
        self.hw_cap_count = 0
        self.total_input_size = 0
        self.total_output_size = 0
        self.completed: Deque[Dict] = deque(maxlen=5)
        self.processing: Dict[str, Dict] = {}
        self.start_time = datetime.now()

    def add_success(self, result: Dict):
        with self.lock:
            self.success_count += 1
            self.total_input_size += result['input_size']
            self.total_output_size += result['output_size']
            self.completed.append(result)

    def add_error(self):
        with self.lock:
            self.error_count += 1

    def add_hw_cap(self):
        with self.lock:
            self.hw_cap_count += 1

    def add_camera_skip(self):
        with self.lock:
            self.camera_skip_count += 1

    def add_av1_skip(self):
        with self.lock:
            self.av1_skip_count += 1

    def add_skipped(self):
        with self.lock:
            self.skipped_count += 1

    def start_processing(self, filename: str, size: int, rotation_angle: int = 0, metadata: Optional[Dict] = None):
        with self.lock:
            self.processing[filename] = {
                'size': size,
                'start_time': datetime.now(),
                'rotation_angle': rotation_angle,
                'metadata': metadata or {}
            }

    def stop_processing(self, filename: str):
        with self.lock:
            if filename in self.processing:
                del self.processing[filename]

    def get_stats(self) -> Dict:
        with self.lock:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            throughput = self.total_input_size / elapsed if elapsed > 0 else 0
            avg_compression = 0
            if self.total_input_size > 0:
                avg_compression = (1 - self.total_output_size / self.total_input_size) * 100

            return {
                'success': self.success_count,
                'error': self.error_count,
                'skipped': self.skipped_count,
                'hw_cap': self.hw_cap_count,
                'camera_skip': self.camera_skip_count,
                'av1_skip': self.av1_skip_count,
                'total_input_size': self.total_input_size,
                'total_output_size': self.total_output_size,
                'avg_compression': avg_compression,
                'elapsed': elapsed,
                'throughput': throughput,
                'completed': list(self.completed),
                'processing': dict(self.processing)
            }


class VideoCompressor:
    def __init__(self, input_dir: Path, threads: int = 8, cq: int = 45, rotate_180: bool = False, use_cpu: bool = False, prefetch_factor: int = 1, copy_metadata: bool = True, extensions: List[str] = None, autorotate_patterns: Dict[str, int] = None, min_size_bytes: int = 1024 * 1024, clean_errors: bool = False, skip_av1: bool = False, strip_unicode_display: bool = True, use_exif: bool = False, dynamic_cq: Dict[str, int] = None, filter_cameras: List[str] = None):
        self.input_dir = input_dir.resolve()
        self.output_dir = Path(f"{self.input_dir}_out")
        self.thread_controller = ThreadController(threads)
        self.cq = cq
        self.rotate_180 = rotate_180
        self.use_cpu = use_cpu
        self.prefetch_factor = prefetch_factor
        self.copy_metadata = copy_metadata
        self.extensions = extensions or ['mp4']
        self.autorotate_patterns = autorotate_patterns or {}
        self.min_size_bytes = max(0, int(min_size_bytes))
        self.clean_errors = clean_errors
        self.skip_av1 = skip_av1
        self.strip_unicode_display = strip_unicode_display
        self.use_exif = use_exif and (exiftool is not None)
        self.dynamic_cq = dynamic_cq or {}
        self.filter_cameras = filter_cameras or []
        self.max_depth = 3
        self.stats = CompressionStats()
        self.console = Console()
        self.stop_keyboard_thread = threading.Event()
        self.last_action = ""
        self.last_action_time = None
        self.last_action_lock = threading.Lock()

        # Initialize ExifTool if needed
        self.et = None
        if self.use_exif:
            try:
                # Use ExifToolHelper for newer pyexiftool versions (0.5+)
                self.et = exiftool.ExifToolHelper()
                self.et.run()
            except Exception as e:
                self.logger.warning(f"Failed to start ExifToolHelper: {e}")
                self.use_exif = False

        # Precomputed counters for UI
        self.files_to_compress_count = 0
        self.already_compressed_count = 0
        self.ignored_small_count = 0
        self.ignored_err_count = 0
        self.ignored_av1_count = 0
        self.ignored_hw_cap_count = 0
        self.ignored_camera_count = 0

        # Refresh functionality
        self.refresh_requested = False
        self.refresh_lock = threading.Lock()
        self.currently_processing_files: Set[Path] = set()
        self.processing_files_lock = threading.Lock()
        self.ui_lock = threading.Lock()

        # Spinner animation frame counter
        self.spinner_frame = 0
        self.spinner_lock = threading.Lock()

        # Cache for queue metadata to avoid repeated ffprobe calls during UI refresh
        self.queue_metadata_cache: Dict[Path, Dict] = {}
        self.queue_metadata_lock = threading.Lock()

        # Setup file logging only
        log_file = self.output_dir / "compression.log"
        self.output_dir.mkdir(exist_ok=True)

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.FileHandler(log_file)]
        )
        self.logger = logging.getLogger(__name__)

    def get_depth(self, path: Path) -> int:
        """Calculate depth of path relative to input_dir"""
        try:
            relative = path.relative_to(self.input_dir)
            return len(relative.parts) - 1
        except ValueError:
            return 999

    def find_input_files(self) -> tuple[List[Path], int]:
        """Find all video files with configured extensions in input directory (max 3 levels deep)"""
        all_files = []
        ignored_small = 0
        for ext in self.extensions:
            for video_file in self.input_dir.rglob(f"*.{ext}"):
                depth = self.get_depth(video_file)
                if depth <= self.max_depth:
                    try:
                        if video_file.stat().st_size < self.min_size_bytes:
                            ignored_small += 1
                            continue
                    except OSError:
                        # If file disappears or unreadable, skip counting it as ignored
                        continue
                    all_files.append(video_file)
        return sorted(all_files), ignored_small

    def find_error_marked_inputs(self, input_files: List[Path]) -> tuple[Set[Path], Set[Path]]:
        """Return (general_errors, hw_cap_errors) sets of input files that have existing .err markers."""
        err_marked: Set[Path] = set()
        hw_cap_marked: Set[Path] = set()
        
        for input_file in input_files:
            output_path = self.get_output_path(input_file)
            err_file = output_path.parent / f"{output_path.stem}.err"
            if err_file.exists():
                try:
                    content = err_file.read_text()
                    if "Hardware is lacking required capabilities" in content:
                        hw_cap_marked.add(input_file)
                    else:
                        err_marked.add(input_file)
                except:
                    err_marked.add(input_file)
        return err_marked, hw_cap_marked

    def get_output_path(self, input_file: Path) -> Path:
        """Get corresponding output path with .mp4 extension"""
        relative = input_file.relative_to(self.input_dir)
        return self.output_dir / relative.with_suffix('.mp4')

    def find_completed_files(self) -> Set[Path]:
        """Find input files that have been compressed"""
        completed = set()
        if not self.output_dir.exists():
            return completed

        for mp4_file in self.output_dir.rglob("*.mp4"):
            relative = mp4_file.relative_to(self.output_dir)
            stem = relative.stem

            # Check all configured extensions for matching input file
            for ext in self.extensions:
                input_path = self.input_dir / relative.parent / f"{stem}.{ext}"
                if input_path.exists():
                    completed.add(input_path)
                    break

        return completed

    def cleanup_temp_files(self):
        """Remove temporary files from output directory. .err files removed only if clean_errors is True."""
        if not self.output_dir.exists():
            return

        tmp_count = 0
        colorfix_count = 0
        err_count = 0

        for tmp_file in self.output_dir.rglob("*.tmp"):
            tmp_file.unlink()
            tmp_count += 1

        if self.clean_errors:
            for err_file in self.output_dir.rglob("*.err"):
                err_file.unlink()
                err_count += 1

        for colorfix_file in self.output_dir.rglob("*_colorfix.mp4"):
            colorfix_file.unlink()
            colorfix_count += 1

        if tmp_count > 0 or err_count > 0 or colorfix_count > 0:
            self.logger.info(f"Cleaned up {tmp_count} .tmp, {err_count} .err, and {colorfix_count} *_colorfix.mp4 files")

    def get_auto_rotation(self, input_file: Path) -> int:
        """
        Check if file matches auto-rotation patterns from config.
        Returns rotation angle (0, 90, 180, 270) or 0 if no match.
        """
        if not self.autorotate_patterns:
            return 0

        filename = input_file.name

        for pattern, angle in self.autorotate_patterns.items():
            try:
                # Case-insensitive match (ConfigParser lowercases option names)
                if re.match(pattern, filename, re.IGNORECASE):
                    self.logger.info(f"Auto-rotation matched: {filename} → {angle}° (pattern: {pattern})")
                    return angle
            except re.error as e:
                self.logger.warning(f"Invalid regex pattern in config: {pattern} - {e}")
                continue

        return 0

    def get_queue_metadata(self, file: Path) -> Dict:
        """
        Return cached metadata for queue display; run ffprobe once per file and cache result.
        """
        if not file.exists():
            with self.queue_metadata_lock:
                self.queue_metadata_cache.pop(file, None)
            return {}

        with self.queue_metadata_lock:
            cached = self.queue_metadata_cache.get(file)
        if cached is not None:
            return cached

        metadata: Dict = {}
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,avg_frame_rate,codec_name',
                '-of', 'default=noprint_wrappers=1',
                str(file)
            ], capture_output=True, text=True, timeout=5)

            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line.startswith('codec_name='):
                        codec = line.split('=')[1].strip().lower()
                        if codec:
                            metadata['codec'] = codec
                    elif line.startswith('width='):
                        try:
                            width = int(line.split('=')[1])
                            metadata['width'] = width
                        except ValueError:
                            pass
                    elif line.startswith('height='):
                        try:
                            height = int(line.split('=')[1])
                            metadata['height'] = height
                        except ValueError:
                            pass
                    elif line.startswith('avg_frame_rate='):
                        fps_str = line.split('=')[1]
                        try:
                            if '/' in fps_str:
                                num, den = fps_str.split('/')
                                if int(den) > 0:
                                    fps = round(float(num) / float(den))
                                    if fps <= 240:
                                        metadata['fps'] = fps
                            else:
                                fps = round(float(fps_str))
                                if fps <= 240:
                                    metadata['fps'] = fps
                        except (ValueError, ZeroDivisionError):
                            pass

                if 'width' in metadata and 'height' in metadata:
                    metadata['megapixels'] = round(metadata['width'] * metadata['height'] / 1_000_000)

            # Deep metadata analysis with ExifTool for dynamic CQ
            if self.use_exif and self.et:
                try:
                    # Request specific tags to identify camera
                    # get_tags in ExifToolHelper takes list of files and list of tags
                    results = self.et.get_tags([str(file)], tags=['Model', 'Make', 'DeviceModelName', 'Encoder'])
                    if results and isinstance(results, list) and len(results) > 0:
                        tags = results[0]
                        
                        # Extract model and make
                        model_val = str(
                            tags.get('EXIF:Model') or 
                            tags.get('QuickTime:Model') or 
                            tags.get('XML:DeviceModelName') or 
                            tags.get('QuickTime:Encoder') or 
                            tags.get('Model') or 
                            ""
                        )
                        make_val = str(tags.get('EXIF:Make') or tags.get('QuickTime:Make') or tags.get('Make') or "")
                        
                        if model_val:
                            # Clean model value for display
                            metadata['camera_raw'] = model_val
                            
                            # Check for dynamic CQ matches
                            matched = False
                            for pattern, custom_cq in self.dynamic_cq.items():
                                if pattern in model_val:
                                    metadata['camera'] = pattern
                                    metadata['custom_cq'] = custom_cq
                                    matched = True
                                    break
                            
                            if not matched:
                                # Fallback: use manufacturer if model didn't match any pattern
                                if "Sony" in make_val or "Sony" in model_val: metadata['camera'] = "Sony"
                                elif "Panasonic" in make_val: metadata['camera'] = "Pana"
                                elif "DJI" in make_val or "DJI" in model_val: metadata['camera'] = "DJI"
                                else: metadata['camera'] = model_val[:10] # Generic short model name
                except Exception as e:
                    self.logger.debug(f"ExifTool analysis failed for {file.name}: {e}")

        except Exception as e:
            self.logger.debug(f"Queue metadata probe failed for {file.name}: {e}")

        with self.queue_metadata_lock:
            self.queue_metadata_cache[file] = metadata

        return metadata

    def check_and_fix_color_space(self, input_file: Path) -> tuple[str, Path, Optional[Path], Optional[Dict]]:
        """
        Check if video has reserved color space and fix it if needed.
        Also extracts video metadata (resolution, FPS).

        Returns:
            tuple: (status, file_to_compress, temp_file_path, metadata)
                - status: "ok" | "fixed" | "corrupted"
                - file_to_compress: Path to use for compression (original or fixed)
                - temp_file_path: Path to temporary fixed file (None if no fix needed)
                - metadata: Dict with width, height, megapixels, fps
        """
        try:
            # Check color space and extract metadata using ffprobe
            result = subprocess.run(
                [
                    'ffprobe',
                    '-v', 'error',
                    '-select_streams', 'v:0',
                    # Use avg_frame_rate; r_frame_rate is often the container timebase (e.g., 120) not real FPS
                    '-show_entries', 'stream=color_space,codec_name,width,height,avg_frame_rate',
                    '-of', 'default=noprint_wrappers=1',
                    str(input_file)
                ],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                # ffprobe failed - file is corrupted
                error_msg = result.stderr.strip() if result.stderr else "ffprobe failed"
                self.logger.error(f"Corrupted file detected (ffprobe failed): {input_file.name} - {error_msg}")
                return ("corrupted", input_file, None, None)

            # Parse output
            output_lines = result.stdout.strip().split('\n')
            color_space = None
            codec_name = None
            width = None
            height = None
            fps_str = None

            for line in output_lines:
                if line.startswith('color_space='):
                    color_space = line.split('=')[1]
                elif line.startswith('codec_name='):
                    codec_name = line.split('=')[1]
                elif line.startswith('width='):
                    try:
                        width = int(line.split('=')[1])
                    except ValueError:
                        pass
                elif line.startswith('height='):
                    try:
                        height = int(line.split('=')[1])
                    except ValueError:
                        pass
                elif line.startswith('avg_frame_rate='):
                    fps_str = line.split('=')[1]

            # Calculate metadata
            metadata = {}
            if width and height:
                metadata['width'] = width
                metadata['height'] = height
                total_pixels = width * height
                metadata['megapixels'] = round(total_pixels / 1_000_000)

            # Calculate FPS (handle fraction like "30000/1001" → 29.97)
            if fps_str:
                try:
                    if '/' in fps_str:
                        num, den = fps_str.split('/')
                        if int(den) > 0:  # Avoid division by zero
                            fps = round(float(num) / float(den))
                            # Only store if reasonable (< 240 fps) - higher values are likely timebase errors
                            if fps <= 240:
                                metadata['fps'] = fps
                    else:
                        fps = round(float(fps_str))
                        if fps <= 240:
                            metadata['fps'] = fps
                except (ValueError, ZeroDivisionError):
                    pass

            # If color space is "reserved", fix it
            if color_space == 'reserved':
                self.logger.info(f"Detected reserved color space in {input_file.name}, applying fix...")

                # Create temporary fixed file in output directory
                output_file = self.get_output_path(input_file)
                temp_fixed = output_file.parent / f"{output_file.stem}_colorfix.mp4"
                temp_fixed.parent.mkdir(parents=True, exist_ok=True)

                # Choose appropriate bitstream filter based on codec
                if codec_name == 'hevc':
                    bsf = 'hevc_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1'
                elif codec_name == 'h264':
                    bsf = 'h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1'
                else:
                    # Unsupported codec for metadata fix
                    self.logger.warning(f"Cannot fix color space for codec {codec_name}, proceeding with original file")
                    return ("ok", input_file, None, metadata)

                # Fix color space metadata using bitstream filter
                fix_result = subprocess.run(
                    [
                        'ffmpeg',
                        '-i', str(input_file),
                        '-c', 'copy',
                        '-bsf:v', bsf,
                        str(temp_fixed),
                        '-y',
                        '-hide_banner',
                        '-loglevel', 'error'
                    ],
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout for remux
                )

                if fix_result.returncode == 0 and temp_fixed.exists():
                    self.logger.info(f"Successfully fixed color space for {input_file.name}")
                    return ("fixed", temp_fixed, temp_fixed, metadata)
                else:
                    # Fix failed - cleanup and use original
                    if temp_fixed.exists():
                        temp_fixed.unlink()
                    self.logger.warning(f"Failed to fix color space for {input_file.name}, proceeding with original")
                    return ("ok", input_file, None, metadata)

            # Color space is OK - use original file
            return ("ok", input_file, None, metadata)

        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout while checking/fixing color space for {input_file.name}")
            return ("ok", input_file, None, {})
        except Exception as e:
            self.logger.error(f"Error checking color space for {input_file.name}: {e}")
            return ("ok", input_file, None, {})

    def set_last_action(self, action: str):
        """Set last keyboard action for display with timestamp"""
        with self.last_action_lock:
            self.last_action = action
            self.last_action_time = datetime.now()

    def get_last_action(self) -> str:
        """Get last keyboard action (clears after 1 minute)"""
        with self.last_action_lock:
            if self.last_action and self.last_action_time:
                elapsed = (datetime.now() - self.last_action_time).total_seconds()
                if elapsed > 60:  # Clear after 1 minute
                    self.last_action = ""
                    self.last_action_time = None
            return self.last_action

    def keyboard_listener(self):
        """Listen for keyboard input in separate thread"""
        # Save terminal settings
        if not sys.stdin.isatty():
            return

        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())
            while not self.stop_keyboard_thread.is_set():
                if sys.stdin in select.select([sys.stdin], [], [], 0.1)[0]:
                    char = sys.stdin.read(1)
                    # Increase threads: . or > (same key, with/without Shift)
                    if char in ('.', '>'):
                        if self.thread_controller.increase():
                            new_count = self.thread_controller.get_current()
                            self.set_last_action(f"Threads: {new_count-1} → {new_count}")
                            self.logger.info(f"Increased threads to {new_count}")
                    # Decrease threads: , or < (same key, with/without Shift)
                    elif char in (',', '<'):
                        old_count = self.thread_controller.get_current()
                        if self.thread_controller.decrease():
                            new_count = self.thread_controller.get_current()
                            self.set_last_action(f"Threads: {old_count} → {new_count}")
                            self.logger.info(f"Decreased threads to {new_count}")
                    # Shutdown: S or s
                    elif char in ('S', 's'):
                        if self.thread_controller.graceful_shutdown():
                            self.set_last_action("SHUTDOWN requested")
                            self.logger.info("Graceful shutdown requested - finishing current tasks...")
                    # Refresh file list: R or r
                    elif char in ('R', 'r'):
                        with self.refresh_lock:
                            self.refresh_requested = True
                        self.set_last_action("REFRESH requested")
                        self.logger.info("File list refresh requested")
        except Exception as e:
            self.logger.error(f"Keyboard listener error: {e}")
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    def compress_file(self, input_file: Path) -> dict:
        """Compress a single video file using NVENC AV1"""
        filename = input_file.name

        # Check file and get size BEFORE acquiring thread slot
        try:
            if not input_file.exists():
                return {
                    'status': 'skipped',
                    'input': input_file,
                    'error': 'File was deleted or moved'
                }
            input_size = input_file.stat().st_size
        except Exception as e:
            return {
                'status': 'error',
                'input': input_file,
                'error': f'Failed to read file: {str(e)}'
            }

        # Check for output collision BEFORE processing
        output_path = self.get_output_path(input_file)
        if output_path.exists():
            # Log collision for later grep
            self.logger.warning(f"COLLISION: Output exists, skipping input={input_file} output={output_path}")
            return {
                'status': 'skipped',
                'input': input_file,
                'error': f'Output file already exists: {output_path.name}'
            }

        # Check and fix color space if needed (before acquiring thread slot)
        validity_status, file_to_compress, temp_fixed_file, metadata_base = self.check_and_fix_color_space(input_file)
        
        # Get full metadata (including camera model and custom CQ)
        metadata = self.get_queue_metadata(input_file)
        if metadata_base:
            metadata.update(metadata_base)

        # Skip corrupted files immediately without trying to compress
        if validity_status == "corrupted":
            err_file = self.get_output_path(input_file).parent / f"{input_file.stem}.err"
            try:
                err_file.parent.mkdir(parents=True, exist_ok=True)
                err_file.write_text("File is corrupted (ffprobe failed to read). Skipped.")
            except:
                pass
            self.logger.error(f"Skipped corrupted file: {filename}")
            return {
                'status': 'error',
                'input': input_file,
                'error': 'File is corrupted (ffprobe failed)'
            }

        # Live filtering: AV1 skip
        if self.skip_av1 and metadata.get('codec') == 'av1':
            return {
                'status': 'av1_skip',
                'input': input_file,
                'error': 'Already AV1 codec'
            }

        # Live filtering: Camera model
        if self.filter_cameras:
            cam_model = metadata.get('camera') or metadata.get('camera_raw', "")
            matched = False
            for filter_pattern in self.filter_cameras:
                if filter_pattern.lower() in cam_model.lower():
                    matched = True
                    break
            
            if not matched:
                return {
                    'status': 'camera_skip',
                    'input': input_file,
                    'error': f'Camera model "{cam_model}" not in filter'
                }

        # Determine rotation angle
        # CLI flag --rotate-180 takes priority, otherwise check auto-rotation config
        if self.rotate_180:
            rotation_angle = 180
        else:
            rotation_angle = self.get_auto_rotation(input_file)

        # Determine CQ value (use custom if camera detected, otherwise global)
        active_cq = metadata.get('custom_cq', self.cq)
        if 'camera' in metadata:
            self.logger.info(f"Detected camera: {metadata['camera']} - using custom CQ: {active_cq}")

        # Acquire thread slot (returns False if shutdown requested)
        if not self.thread_controller.acquire():
            # Cleanup temp file if created
            if temp_fixed_file and temp_fixed_file.exists():
                temp_fixed_file.unlink()
            return {
                'status': 'skipped',
                'input': input_file,
                'error': 'Shutdown requested'
            }

        # Mark as processing immediately after acquiring slot
        self.stats.start_processing(filename, input_size, rotation_angle, metadata)

        # Add to currently processing files
        with self.processing_files_lock:
            self.currently_processing_files.add(input_file)

        try:
            output_file = self.get_output_path(input_file)
            tmp_file = output_file.parent / f"{output_file.stem}.tmp"
            err_file = output_file.parent / f"{output_file.stem}.err"

            # Create output directory if needed
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # Build ffmpeg command
            if self.use_cpu:
                    # CPU-based SVT-AV1 encoder
                    cmd = [
                        'ffmpeg',
                        '-fflags', '+genpts+igndts',  # Generate timestamps and ignore input DTS
                        '-avoid_negative_ts', 'make_zero',  # Fix negative timestamps
                        '-i', str(file_to_compress),
                    ]

                    # Add rotation filter if needed
                    if rotation_angle == 180:
                        cmd.extend(['-vf', 'hflip,vflip'])
                    elif rotation_angle == 90:
                        cmd.extend(['-vf', 'transpose=1'])
                    elif rotation_angle == 270:
                        cmd.extend(['-vf', 'transpose=2'])

                    cmd.extend([
                        '-c:v', 'libsvtav1',
                        '-preset', '8',  # Preset 8 = fast encoding
                        '-crf', str(active_cq),
                        '-c:a', 'copy',
                    ])

                    # Copy EXIF metadata if enabled
                    if self.copy_metadata:
                        cmd.extend(['-map_metadata', '0', '-movflags', 'use_metadata_tags'])

                    cmd.extend([
                        '-f', 'mp4',
                        str(tmp_file),
                        '-y',
                        '-hide_banner',
                        '-loglevel', 'error',
                        '-stats'
                    ])
            else:
                # GPU-based NVENC AV1 encoder
                cmd = [
                    'ffmpeg',
                    '-vsync', '0',
                    '-hwaccel', 'cuda',
                    '-fflags', '+genpts+igndts',  # Generate timestamps and ignore input DTS
                    '-avoid_negative_ts', 'make_zero',  # Fix negative timestamps
                    '-i', str(file_to_compress),
                ]

                # Add rotation filter if needed
                if rotation_angle == 180:
                    cmd.extend(['-vf', 'hflip,vflip'])
                elif rotation_angle == 90:
                    cmd.extend(['-vf', 'transpose=1'])
                elif rotation_angle == 270:
                    cmd.extend(['-vf', 'transpose=2'])

                cmd.extend([
                    '-c:v', 'av1_nvenc',
                    '-preset', 'p7',
                    '-cq', str(active_cq),
                    '-b:v', '0',
                    '-c:a', 'copy',
                ])

                # Copy EXIF metadata if enabled
                if self.copy_metadata:
                    cmd.extend(['-map_metadata', '0', '-movflags', 'use_metadata_tags'])

                cmd.extend([
                    '-f', 'mp4',
                    str(tmp_file),
                    '-y',
                    '-hide_banner',
                    '-loglevel', 'error',
                    '-stats'
                ])

            start_time = datetime.now()

            # Run compression
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=21600  # 6 hour timeout
            )

            if result.returncode == 0:
                # Success - rename tmp to final
                if err_file.exists():
                    err_file.unlink()
                tmp_file.rename(output_file)
                
                # NEW: Copy ALL metadata from source to output using ExifTool
                # This ensures GPS, Lens Info, MakerNotes etc. are preserved in MP4
                if self.copy_metadata:
                    try:
                        # Map all source tags to XMP and QuickTime groups for MP4 compatibility
                        subprocess.run([
                            'exiftool', 
                            '-tagsFromFile', str(input_file), 
                            '-XMP:all<all', '-QuickTime:all<all',
                            '-all:all', '-unsafe', 
                            '-overwrite_original', 
                            str(output_file)
                        ], capture_output=True, check=True)
                        self.logger.info(f"Metadata copied successfully for {filename}")
                    except Exception as e:
                        self.logger.warning(f"Failed to copy deep metadata for {filename}: {e}")

                self.stats.stop_processing(filename)

                # Calculate stats
                duration = (datetime.now() - start_time).total_seconds()
                output_size = output_file.stat().st_size
                compression_ratio = (1 - output_size / input_size) * 100

                # Log with resolution and FPS (classic format)
                resolution_str = f"{metadata.get('width', '?')}x{metadata.get('height', '?')}" if metadata else "?"
                fps_str = f"{metadata.get('fps', '?')}fps" if metadata else "?"
                self.logger.info(
                    f"Success: {filename} {resolution_str} {fps_str}: {self.format_size(input_size)} → "
                    f"{self.format_size(output_size)} ({compression_ratio:.1f}%) in {duration:.0f}s"
                )

                return {
                    'status': 'success',
                    'input': input_file,
                    'output': output_file,
                    'input_size': input_size,
                    'output_size': output_size,
                    'compression_ratio': compression_ratio,
                    'duration': duration,
                    'metadata': metadata
                }

            # Compression failed
            if tmp_file.exists():
                tmp_file.unlink()

            error_msg = result.stderr if result.stderr else "Unknown error"
            err_file.write_text(error_msg)
            self.stats.stop_processing(filename)
            
            if "Hardware is lacking required capabilities" in error_msg:
                self.logger.warning(f"HW_CAP: {filename}: Hardware lacking capabilities")
                return {
                    'status': 'hw_cap',
                    'input': input_file,
                    'error': error_msg
                }

            self.logger.error(f"Failed: {filename}: {error_msg}")
            return {
                'status': 'error',
                'input': input_file,
                'error': error_msg
            }

        except subprocess.TimeoutExpired:
            self.stats.stop_processing(filename)
            error_msg = "Compression timeout (6 hours)"
            err_file = self.get_output_path(input_file).parent / f"{input_file.stem}.err"
            err_file.write_text(error_msg)
            self.logger.error(f"Timeout: {filename}")
            return {
                'status': 'error',
                'input': input_file,
                'error': error_msg
            }

        except Exception as e:
            self.stats.stop_processing(filename)
            error_msg = str(e)
            try:
                err_file = self.get_output_path(input_file).parent / f"{input_file.stem}.err"
                err_file.parent.mkdir(parents=True, exist_ok=True)
                err_file.write_text(error_msg)
            except:
                pass
            self.logger.error(f"Exception: {filename}: {error_msg}")
            return {
                'status': 'error',
                'input': input_file,
                'error': error_msg
            }

        finally:
            # Always release thread slot
            self.thread_controller.release()

            # Remove from currently processing files
            with self.processing_files_lock:
                self.currently_processing_files.discard(input_file)

            # Drop queue metadata cache entry after processing to keep cache bounded
            with self.queue_metadata_lock:
                self.queue_metadata_cache.pop(input_file, None)

            # Cleanup temporary color-fixed file if it was created
            if temp_fixed_file and temp_fixed_file.exists():
                try:
                    temp_fixed_file.unlink()
                except Exception as e:
                    self.logger.warning(f"Failed to cleanup temp file {temp_fixed_file}: {e}")

    def sanitize_filename_for_display(self, filename: str) -> str:
        """
        Sanitize filename for display by replacing non-ASCII characters with '?'.
        Only affects display, file names are never modified.
        """
        if not self.strip_unicode_display:
            return filename

        # Replace non-ASCII characters (emoji, special Unicode) with '?'
        return ''.join(c if ord(c) < 128 else '?' for c in filename)

    def format_size(self, size: int) -> str:
        """Format size in bytes to human readable"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f}{unit}"
            size /= 1024.0
        return f"{size:.1f}TB"

    def format_time(self, seconds: float) -> str:
        """Format seconds to human readable time with leading zeros"""
        if seconds < 60:
            return f"{int(seconds):02d}s"
        elif seconds < 3600:
            return f"{int(seconds // 60):02d}m {int(seconds % 60):02d}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours:02d}h {minutes:02d}m"

    def format_resolution(self, metadata: Dict) -> str:
        """Format resolution as megapixels (e.g., '8M')"""
        if metadata and 'megapixels' in metadata:
            return f"{metadata['megapixels']}M"
        return ""

    def format_fps(self, metadata: Dict) -> str:
        """Format FPS as integer (e.g., '60fps')"""
        if metadata and 'fps' in metadata:
            return f"{metadata['fps']}fps"
        return ""

    def create_display(self, total_files: int, completed_count: int, queue: List[Path], completed_files_set: Set[Path] = None, submitted_files_set: Set[Path] = None, pending_files_list: List[Path] = None, in_flight_files: List[Path] = None, spinner_frame: int = 0, already_compressed_count: int = 0, ignored_small_count: int = 0, ignored_err_count: int = 0, ignored_hw_cap_count: int = 0) -> Group:
        """Create rich display with all panels"""
        stats = self.stats.get_stats()

        # Menu Panel
        menu_panel = Panel(
            "[bright_red]<[/bright_red] decrease threads | [bright_red]>[/bright_red] increase threads | [bright_red]S[/bright_red] stop | [bright_red]R[/bright_red] refresh",
            title="MENU",
            border_style="white"
        )

        # Compression Status Panel (dynamic + counters)
        status_lines = [
            f"Files to compress: {total_files} | Already compressed: {already_compressed_count}",
            f"Ignored: size: {ignored_small_count} | err: {ignored_err_count} | hw_cap: {ignored_hw_cap_count} | av1: {stats['av1_skip']} | cam: {stats['camera_skip']}"
        ]
        current_threads = self.thread_controller.get_current()
        is_shutdown = self.thread_controller.is_shutdown_requested()

        if is_shutdown:
            status_lines.append(
                f"Total: {total_files} files | SHUTDOWN - finishing tasks | "
                f"{self.format_size(stats['total_input_size'])} → {self.format_size(stats['total_output_size'])} "
                f"({stats['avg_compression']:.1f}% avg) | "
                f"{self.format_time(stats['elapsed'])} elapsed"
            )
        else:
            status_lines.append(
                f"Total: {total_files} files | Threads: {current_threads} | "
                f"{self.format_size(stats['total_input_size'])} → {self.format_size(stats['total_output_size'])} "
                f"({stats['avg_compression']:.1f}% avg) | "
                f"{self.format_time(stats['elapsed'])} elapsed"
            )

        # Calculate ETA
        if stats['throughput'] > 0 and len(queue) > completed_count:
            remaining_files = queue[completed_count:]
            remaining_size = sum(f.stat().st_size for f in remaining_files if f.exists())
            eta_seconds = remaining_size / stats['throughput']
            status_lines.append(f"ETA: {self.format_time(eta_seconds)} (based on {self.format_size(stats['throughput'])}/s throughput)")
        else:
            status_lines.append("ETA: calculating...")

        status_panel = Panel(
            "\n".join(status_lines),
            title="COMPRESSION STATUS",
            border_style="cyan"
        )

        # Progress Bar with thread info
        active_threads = self.thread_controller.get_active()
        last_action = self.get_last_action()

        progress_text = (
            f"Progress: {completed_count}/{total_files} ({completed_count*100//total_files if total_files > 0 else 0}%) | "
            f"Active threads: {active_threads}"
        )
        if last_action:
            progress_text += f" | {last_action}"

        progress_panel = Panel(progress_text, border_style="green")

        # Currently Processing Panel
        processing_table = Table(show_header=False, box=None, padding=(0, 1))
        processing_table.add_column("Status", width=1, style="yellow")
        processing_table.add_column("File", style="yellow", width=40, no_wrap=True, overflow="ellipsis")
        processing_table.add_column("Res", width=3, justify="right", style="cyan")
        processing_table.add_column("FPS", width=6, justify="right", style="cyan")
        processing_table.add_column("Size", justify="right")
        processing_table.add_column("Time", justify="right")

        # Spinner animation for currently processing files
        # Different spinners based on rotation:
        # - With auto-rotation (rotation_angle > 0): ◐◓◑◒ (rotating spinner)
        # - Without rotation (rotation_angle == 0): ●○◉◎ (simple circles)
        spinner_rotating = "◐◓◑◒"
        spinner_simple = "●○◉◎"

        for idx, (filename, info) in enumerate(list(stats['processing'].items())):
            elapsed = (datetime.now() - info['start_time']).total_seconds()
            rotation_angle = info.get('rotation_angle', 0)
            metadata = info.get('metadata', {})

            # Choose spinner based on rotation
            spinner_frames = spinner_rotating if rotation_angle > 0 else spinner_simple

            # Animate: each file gets different phase of spinner based on frame counter
            spinner_char = spinner_frames[(spinner_frame + idx) % len(spinner_frames)]
            processing_table.add_row(
                spinner_char,
                self.sanitize_filename_for_display(filename),
                self.format_resolution(metadata),
                self.format_fps(metadata),
                self.format_size(info['size']),
                self.format_time(elapsed)
            )

        if stats['processing']:
            processing_panel = Panel(
                processing_table,
                title="CURRENTLY PROCESSING",
                border_style="yellow"
            )
        else:
            processing_panel = Panel("No files processing", title="CURRENTLY PROCESSING", border_style="yellow")

        # Last Completed Panel
        completed_table = Table(show_header=False, box=None, padding=(0, 1))
        completed_table.add_column("Status", width=1, style="green")
        completed_table.add_column("File", style="green", width=40, no_wrap=True, overflow="ellipsis")
        completed_table.add_column("Res", width=3, justify="right", style="cyan")
        completed_table.add_column("FPS", width=6, justify="right", style="cyan")
        completed_table.add_column("Input", justify="right", style="cyan")
        completed_table.add_column("→", justify="center", style="dim")
        completed_table.add_column("Output", justify="right", style="cyan")
        completed_table.add_column("Saved", justify="right", style="green")
        completed_table.add_column("Time", justify="right", style="yellow")
        completed_table.add_column("", width=2, justify="center", style="magenta")

        # Show last 5 completed in reverse order (newest first)
        completed_list = list(reversed(list(stats['completed'])))
        for item in completed_list[:5]:
            metadata = item.get('metadata', {})
            compression_ratio = item.get('compression_ratio', 100)
            
            warn_icon = "📦" if compression_ratio < 50 else ""
            completed_table.add_row(
                "✓",
                self.sanitize_filename_for_display(item['input'].name),
                self.format_resolution(metadata),
                self.format_fps(metadata),
                self.format_size(item['input_size']),
                "→",
                self.format_size(item['output_size']),
                f"{compression_ratio:.1f}%",
                self.format_time(item['duration']),
                warn_icon
            )

        if stats['completed']:
            completed_panel = Panel(
                completed_table,
                title="LAST COMPLETED",
                border_style="green"
            )
        else:
            completed_panel = Panel("No files completed yet", title="LAST COMPLETED", border_style="green")

        # Next in Queue Panel
        next_table = Table(show_header=False, box=None, padding=(0, 1))
        next_table.add_column("", width=1, style="dim")
        next_table.add_column("File", width=40, no_wrap=True, overflow="ellipsis")
        next_table.add_column("Res", width=3, justify="right", style="cyan")
        next_table.add_column("FPS", width=6, justify="right", style="cyan")
        next_table.add_column("Cam", width=16, style="magenta", no_wrap=True)
        next_table.add_column("Size", justify="right")
        next_table.add_column("Codec", width=5, justify="center", no_wrap=True, overflow="ellipsis")
        next_table.add_column("", width=2, justify="center", style="magenta")

        # If shutdown requested, show empty queue
        if is_shutdown:
            next_files = []
        else:
            # Submit-on-demand: show files waiting to be processed
            # Priority 1: Files in in_flight but not yet processing (submitted, waiting for slot)
            # Priority 2: Files in pending_files (not yet submitted)
            if in_flight_files is not None and pending_files_list is not None:
                with self.processing_files_lock:
                    processing = set(self.currently_processing_files)

                # Files submitted but waiting for thread slot (sorted for consistent display)
                waiting_in_flight = sorted([f for f in in_flight_files if f not in processing])

                # Combine: waiting in_flight + pending, take first 5
                next_files = (waiting_in_flight + pending_files_list)[:5]
            elif pending_files_list is not None:
                next_files = pending_files_list[:5]
            else:
                # Fallback to old behavior (shouldn't happen with submit-on-demand)
                next_files = queue[completed_count:completed_count + 5]

            for file in next_files:
                if file.exists():
                    metadata = self.get_queue_metadata(file)
                    codec_raw = metadata.get('codec')
                    codec = codec_raw.lower() if codec_raw else ""
                    warn_icon = "📦" if codec == 'av1' else ""
                    
                    cam_info = metadata.get('camera', "")

                    next_table.add_row(
                        "»",
                        self.sanitize_filename_for_display(file.name),
                        self.format_resolution(metadata),
                        self.format_fps(metadata),
                        cam_info,
                        self.format_size(file.stat().st_size),
                        codec,
                        warn_icon
                    )

        if next_files:
            queue_panel = Panel(
                next_table,
                title="NEXT IN QUEUE",
                border_style="blue"
            )
        else:
            queue_panel = Panel("Queue empty", title="NEXT IN QUEUE", border_style="blue")

        # Summary at bottom
        summary = f"✓ {stats['success']} success  ✗ {stats['error']} errors  ⚠ {stats['hw_cap']} hw_cap  ⊘ {stats['skipped']} skipped"
        summary_panel = Panel(summary, border_style="white")

        return Group(
            menu_panel,
            status_panel,
            progress_panel,
            processing_panel,
            completed_panel,
            queue_panel,
            summary_panel
        )

    def show_config(self):
        """Display current configuration in a pretty format"""
        table = Table(title="VBC CURRENT CONFIGURATION", border_style="cyan")
        table.add_column("Parameter", style="yellow")
        table.add_column("Value", style="green")

        table.add_row("Input Directory", str(self.input_dir))
        table.add_row("Output Directory", str(self.output_dir))
        table.add_row("Threads", str(self.thread_controller.get_current()))
        table.add_row("AV1 Quality (Default CQ)", str(self.cq))
        table.add_row("GPU Acceleration", str(not self.use_cpu))
        table.add_row("Copy Metadata", str(self.copy_metadata))
        table.add_row("Use ExifTool Analysis", str(self.use_exif))
        table.add_row("Skip AV1 Codec", str(self.skip_av1))
        table.add_row("Min File Size", self.format_size(self.min_size_bytes))
        
        # Camera Filters
        cam_filters = ", ".join(self.filter_cameras) if self.filter_cameras else "ALL CAMERAS"
        table.add_row("Camera Filters", cam_filters)

        # Dynamic CQ
        if self.dynamic_cq:
            cq_rules = "\n".join([f"  {k} → CQ{v}" for k, v in self.dynamic_cq.items()])
            table.add_row("Dynamic CQ Rules", cq_rules)

        # Autorotate
        if self.autorotate_patterns:
            rotate_rules = "\n".join([f"  {k} → {v}°" for k, v in self.autorotate_patterns.items()])
            table.add_row("Autorotate Rules", rotate_rules)

        self.console.print(table)

    def generate_report(self):
        """Generate a detailed CSV report of all files (Dry Run)"""
        self.console.print("[cyan]Starting Dry Run - generating report...[/cyan]")
        
        input_files, ignored_small = self.find_input_files()
        completed_files = self.find_completed_files()
        err_marked, hw_cap_marked = self.find_error_marked_inputs(input_files)
        
        report_file = self.output_dir / f"compression_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.output_dir.mkdir(exist_ok=True)

        rows = []
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=self.console
        ) as progress:
            task = progress.add_task("Analyzing files...", total=len(input_files))
            
            for f in input_files:
                status = "Pending"
                if f in completed_files: status = "Already Compressed"
                elif f in err_marked: status = "Previous Error"
                elif f in hw_cap_marked: status = "Hardware Cap Error"
                
                metadata = self.get_queue_metadata(f)
                cam_model = metadata.get('camera') or metadata.get('camera_raw', "")
                active_cq = metadata.get('custom_cq', self.cq)
                codec = metadata.get('codec', "unknown")
                
                # Filter check
                cam_match = "Yes"
                if self.filter_cameras:
                    matched = False
                    for p in self.filter_cameras:
                        if p.lower() in cam_model.lower(): matched = True; break
                    if not matched: cam_match = "No"; status = "Filtered Out"

                if status == "Pending" and self.skip_av1 and codec == 'av1':
                    status = "Skip (AV1)"

                rows.append({
                    'File': f.name,
                    'Path': str(f.relative_to(self.input_dir)),
                    'Size': self.format_size(f.stat().st_size),
                    'Codec': codec,
                    'Resolution': f"{metadata.get('width', '?')}x{metadata.get('height', '?')}",
                    'Camera': cam_model,
                    'Camera Match': cam_match,
                    'Target CQ': active_cq,
                    'Status': status
                })
                progress.update(task, advance=1)

        with open(report_file, 'w', newline='') as csvfile:
            fieldnames = ['File', 'Status', 'Target CQ', 'Camera', 'Camera Match', 'Codec', 'Resolution', 'Size', 'Path']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

        self.console.print(f"\n[green]Report generated successfully![/green]")
        self.console.print(f"File: [bold]{report_file}[/bold]")
        
        # Print summary table
        summary = Table(show_header=False, border_style="dim")
        status_counts = {}
        for r in rows: status_counts[r['Status']] = status_counts.get(r['Status'], 0) + 1
        
        for status, count in status_counts.items():
            summary.add_row(status, str(count))
        self.console.print(Panel(summary, title="DRY RUN SUMMARY"))

    def run(self):
        """Main execution method"""
        # Save start time
        start_time = datetime.now()

        # Step 1: Cleanup old temp files
        self.cleanup_temp_files()

        # Step 2: Find all input files
        input_files, ignored_small = self.find_input_files()
        self.ignored_small_count = ignored_small
        
        err_marked, hw_cap_marked = (set(), set()) if self.clean_errors else self.find_error_marked_inputs(input_files)
        self.ignored_err_count = len(err_marked)
        self.ignored_hw_cap_count = len(hw_cap_marked)
        
        if not input_files:
            ext_list = ', '.join([f'.{ext}' for ext in self.extensions])
            if ignored_small > 0:
                self.console.print(f"[yellow]No video files >= {self.format_size(self.min_size_bytes)} found! (ignored {ignored_small} below threshold, looking for: {ext_list})[/yellow]")
            else:
                self.console.print(f"[yellow]No video files found! (looking for: {ext_list})[/yellow]")
            return

        # Step 3: Find already completed files
        completed_files = self.find_completed_files()
        self.already_compressed_count = len(completed_files)

        # Step 4: Filter candidates based on file existence only (błyskawiczne)
        files_to_process = [f for f in input_files if f not in completed_files and f not in err_marked and f not in hw_cap_marked]
        self.files_to_compress_count = len(files_to_process)

        if not files_to_process:
            parts = []
            if ignored_small > 0:
                parts.append(f"ignored {ignored_small} below {self.format_size(self.min_size_bytes)}")
            if err_marked:
                parts.append(f"skipped {len(err_marked)} with existing .err (use --clean-errors to retry)")
            if hw_cap_marked:
                parts.append(f"skipped {len(hw_cap_marked)} due to GPU hardware limits")
            suffix = f" ({'; '.join(parts)})" if parts else ""
            self.console.print(f"[green]All files already compressed![/green]{suffix}")
            return

        # Print initial info to console with file counts
        encoder_name = "SVT-AV1 (CPU)" if self.use_cpu else "NVENC AV1 (GPU)"
        preset = "8 (Fast)" if self.use_cpu else "p7 (Slow/HQ)"
        metadata_method = "Deep (ExifTool + XMP)" if (self.use_exif and self.copy_metadata) else ("Basic (FFmpeg)" if self.copy_metadata else "None")
        autorotate_count = len(self.autorotate_patterns)

        ext_list = ', '.join([f'.{ext}' for ext in self.extensions])
        dynamic_cq_info = ", ".join([f"{k}:{v}" for k, v in self.dynamic_cq.items()]) if self.dynamic_cq else "None"
        camera_filter_info = ", ".join(self.filter_cameras) if self.filter_cameras else "None"
        
        start_info = f"""[cyan]Video Batch Compression - {encoder_name}[/cyan]
Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}
Input: {self.input_dir}
Output: {self.output_dir}
Threads: {self.thread_controller.get_current()} (Prefetch: {self.prefetch_factor}x)
Encoder: {encoder_name} | Preset: {preset}
Audio: Copy (stream copy)
Quality: CQ{self.cq} (Global Default)
Dynamic CQ: {dynamic_cq_info}
Camera Filter: {camera_filter_info}
Metadata: {metadata_method} (Analysis: {self.use_exif})
Autorotate: {autorotate_count} rules loaded
Manual Rotation: {'180°' if self.rotate_180 else 'None'}
Extensions: {ext_list} → .mp4
Min size: {self.format_size(self.min_size_bytes)} | Skip AV1: {self.skip_av1}
Clean errors: {self.clean_errors} | Strip Unicode: {self.strip_unicode_display}"""

        self.console.print(Panel(start_info, title="CONFIGURATION", border_style="cyan"))
        self.console.print()  # Empty line before MENU

        # Step 5: Compress files in parallel with live display
        completed_count = 0
        total_files = len(files_to_process)
        stop_refresh = threading.Event()
        futures_lock = threading.Lock()
        completed_files_set: Set[Path] = set()
        completed_files_lock = threading.Lock()

        # Submit-on-demand architecture
        pending_files: Deque[Path] = deque(sorted(files_to_process))  # Unsubmitted files
        in_flight: Dict = {}  # Future -> Path, submitted but not completed
        queue_lock = threading.Lock()  # Protects pending_files and in_flight

        def safe_live_update(live_obj, completed_files_snapshot, pending_files_snapshot, in_flight_snapshot, spinner_frame):
            """Render display and update Live with UI lock to avoid concurrent updates."""
            display = self.create_display(
                total_files,
                completed_count,
                files_to_process,
                completed_files_snapshot,
                None,
                pending_files_snapshot,
                in_flight_snapshot,
                spinner_frame,
                self.already_compressed_count,
                self.ignored_small_count,
                self.ignored_err_count,
                self.ignored_hw_cap_count
            )
            with self.ui_lock:
                live_obj.update(display)

        def top_up_queue(executor):
            """Submit tasks from pending_files to executor up to max_inflight limit"""
            max_inflight = self.prefetch_factor * self.thread_controller.get_current()

            with queue_lock:
                while (
                    len(in_flight) < max_inflight
                    and pending_files
                    and not self.thread_controller.is_shutdown_requested()
                ):
                    file = pending_files.popleft()
                    future = executor.submit(self.compress_file, file)
                    in_flight[future] = file

        def auto_refresh():
            """Auto-refresh display every 1 second"""
            while not stop_refresh.is_set():
                try:
                    # Increment spinner animation frame
                    with self.spinner_lock:
                        self.spinner_frame = (self.spinner_frame + 1) % 4

                    with completed_files_lock:
                        completed_set_copy = set(completed_files_set)
                    with queue_lock:
                        pending_files_copy = list(pending_files)
                        in_flight_files_copy = list(in_flight.values())
                    with self.spinner_lock:
                        frame = self.spinner_frame
                    safe_live_update(live, completed_set_copy, pending_files_copy, in_flight_files_copy, frame)
                except:
                    pass
                stop_refresh.wait(1.0)

        def refresh_handler(executor, files_to_process_list):
            """Handle file list refresh in separate thread"""
            nonlocal total_files

            while not stop_refresh.is_set():
                time.sleep(1.0)

                # Check if refresh was requested
                with self.refresh_lock:
                    if not self.refresh_requested:
                        continue
                    self.refresh_requested = False

                # Don't add files if shutdown requested
                if self.thread_controller.is_shutdown_requested():
                    continue

                try:
                    # Find new files
                    new_input_files, new_ignored_small = self.find_input_files()
                    self.ignored_small_count = new_ignored_small
                    
                    new_err_marked, new_hw_cap_marked = (set(), set()) if self.clean_errors else self.find_error_marked_inputs(new_input_files)
                    self.ignored_err_count = len(new_err_marked)
                    self.ignored_hw_cap_count = len(new_hw_cap_marked)
                    
                    new_completed_files = self.find_completed_files()
                    self.already_compressed_count = len(new_completed_files)

                    # Get currently processing files (thread-safe)
                    with self.processing_files_lock:
                        processing = set(self.currently_processing_files)

                    # Get completed files (thread-safe)
                    with completed_files_lock:
                        completed = set(completed_files_set)

                    # Get known files from all sources
                    with queue_lock:
                        known = (
                            processing
                            | completed
                            | set(pending_files)
                            | set(in_flight.values())
                        )

                        # Find files to ADD: new files not in any known set
                        candidates_add = [
                            f for f in new_input_files
                            if f not in new_completed_files and f not in known and f not in new_err_marked and f not in new_hw_cap_marked
                        ]

                        # Find files to REMOVE: files in pending_files that no longer exist in source
                        new_input_files_set = set(new_input_files)
                        candidates_remove = [
                            f for f in list(pending_files)
                            if f not in new_input_files_set or f in new_err_marked or f in new_hw_cap_marked
                        ]

                        added = 0
                        removed = 0

                        # Add new files
                        if candidates_add:
                            candidates_add.sort()
                            pending_files.extend(candidates_add)
                            files_to_process_list.extend(candidates_add)
                            added = len(candidates_add)
                            self.logger.info(f"Refresh: added {added} new files to queue")

                        # Remove deleted files
                        if candidates_remove:
                            for file in candidates_remove:
                                try:
                                    pending_files.remove(file)
                                    if file in files_to_process_list:
                                        files_to_process_list.remove(file)
                                except ValueError:
                                    pass
                            removed = len(candidates_remove)
                            self.logger.info(f"Refresh: removed {removed} deleted files from queue")

                        # Update total count
                        total_files = len(files_to_process_list)

                        # Set status message
                        if added > 0 and removed > 0:
                            self.set_last_action(f"Refreshed: +{added} new, -{removed} deleted")
                        elif added > 0:
                            self.set_last_action(f"Refreshed: +{added} new files")
                        elif removed > 0:
                            self.set_last_action(f"Refreshed: -{removed} deleted files")
                        else:
                            self.set_last_action("Refreshed: no changes")
                            self.logger.info("Refresh: no changes detected")

                    # Trigger top-up to submit new files if there's capacity
                    top_up_queue(executor)

                    # Update display
                    with completed_files_lock:
                        completed_set_copy = set(completed_files_set)
                    with queue_lock:
                        pending_files_copy = list(pending_files)
                        in_flight_files_copy = list(in_flight.values())
                    with self.spinner_lock:
                        frame = self.spinner_frame
                    safe_live_update(live, completed_set_copy, pending_files_copy, in_flight_files_copy, frame)
                except Exception as e:
                    self.logger.error(f"Refresh error: {e}")

        # Start keyboard listener thread
        keyboard_thread = threading.Thread(target=self.keyboard_listener, daemon=True)
        keyboard_thread.start()

        try:
            with Live(self.create_display(total_files, completed_count, files_to_process, set(), None, list(pending_files), [], 0, self.already_compressed_count, self.ignored_small_count, self.ignored_err_count, self.ignored_hw_cap_count),
                      refresh_per_second=10, console=self.console) as live:

                # Start auto-refresh thread
                refresh_thread = threading.Thread(target=auto_refresh, daemon=True)
                refresh_thread.start()

                # Use max 8 workers pool (GPU NVENC session limit)
                executor = ThreadPoolExecutor(max_workers=8)
                try:
                    # Submit-on-demand: submit initial batch up to max_inflight
                    top_up_queue(executor)

                    # Start refresh handler thread
                    refresh_handler_thread = threading.Thread(
                        target=refresh_handler,
                        args=(executor, files_to_process),
                        daemon=True
                    )
                    refresh_handler_thread.start()

                    # Process results - submit-on-demand: only process in_flight futures
                    while True:
                        is_shutdown = self.thread_controller.is_shutdown_requested()

                        with queue_lock:
                            # Normal operation: end when both queues empty
                            # Shutdown: end when in_flight empty (ignore pending_files)
                            if is_shutdown:
                                if not in_flight:
                                    break
                            else:
                                if not in_flight and not pending_files:
                                    break

                            current_futures = set(in_flight.keys())
                            has_pending = len(pending_files) > 0

                        # If no futures in flight but pending files remain, top-up and continue
                        if not current_futures:
                            if has_pending and not is_shutdown:
                                top_up_queue(executor)
                                continue
                            else:
                                break

                        # Wait for at least one future to complete (with timeout to react to thread changes)
                        done, _ = wait(current_futures, timeout=1.0, return_when=FIRST_COMPLETED)

                        # If timeout (no completions), check if we need to top-up queue
                        # (e.g., user increased threads via '>' key)
                        if not done:
                            top_up_queue(executor)
                            continue

                        for future in done:
                            # Get the file path for this future
                            with queue_lock:
                                completed_file = in_flight.get(future)

                            try:
                                result = future.result()

                                if result['status'] == 'success':
                                    self.stats.add_success(result)
                                elif result['status'] == 'skipped':
                                    self.stats.add_skipped()
                                elif result['status'] == 'hw_cap':
                                    self.stats.add_hw_cap()
                                elif result['status'] == 'camera_skip':
                                    self.stats.add_camera_skip()
                                elif result['status'] == 'av1_skip':
                                    self.stats.add_av1_skip()
                                else:
                                    self.stats.add_error()

                                completed_count += 1

                                # Add to completed files set
                                if completed_file:
                                    with completed_files_lock:
                                        completed_files_set.add(completed_file)

                            except Exception as e:
                                self.logger.error(f"Unexpected error in main loop: {e}")
                                self.stats.add_error()
                                completed_count += 1

                                # Add to completed files set even on error
                                if completed_file:
                                    with completed_files_lock:
                                        completed_files_set.add(completed_file)

                            # Remove processed future from in_flight
                            with queue_lock:
                                if future in in_flight:
                                    del in_flight[future]

                            # Submit-on-demand: replenish queue after completion
                            top_up_queue(executor)

                        with completed_files_lock:
                            completed_set_copy = set(completed_files_set)
                        with queue_lock:
                            pending_files_copy = list(pending_files)
                            in_flight_files_copy = list(in_flight.values())
                        with self.spinner_lock:
                            frame = self.spinner_frame
                        safe_live_update(live, completed_set_copy, pending_files_copy, in_flight_files_copy, frame)

                except KeyboardInterrupt:
                    self.console.print("\n[yellow]Ctrl+C detected - stopping new tasks...[/yellow]")
                    self.logger.info("Keyboard interrupt - graceful shutdown")

                    # Stop accepting new tasks
                    self.thread_controller.graceful_shutdown()

                    # Cancel all in-flight futures
                    with queue_lock:
                        for future in list(in_flight.keys()):
                            if not future.done():
                                future.cancel()

                    # Wait for currently running tasks (max 30 seconds)
                    self.console.print("[yellow]Waiting for active tasks to finish (max 30s)...[/yellow]")
                    executor.shutdown(wait=True, cancel_futures=True)

                    raise
                finally:
                    executor.shutdown(wait=False)

        finally:
            # Stop threads
            stop_refresh.set()
            self.stop_keyboard_thread.set()
            
            # Terminate ExifTool process
            if self.et:
                try:
                    # ExifToolHelper might have stop() or terminate() depending on version
                    if hasattr(self.et, 'terminate'):
                        self.et.terminate()
                    elif hasattr(self.et, 'stop'):
                        self.et.stop()
                except:
                    pass

        # Final summary
        end_time = datetime.now()
        stats = self.stats.get_stats()

        summary_lines = [
            f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"End: {end_time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"Total files processed: {total_files}",
            f"[green]Successful: {stats['success']}[/green]",
            f"[yellow]Skipped: {stats['skipped']}[/yellow]",
            f"[yellow]Hardware Cap: {stats['hw_cap']}[/yellow]",
            f"[red]Failed: {stats['error']}[/red]",
        ]

        if stats['success'] > 0:
            throughput_mb = stats['throughput'] / (1024 * 1024)  # Convert bytes/s to MB/s
            summary_lines.extend([
                "",
                f"Total input size: {self.format_size(stats['total_input_size'])}",
                f"Total output size: {self.format_size(stats['total_output_size'])}",
                f"Overall compression: {stats['avg_compression']:.1f}%",
                f"Total time: {self.format_time(stats['elapsed'])}",
                f"Average throughput: {throughput_mb:.1f} MB/s"
            ])

        # Check for collisions in log file
        log_file = self.output_dir / "compression.log"
        if log_file.exists():
            try:
                collision_lines = []
                with open(log_file, 'r') as f:
                    for line in f:
                        if 'COLLISION:' in line:
                            collision_lines.append(line.strip())

                if collision_lines:
                    summary_lines.extend([
                        "",
                        f"[red]⚠ Found {len(collision_lines)} filename collision(s):[/red]",
                        "[dim]Files skipped because output .mp4 already exists:[/dim]"
                    ])
                    for line in collision_lines:
                        # Extract input/output paths from log line
                        # Format: "COLLISION: Output exists, skipping input=/path/to/file.flv output=/path/to/file.mp4"
                        if 'input=' in line and 'output=' in line:
                            try:
                                input_part = line.split('input=')[1].split(' output=')[0]
                                output_part = line.split('output=')[1]
                                summary_lines.append(f"  [yellow]→ {input_part}[/yellow]")
                                summary_lines.append(f"    [dim]conflicts with: {output_part}[/dim]")
                            except:
                                summary_lines.append(f"  [dim]{line}[/dim]")
            except Exception as e:
                self.logger.error(f"Failed to read collision info from log: {e}")

        self.console.print(Panel("\n".join(summary_lines), title="COMPRESSION SUMMARY", border_style="cyan"))


def main():
    # Parse --config early to allow overriding defaults from custom config file
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        '--config',
        type=Path,
        help='Path to configuration file (default: conf/vbc.yaml next to this script)'
    )
    pre_args, _ = pre_parser.parse_known_args()

    # Load configuration from conf/vbc.yaml or user-provided path
    config = load_config(pre_args.config)

    parser = argparse.ArgumentParser(
        description='VBC - Video Batch Compression using AV1',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[pre_parser],
        epilog="""
Example:
  python vbc.py /path/to/videos --threads 4 --cq 45
  python vbc.py /path/to/videos --rotate-180 --no-metadata

Configuration:
  - Default values are loaded from conf/vbc.yaml
  - You can override config path with --config /path/to/vbc.yaml
  - CLI arguments override config file settings
  - Auto-rotation patterns and dynamic CQ defined in config file (YAML)

Output:
  - Compressed files: /path/to/videos_out/
  - Log file: /path/to/videos_out/compression.log
  - Error files: *.mp4.err (if compression fails)
        """
    )

    parser.add_argument(
        'input_dir',
        type=Path,
        help='Input directory containing video files (extensions configured in vbc.yaml)'
    )

    parser.add_argument(
        '--threads',
        type=int,
        default=config['threads'],
        help=f'Number of parallel compression threads (default: {config["threads"]} from config)'
    )

    parser.add_argument(
        '--cq',
        type=int,
        default=config['cq'],
        help=f'AV1 constant quality value (default: {config["cq"]} from config, lower=better quality)'
    )

    parser.add_argument(
        '--rotate-180',
        action='store_true',
        help='Rotate all videos 180 degrees (overrides auto-rotation from config)'
    )

    parser.add_argument(
        '--cpu',
        action='store_true',
        help=f'Use CPU encoder (SVT-AV1) instead of GPU (NVENC). Default: {"CPU" if not config["gpu"] else "GPU"} from config'
    )

    parser.add_argument(
        '--prefetch-factor',
        type=int,
        default=config['prefetch_factor'],
        choices=[1, 2, 3, 4, 5],
        help=f'Submit-on-demand prefetch multiplier (default: {config["prefetch_factor"]} from config)'
    )

    parser.add_argument(
        '--no-metadata',
        action='store_true',
        help=f'Do not copy EXIF metadata (GPS, camera info). Default: {"copy" if config["copy_metadata"] else "do not copy"} from config'
    )

    parser.add_argument(
        '--min-size',
        type=int,
        default=config['min_size_bytes'],
        help='Minimum input file size in bytes to process (default: 1048576 = 1MiB; set 0 to include empty files)'
    )

    parser.add_argument(
        '--clean-errors',
        action='store_true',
        default=config['clean_errors'],
        help='Remove existing .err files in output directory and retry those inputs (default: keep .err and skip those files)'
    )

    parser.add_argument(
        '--skip-av1',
        action='store_true',
        default=config['skip_av1'],
        help=f'Skip files that already use AV1 codec (default: {"skip" if config["skip_av1"] else "compress"} from config)'
    )

    parser.add_argument(
        '--strip-unicode-display',
        action='store_true',
        dest='strip_unicode_display',
        default=None,
        help='Strip non-ASCII Unicode characters from filenames in UI display (replaces emoji/special chars with \'?\')'
    )

    parser.add_argument(
        '--no-strip-unicode-display',
        action='store_false',
        dest='strip_unicode_display',
        help='Show original filenames with Unicode characters in UI (may break table alignment)'
    )

    parser.add_argument(
        '--use-exif',
        action='store_true',
        dest='use_exif',
        default=None,
        help=f'Use ExifTool for deep metadata analysis and dynamic CQ. Default: {config["use_exif"]} from config'
    )

    parser.add_argument(
        '--no-exif',
        action='store_false',
        dest='use_exif',
        help='Disable deep metadata analysis'
    )

    parser.add_argument(
        '--camera',
        type=str,
        help='Filter by camera model (comma-separated). Example: "Sony, DJI OsmoPocket3"'
    )

    parser.add_argument(
        '--show-config',
        action='store_true',
        help='Show current configuration and exit'
    )

    parser.add_argument(
        '--report',
        action='store_true',
        help='Scan files and generate a CSV report (Dry Run)'
    )

    args = parser.parse_args()

    # Validate input directory
    if not args.input_dir.exists():
        print(f"Error: Input directory does not exist: {args.input_dir}")
        sys.exit(1)

    if not args.input_dir.is_dir():
        print(f"Error: Input path is not a directory: {args.input_dir}")
        sys.exit(1)

    if args.min_size < 0:
        print("Error: --min-size cannot be negative")
        sys.exit(1)

    # Verify required binaries are available before starting
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            print(f"Error: {binary} not found in PATH. Please install ffmpeg with {binary} available.")
            sys.exit(1)

    # Determine encoder: --cpu flag overrides config, otherwise use config['gpu']
    use_cpu = args.cpu if args.cpu else (not config['gpu'])

    # Determine metadata copying: --no-metadata flag overrides config
    copy_metadata = not args.no_metadata if args.no_metadata else config['copy_metadata']

    # Determine Unicode display stripping: CLI flag overrides config if provided
    strip_unicode_display = args.strip_unicode_display if args.strip_unicode_display is not None else config['strip_unicode_display']

    # Determine camera filtering
    filter_cameras = config['filter_cameras']
    if args.camera:
        filter_cameras = [c.strip() for c in args.camera.split(',') if c.strip()]

    # Determine ExifTool usage
    use_exif = args.use_exif if args.use_exif is not None else config['use_exif']
    if filter_cameras and not use_exif:
        print("Warning: Camera filtering requires EXIF analysis. Enabling --use-exif automatically.")
        use_exif = True

    # Run compression
    compressor = VideoCompressor(
        input_dir=args.input_dir,
        threads=args.threads,
        cq=args.cq,
        rotate_180=args.rotate_180,
        use_cpu=use_cpu,
        prefetch_factor=args.prefetch_factor,
        copy_metadata=copy_metadata,
        extensions=config['extensions'],
        autorotate_patterns=config['autorotate_patterns'],
        min_size_bytes=args.min_size,
        clean_errors=args.clean_errors,
        skip_av1=args.skip_av1,
        strip_unicode_display=strip_unicode_display,
        use_exif=use_exif,
        dynamic_cq=config['dynamic_cq'],
        filter_cameras=filter_cameras
    )

    if args.show_config:
        compressor.show_config()
        sys.exit(0)

    if args.report:
        compressor.generate_report()
        sys.exit(0)

    try:
        compressor.run()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Partial progress saved.")
        print("Re-run the script to continue from where it left off.")
        sys.exit(0)


if __name__ == '__main__':
    main()
