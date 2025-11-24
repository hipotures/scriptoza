#!/usr/bin/env python3
"""
Batch video compression script using NVENC AV1 with rich UI
Compresses all .mp4 files in input directory to AV1 with specified quality
"""

import argparse
import configparser
import logging
import re
import select
import subprocess
import sys
import threading
import time
import termios
import tty
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Set, Dict, Optional, Deque

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


def load_config() -> Dict:
    """
    Load configuration from conf/vbc.conf
    Returns dict with default values if config file doesn't exist or can't be read
    """
    defaults = {
        'threads': 4,
        'cq': 45,
        'prefetch_factor': 1,
        'gpu': True,
        'copy_metadata': True,
        'autorotate_patterns': {}
    }

    config_file = Path(__file__).parent.parent / 'conf' / 'vbc.conf'

    if not config_file.exists():
        return defaults

    try:
        config = configparser.ConfigParser()
        config.read(config_file)

        # Load [general] section
        if config.has_section('general'):
            if config.has_option('general', 'threads'):
                defaults['threads'] = config.getint('general', 'threads')
            if config.has_option('general', 'cq'):
                defaults['cq'] = config.getint('general', 'cq')
            if config.has_option('general', 'prefetch_factor'):
                defaults['prefetch_factor'] = config.getint('general', 'prefetch_factor')
            if config.has_option('general', 'gpu'):
                defaults['gpu'] = config.getboolean('general', 'gpu')
            if config.has_option('general', 'copy_metadata'):
                defaults['copy_metadata'] = config.getboolean('general', 'copy_metadata')

        # Load [autorotate] section
        if config.has_section('autorotate'):
            autorotate = {}
            for pattern, angle_str in config.items('autorotate'):
                try:
                    angle = int(angle_str)
                    if angle in [0, 90, 180, 270]:
                        autorotate[pattern] = angle
                except (ValueError, re.error):
                    pass
            defaults['autorotate_patterns'] = autorotate

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

    def add_skipped(self):
        with self.lock:
            self.skipped_count += 1

    def start_processing(self, filename: str, size: int, rotation_angle: int = 0):
        with self.lock:
            self.processing[filename] = {
                'size': size,
                'start_time': datetime.now(),
                'rotation_angle': rotation_angle
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
                'total_input_size': self.total_input_size,
                'total_output_size': self.total_output_size,
                'avg_compression': avg_compression,
                'elapsed': elapsed,
                'throughput': throughput,
                'completed': list(self.completed),
                'processing': dict(self.processing)
            }


