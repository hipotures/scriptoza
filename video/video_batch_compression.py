#!/usr/bin/env python3
"""
Batch video compression script using NVENC AV1 with rich UI
Compresses all .mp4 files in input directory to AV1 with specified quality
"""

import argparse
import logging
import select
import subprocess
import sys
import threading
import time
import termios
import tty
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
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


class ThreadController:
    """Dynamic thread control with condition variable"""
    def __init__(self, initial_threads: int, max_threads_limit: int = 16):
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

    def clamp_max_threads(self, new_max: int) -> bool:
        """Reduce allowed threads (used for backoff); returns True if changed"""
        with self.condition:
            new_max = max(self.min_threads, min(new_max, self.max_threads_limit))
            if new_max < self.max_threads:
                self.max_threads = new_max
                self.max_threads_limit = min(self.max_threads_limit, new_max)
                self.condition.notify_all()
                return True
            return False

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

    def start_processing(self, filename: str, size: int):
        with self.lock:
            self.processing[filename] = {
                'size': size,
                'start_time': datetime.now()
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
    def __init__(self, input_dir: Path, threads: int = 8, cq: int = 45, rotate_180: bool = False):
        self.input_dir = input_dir.resolve()
        self.output_dir = Path(f"{self.input_dir}_out")
        self.thread_controller = ThreadController(threads)
        self.cq = cq
        self.rotate_180 = rotate_180
        self.max_depth = 3
        self.stats = CompressionStats()
        self.console = Console()
        self.stop_keyboard_thread = threading.Event()
        self.last_action = ""
        self.last_action_lock = threading.Lock()
        self.max_nvenc_retries = 2
        self.nvenc_retry_delay = 2  # seconds
        self.nvenc_errors_seen = 0

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
        """Remove all .tmp and .err files from output directory"""
        if not self.output_dir.exists():
            return

        tmp_count = 0
        err_count = 0

        for tmp_file in self.output_dir.rglob("*.tmp"):
            tmp_file.unlink()
            tmp_count += 1

        for err_file in self.output_dir.rglob("*.err"):
            err_file.unlink()
            err_count += 1

        if tmp_count > 0 or err_count > 0:
            self.logger.info(f"Cleaned up {tmp_count} .tmp and {err_count} .err files")

    def set_last_action(self, action: str):
        """Set last keyboard action for display"""
        with self.last_action_lock:
            self.last_action = action

    def get_last_action(self) -> str:
        """Get last keyboard action"""
        with self.last_action_lock:
            return self.last_action

    def is_nvenc_session_error(self, message: str) -> bool:
        return "OpenEncodeSessionEx failed" in message or "Could not open encoder" in message

    def handle_nvenc_session_error(self):
        """Throttle threads when NVENC rejects new sessions"""
        self.nvenc_errors_seen += 1
        current = self.thread_controller.get_current()
        new_limit = max(self.thread_controller.min_threads, max(1, current // 2))
        if self.thread_controller.clamp_max_threads(new_limit):
            self.set_last_action(f"NVENC backoff → {new_limit} threads")
            self.logger.warning(
                "NVENC rejected a session. Reducing max concurrent encodes to %d to avoid GPU session limits.",
                new_limit
            )

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

        # Acquire thread slot (returns False if shutdown requested)
        if not self.thread_controller.acquire():
            return {
                'status': 'skipped',
                'input': input_file,
                'error': 'Shutdown requested'
            }

        # Mark as processing immediately after acquiring slot
        self.stats.start_processing(filename, input_size)

        try:
            output_file = self.get_output_path(input_file)
            tmp_file = output_file.parent / f"{output_file.stem}.tmp"
            err_file = output_file.parent / f"{output_file.stem}.err"

            # Create output directory if needed
            output_file.parent.mkdir(parents=True, exist_ok=True)

            attempt = 0

            while attempt <= self.max_nvenc_retries:
                # Build ffmpeg command
                cmd = [
                    'ffmpeg',
                    '-vsync', '0',
                    '-hwaccel', 'cuda',
                    '-fflags', '+genpts',  # Generate presentation timestamps
                    '-avoid_negative_ts', 'make_zero',  # Fix negative timestamps
                    '-i', str(input_file),
                ]

                # Add rotation filter if requested
                if self.rotate_180:
                    cmd.extend(['-vf', 'hflip,vflip'])

                cmd.extend([
                    '-c:v', 'av1_nvenc',
                    '-preset', 'p7',
                    '-cq', str(self.cq),
                    '-b:v', '0',
                    '-c:a', 'copy',
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
                error_msg = result.stderr if result.stderr else "Unknown error"
                is_nvenc_error = self.is_nvenc_session_error(error_msg)

                if is_nvenc_error and attempt < self.max_nvenc_retries:
                    self.handle_nvenc_session_error()
                    if tmp_file.exists():
                        tmp_file.unlink()
                    self.logger.warning(
                        "Retrying %s after NVENC session error (%d/%d) following %ds backoff",
                        filename,
                        attempt + 1,
                        self.max_nvenc_retries,
                        self.nvenc_retry_delay
                    )
                    time.sleep(self.nvenc_retry_delay)
                    attempt += 1
                    continue

                if tmp_file.exists():
                    tmp_file.unlink()

                hint = ""
                if is_nvenc_error:
                    hint = (
                        "\n\nHint: NVENC refused to open another session. "
                        f"Lower concurrent threads (current cap: {self.thread_controller.get_current()}) "
                        "and retry."
                    )

                err_file.write_text(error_msg + hint)
                self.logger.error(f"Failed: {filename}: {error_msg}")
                self.stats.stop_processing(filename)
                return {
                    'status': 'error',
                    'input': input_file,
                    'error': error_msg
                }

            # If loop exits unexpectedly, treat as error
            self.stats.stop_processing(filename)
            return {
                'status': 'error',
                'input': input_file,
                'error': 'Unknown error - retries exhausted'
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

    def create_display(self, total_files: int, completed_count: int, queue: List[Path]) -> Group:
        """Create rich display with all panels"""
        stats = self.stats.get_stats()

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
                f"Total: {total_files} files | Threads: {current_threads} (</> to adjust, S to stop) | "
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
        max_threads = current_threads
        last_action = self.get_last_action()

        progress_text = (
            f"Progress: {completed_count}/{total_files} ({completed_count*100//total_files if total_files > 0 else 0}%) | "
            f"Active threads: {active_threads}/{max_threads}"
        )
        if last_action:
            progress_text += f" | {last_action}"

        progress_panel = Panel(progress_text, border_style="green")

        # Currently Processing Panel
        processing_table = Table(show_header=False, box=None, padding=(0, 1))
        processing_table.add_column("File", style="yellow")
        processing_table.add_column("Size", justify="right")
        processing_table.add_column("Time", justify="right")

        for filename, info in list(stats['processing'].items()):
            elapsed = (datetime.now() - info['start_time']).total_seconds()
            processing_table.add_row(
                f"⏳ {filename}",
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
                f"✓ {item['input'].name}",
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
        next_table.add_column("No.", style="dim")
        next_table.add_column("File")
        next_table.add_column("Size", justify="right")

        next_files = queue[completed_count:completed_count + 5]
        for idx, file in enumerate(next_files, 1):
            if file.exists():
                next_table.add_row(
                    f"{idx}.",
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
            status_panel,
            progress_panel,
            processing_panel,
            completed_panel,
            queue_panel,
            summary_panel
        )

    def run(self):
        """Main execution method"""
        # Print initial info to console
        self.console.print(f"\n[cyan]Video Batch Compression - NVENC AV1[/cyan]")
        self.console.print(f"Input: {self.input_dir}")
        self.console.print(f"Output: {self.output_dir}")
        self.console.print(f"Threads: {self.thread_controller.get_current()} (use < and > keys to adjust, S to stop)")
        self.console.print(f"Quality: CQ{self.cq}")
        self.console.print(f"Rotate 180°: {self.rotate_180}\n")

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

        self.console.print(f"Files to compress: {len(files_to_process)}")
        self.console.print(f"Already compressed: {len(completed_files)}\n")

        # Step 5: Compress files in parallel with live display
        completed_count = 0
        total_files = len(files_to_process)
        stop_refresh = threading.Event()

        def auto_refresh():
            """Auto-refresh display every 0.2 seconds"""
            while not stop_refresh.is_set():
                try:
                    live.update(self.create_display(total_files, completed_count, files_to_process))
                except:
                    pass
                stop_refresh.wait(0.2)

        # Start keyboard listener thread
        keyboard_thread = threading.Thread(target=self.keyboard_listener, daemon=True)
        keyboard_thread.start()

        try:
            with Live(self.create_display(total_files, completed_count, files_to_process),
                      refresh_per_second=10, console=self.console) as live:

                # Start auto-refresh thread
                refresh_thread = threading.Thread(target=auto_refresh, daemon=True)
                refresh_thread.start()

                # Use max 16 workers pool, actual limit controlled by semaphore
                executor = ThreadPoolExecutor(max_workers=16)
                try:
                    # Submit all tasks
                    futures = {
                        executor.submit(self.compress_file, file): file
                        for file in files_to_process
                    }

                    # Process results
                    for future in as_completed(futures):
                        try:
                            result = future.result()

                            if result['status'] == 'success':
                                self.stats.add_success(result)
                            elif result['status'] == 'skipped':
                                self.stats.add_skipped()
                            else:
                                self.stats.add_error()

                            completed_count += 1
                            live.update(self.create_display(total_files, completed_count, files_to_process))

                        except Exception as e:
                            self.logger.error(f"Unexpected error in main loop: {e}")
                            self.stats.add_error()
                            completed_count += 1
                            live.update(self.create_display(total_files, completed_count, files_to_process))

                except KeyboardInterrupt:
                    self.console.print("\n[yellow]Ctrl+C detected - stopping new tasks...[/yellow]")
                    self.logger.info("Keyboard interrupt - graceful shutdown")

                    # Stop accepting new tasks
                    self.thread_controller.graceful_shutdown()

                    # Cancel all pending futures
                    for future in futures:
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
        stats = self.stats.get_stats()
        self.console.print("\n[cyan]" + "="*60 + "[/cyan]")
        self.console.print("[cyan]COMPRESSION SUMMARY[/cyan]")
        self.console.print("[cyan]" + "="*60 + "[/cyan]")
        self.console.print(f"Total files processed: {total_files}")
        self.console.print(f"[green]Successful: {stats['success']}[/green]")
        self.console.print(f"[yellow]Skipped: {stats['skipped']}[/yellow]")
        self.console.print(f"[red]Failed: {stats['error']}[/red]")

        if stats['success'] > 0:
            self.console.print(f"Total input size: {self.format_size(stats['total_input_size'])}")
            self.console.print(f"Total output size: {self.format_size(stats['total_output_size'])}")
            self.console.print(f"Overall compression: {stats['avg_compression']:.1f}%")
            self.console.print(f"Total time: {self.format_time(stats['elapsed'])}")

        self.console.print("[cyan]" + "="*60 + "[/cyan]\n")


def main():
    parser = argparse.ArgumentParser(
        description='Batch compress videos using NVENC AV1',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python compress_batch.py /path/to/videos --threads 4 --cq 45
  python compress_batch.py /path/to/videos --threads 4 --cq 45 --rotate-180

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
        default=4,
        help='Number of parallel compression threads (default: 4)'
    )

    parser.add_argument(
        '--cq',
        type=int,
        default=45,
        help='AV1 constant quality value (default: 45, lower=better quality)'
    )

    parser.add_argument(
        '--rotate-180',
        action='store_true',
        help='Rotate video 180 degrees (equivalent to mpv --video-rotate=180)'
    )

    args = parser.parse_args()

    # Validate input directory
    if not args.input_dir.exists():
        print(f"Error: Input directory does not exist: {args.input_dir}")
        sys.exit(1)

    if not args.input_dir.is_dir():
        print(f"Error: Input path is not a directory: {args.input_dir}")
        sys.exit(1)

    # Run compression
    compressor = VideoCompressor(
        input_dir=args.input_dir,
        threads=args.threads,
        cq=args.cq,
        rotate_180=args.rotate_180
    )

    try:
        compressor.run()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Partial progress saved.")
        print("Re-run the script to continue from where it left off.")
        sys.exit(0)


if __name__ == '__main__':
    main()