class VideoCompressor:
    def __init__(self, input_dir: Path, threads: int = 8, cq: int = 45, rotate_180: bool = False, use_cpu: bool = False, prefetch_factor: int = 1, copy_metadata: bool = True, autorotate_patterns: Dict[str, int] = None):
        self.input_dir = input_dir.resolve()
        self.output_dir = Path(f"{self.input_dir}_out")
        self.thread_controller = ThreadController(threads)
        self.cq = cq
        self.rotate_180 = rotate_180
        self.use_cpu = use_cpu
        self.prefetch_factor = prefetch_factor
        self.copy_metadata = copy_metadata
        self.autorotate_patterns = autorotate_patterns or {}
        self.max_depth = 3
        self.stats = CompressionStats()
        self.console = Console()
        self.stop_keyboard_thread = threading.Event()
        self.last_action = ""
        self.last_action_time = None
        self.last_action_lock = threading.Lock()

        # Refresh functionality
        self.refresh_requested = False
        self.refresh_lock = threading.Lock()
        self.currently_processing_files: Set[Path] = set()
        self.processing_files_lock = threading.Lock()

        # Spinner animation frame counter
        self.spinner_frame = 0
        self.spinner_lock = threading.Lock()

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

    def find_input_files(self) -> List[Path]:
        """Find all .mp4 files in input directory (max 3 levels deep)"""
        all_files = []
        for mp4_file in self.input_dir.rglob("*.mp4"):
            depth = self.get_depth(mp4_file)
            if depth <= self.max_depth:
                all_files.append(mp4_file)
        return sorted(all_files)

    def get_output_path(self, input_file: Path) -> Path:
        """Get corresponding output path maintaining directory structure"""
        relative = input_file.relative_to(self.input_dir)
        return self.output_dir / relative

    def find_completed_files(self) -> Set[Path]:
        """Find all already compressed files in output directory"""
        completed = set()
        if self.output_dir.exists():
            for mp4_file in self.output_dir.rglob("*.mp4"):
                relative = mp4_file.relative_to(self.output_dir)
                input_path = self.input_dir / relative
                completed.add(input_path)
        return completed

    def cleanup_temp_files(self):
        """Remove all .tmp, .err, and *_colorfix.mp4 files from output directory"""
        if not self.output_dir.exists():
            return

        tmp_count = 0
        err_count = 0
        colorfix_count = 0

        for tmp_file in self.output_dir.rglob("*.tmp"):
            tmp_file.unlink()
            tmp_count += 1

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
                if re.match(pattern, filename):
                    self.logger.info(f"Auto-rotation matched: {filename} → {angle}° (pattern: {pattern})")
                    return angle
            except re.error as e:
                self.logger.warning(f"Invalid regex pattern in config: {pattern} - {e}")
                continue

        return 0

    def check_and_fix_color_space(self, input_file: Path) -> tuple[str, Path, Optional[Path]]:
        """
        Check if video has reserved color space and fix it if needed.

        Returns:
            tuple: (status, file_to_compress, temp_file_path)
                - status: "ok" | "fixed" | "corrupted"
                - file_to_compress: Path to use for compression (original or fixed)
                - temp_file_path: Path to temporary fixed file (None if no fix needed)
        """
        try:
            # Check color space using ffprobe
            result = subprocess.run(
                [
                    'ffprobe',
                    '-v', 'error',
                    '-select_streams', 'v:0',
                    '-show_entries', 'stream=color_space,codec_name',
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
                return ("corrupted", input_file, None)

            # Parse output
            output_lines = result.stdout.strip().split('\n')
            color_space = None
            codec_name = None

            for line in output_lines:
                if line.startswith('color_space='):
                    color_space = line.split('=')[1]
                elif line.startswith('codec_name='):
                    codec_name = line.split('=')[1]

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
                    return (input_file, None)

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
                    return ("fixed", temp_fixed, temp_fixed)
                else:
                    # Fix failed - cleanup and use original
                    if temp_fixed.exists():
                        temp_fixed.unlink()
                    self.logger.warning(f"Failed to fix color space for {input_file.name}, proceeding with original")
                    return ("ok", input_file, None)

            # Color space is OK - use original file
            return ("ok", input_file, None)

        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout while checking/fixing color space for {input_file.name}")
            return ("ok", input_file, None)
        except Exception as e:
            self.logger.error(f"Error checking color space for {input_file.name}: {e}")
            return ("ok", input_file, None)

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

        # Check and fix color space if needed (before acquiring thread slot)
        validity_status, file_to_compress, temp_fixed_file = self.check_and_fix_color_space(input_file)

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

        # Determine rotation angle
        # CLI flag --rotate-180 takes priority, otherwise check auto-rotation config
        if self.rotate_180:
            rotation_angle = 180
        else:
            rotation_angle = self.get_auto_rotation(input_file)

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
        self.stats.start_processing(filename, input_size, rotation_angle)

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
                        '-crf', str(self.cq),
                        '-c:a', 'copy',
                    ])

                    # Copy EXIF metadata if enabled
                    if self.copy_metadata:
                        cmd.extend(['-map_metadata', '0'])

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
                    '-cq', str(self.cq),
                    '-b:v', '0',
                    '-c:a', 'copy',
                ])

                # Copy EXIF metadata if enabled
                if self.copy_metadata:
                    cmd.extend(['-map_metadata', '0'])

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
                capture_output=True,
                text=True,
                timeout=21600  # 6 hour timeout
            )

            if result.returncode == 0:
                # Success - rename tmp to final
                if err_file.exists():
                    err_file.unlink()
                tmp_file.rename(output_file)
                self.stats.stop_processing(filename)

                # Calculate stats
                duration = (datetime.now() - start_time).total_seconds()
                output_size = output_file.stat().st_size
                compression_ratio = (1 - output_size / input_size) * 100

                self.logger.info(
                    f"Success: {filename}: {self.format_size(input_size)} → "
                    f"{self.format_size(output_size)} ({compression_ratio:.1f}%) in {duration:.0f}s"
                )

                return {
                    'status': 'success',
                    'input': input_file,
                    'output': output_file,
                    'input_size': input_size,
                    'output_size': output_size,
                    'compression_ratio': compression_ratio,
                    'duration': duration
                }

            # Compression failed
            if tmp_file.exists():
                tmp_file.unlink()

            error_msg = result.stderr if result.stderr else "Unknown error"
            err_file.write_text(error_msg)
            self.logger.error(f"Failed: {filename}: {error_msg}")
            self.stats.stop_processing(filename)
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

            # Cleanup temporary color-fixed file if it was created
            if temp_fixed_file and temp_fixed_file.exists():
                try:
                    temp_fixed_file.unlink()
                except Exception as e:
                    self.logger.warning(f"Failed to cleanup temp file {temp_fixed_file}: {e}")

    def format_size(self, size: int) -> str:
        """Format size in bytes to human readable"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f}{unit}"
            size /= 1024.0
        return f"{size:.1f}TB"

    def format_time(self, seconds: float) -> str:
        """Format seconds to human readable time"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    def create_display(self, total_files: int, completed_count: int, queue: List[Path], completed_files_set: Set[Path] = None, submitted_files_set: Set[Path] = None, pending_files_list: List[Path] = None, in_flight_files: List[Path] = None, spinner_frame: int = 0) -> Group:
        """Create rich display with all panels"""
        stats = self.stats.get_stats()

        # Menu Panel
        menu_panel = Panel(
            "[bright_red]<[/bright_red] decrease threads | [bright_red]>[/bright_red] increase threads | [bright_red]S[/bright_red] stop | [bright_red]R[/bright_red] refresh",
            title="MENU",
            border_style="white"
        )

        # Status Panel
        status_lines = []
        current_threads = self.thread_controller.get_current()
        is_shutdown = self.thread_controller.is_shutdown_requested()

        if is_shutdown:
            status_lines.append(
                f"Total: {total_files} files | SHUTDOWN REQUESTED - finishing current tasks | "
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
        processing_table.add_column("Status", width=3, style="yellow")
        processing_table.add_column("File", style="yellow")
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

            # Choose spinner based on rotation
            spinner_frames = spinner_rotating if rotation_angle > 0 else spinner_simple

            # Animate: each file gets different phase of spinner based on frame counter
            spinner_char = spinner_frames[(spinner_frame + idx) % len(spinner_frames)]
            processing_table.add_row(
                spinner_char,
                filename,
                self.format_size(info['size']),
                self.format_time(elapsed)
            )

        if stats['processing']:
            processing_panel = Panel(
                processing_table,
                title=f"CURRENTLY PROCESSING ({len(stats['processing'])} files)",
                border_style="yellow"
            )
        else:
            processing_panel = Panel("No files processing", title="CURRENTLY PROCESSING", border_style="yellow")

        # Last Completed Panel
        completed_table = Table(show_header=False, box=None, padding=(0, 1))
        completed_table.add_column("Status", width=3, style="green")
        completed_table.add_column("File", style="green", no_wrap=False)
        completed_table.add_column("Input", justify="right", style="cyan")
        completed_table.add_column("→", justify="center", style="dim")
        completed_table.add_column("Output", justify="right", style="cyan")
        completed_table.add_column("Saved", justify="right", style="green")
        completed_table.add_column("Time", justify="right", style="yellow")

        # Show last 5 completed in reverse order (newest first)
        completed_list = list(reversed(list(stats['completed'])))
        for item in completed_list[:5]:
            completed_table.add_row(
                "✓",
                item['input'].name,
                self.format_size(item['input_size']),
                "→",
                self.format_size(item['output_size']),
                f"{item['compression_ratio']:.1f}%",
                self.format_time(item['duration'])
            )

        if stats['completed']:
            completed_panel = Panel(
                completed_table,
                title="LAST COMPLETED (5 files)",
                border_style="green"
            )
        else:
            completed_panel = Panel("No files completed yet", title="LAST COMPLETED", border_style="green")

        # Next in Queue Panel
        next_table = Table(show_header=False, box=None, padding=(0, 1))
        next_table.add_column("", width=3, style="dim")
        next_table.add_column("File")
        next_table.add_column("Size", justify="right")

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
                    next_table.add_row(
                        "⏳",
                        file.name,
                        self.format_size(file.stat().st_size)
                    )

        if next_files:
            queue_panel = Panel(
                next_table,
                title="NEXT IN QUEUE (5 files)",
                border_style="blue"
            )
        else:
            queue_panel = Panel("Queue empty", title="NEXT IN QUEUE", border_style="blue")

        # Summary at bottom
        summary = f"✓ {stats['success']} success  ✗ {stats['error']} errors  ⊘ {stats['skipped']} skipped"
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

    def run(self):
        """Main execution method"""
        # Save start time
        start_time = datetime.now()

        # Step 1: Cleanup old temp files
        self.cleanup_temp_files()

        # Step 2: Find all input files
        input_files = self.find_input_files()
        if not input_files:
            self.console.print("[yellow]No .mp4 files found![/yellow]")
            return

        # Step 3: Find already completed files
        completed_files = self.find_completed_files()

        # Step 4: Filter out completed files
        files_to_process = [f for f in input_files if f not in completed_files]

        if not files_to_process:
            self.console.print("[green]All files already compressed![/green]")
            return

        # Print initial info to console with file counts
        encoder_name = "SVT-AV1 (CPU)" if self.use_cpu else "NVENC AV1 (GPU)"

        start_info = f"""[cyan]Video Batch Compression - {encoder_name}[/cyan]
Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}
Input: {self.input_dir}
Output: {self.output_dir}
Threads: {self.thread_controller.get_current()}
Prefetch factor: {self.prefetch_factor}× (max_inflight = {self.prefetch_factor * self.thread_controller.get_current()})
Quality: CQ{self.cq}
Rotate 180°: {self.rotate_180}

Files to compress: {len(files_to_process)}
Already compressed: {len(completed_files)}"""

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
                    live.update(self.create_display(total_files, completed_count, files_to_process, completed_set_copy, None, pending_files_copy, in_flight_files_copy, frame))
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
                    new_input_files = self.find_input_files()
                    new_completed_files = self.find_completed_files()

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

                        # Filter: candidates = new files not in any known set
                        candidates = [
                            f for f in new_input_files
                            if f not in new_completed_files and f not in known
                        ]

                        if candidates:
                            # Sort new files alphabetically (optional)
                            candidates.sort()

                            # Add to end of pending queue (FIFO)
                            pending_files.extend(candidates)
                            files_to_process_list.extend(candidates)
                            total_files = len(files_to_process_list)

                            self.set_last_action(f"Refreshed: +{len(candidates)} new files")
                            self.logger.info(f"Refresh: added {len(candidates)} new files to queue")
                        else:
                            self.set_last_action("Refreshed: no new files")
                            self.logger.info("Refresh: no new files found")

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
                    live.update(self.create_display(total_files, completed_count, files_to_process_list, completed_set_copy, None, pending_files_copy, in_flight_files_copy, frame))
                except Exception as e:
                    self.logger.error(f"Refresh error: {e}")

        # Start keyboard listener thread
        keyboard_thread = threading.Thread(target=self.keyboard_listener, daemon=True)
        keyboard_thread.start()

        try:
            with Live(self.create_display(total_files, completed_count, files_to_process, set(), None, list(pending_files), [], 0),
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
                        live.update(self.create_display(total_files, completed_count, files_to_process, completed_set_copy, None, pending_files_copy, in_flight_files_copy, frame))

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

        self.console.print(Panel("\n".join(summary_lines), title="COMPRESSION SUMMARY", border_style="cyan"))


def main():
    # Load configuration from conf/vbc.conf
    config = load_config()

    parser = argparse.ArgumentParser(
        description='VBC - Video Batch Compression using AV1',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python vbc.py /path/to/videos --threads 4 --cq 45
  python vbc.py /path/to/videos --rotate-180 --no-metadata

Configuration:
  - Default values are loaded from conf/vbc.conf
  - CLI arguments override config file settings
  - Auto-rotation patterns defined in config file

Output:
  - Compressed files: /path/to/videos_out/
  - Log file: /path/to/videos_out/compression.log
  - Error files: *.mp4.err (if compression fails)
        """
    )

    parser.add_argument(
        'input_dir',
        type=Path,
        help='Input directory containing .mp4 files'
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

    args = parser.parse_args()

    # Validate input directory
    if not args.input_dir.exists():
        print(f"Error: Input directory does not exist: {args.input_dir}")
        sys.exit(1)

    if not args.input_dir.is_dir():
        print(f"Error: Input path is not a directory: {args.input_dir}")
        sys.exit(1)

    # Determine encoder: --cpu flag overrides config, otherwise use config['gpu']
    use_cpu = args.cpu if args.cpu else (not config['gpu'])

    # Determine metadata copying: --no-metadata flag overrides config
    copy_metadata = not args.no_metadata if args.no_metadata else config['copy_metadata']

    # Run compression
    compressor = VideoCompressor(
        input_dir=args.input_dir,
        threads=args.threads,
        cq=args.cq,
        rotate_180=args.rotate_180,
        use_cpu=use_cpu,
        prefetch_factor=args.prefetch_factor,
        copy_metadata=copy_metadata,
        autorotate_patterns=config['autorotate_patterns']
    )

    try:
        compressor.run()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Partial progress saved.")
        print("Re-run the script to continue from where it left off.")
        sys.exit(0)


if __name__ == '__main__':
    main()
