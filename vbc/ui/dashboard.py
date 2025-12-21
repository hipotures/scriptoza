import threading
import time
from datetime import datetime
from typing import Optional, Dict
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from vbc.ui.state import UIState
from vbc.domain.models import JobStatus

class Dashboard:
    """Renders the live dashboard UI."""

    def __init__(self, state: UIState):
        self.state = state
        self.console = Console()
        self._live: Optional[Live] = None
        self._refresh_thread: Optional[threading.Thread] = None
        self._stop_refresh = threading.Event()
        self._ui_lock = threading.Lock()
        self._spinner_frame = 0

    def format_size(self, size: int) -> str:
        """Format size in bytes to human readable"""
        if size == 0:
            return "0B"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f}{unit}"
            size /= 1024.0
        return f"{size:.1f}TB"

    def format_time(self, seconds: float) -> str:
        """Format seconds to human readable time"""
        if seconds < 60:
            return f"{int(seconds):02d}s"
        elif seconds < 3600:
            return f"{int(seconds / 60):02d}m {int(seconds % 60):02d}s"
        else:
            return f"{int(seconds / 3600)}h {int((seconds % 3600) / 60):02d}m"

    def format_resolution(self, metadata) -> str:
        """Format resolution as megapixels (e.g., '8M')"""
        if metadata and metadata.width and metadata.height:
            megapixels = round((metadata.width * metadata.height) / 1_000_000)
            return f"{megapixels}M"
        return ""

    def format_fps(self, metadata) -> str:
        """Format FPS as integer (e.g., '60fps')"""
        if metadata and metadata.fps:
            return f"{int(metadata.fps)}fps"
        return ""

    def _generate_menu_panel(self) -> Panel:
        return Panel(
            "[bright_red]<[/bright_red] decrease threads | [bright_red]>[/bright_red] increase threads | [bright_red]S[/bright_red] stop",
            title="MENU",
            border_style="white"
        )

    def _generate_status_panel(self) -> Panel:
        with self.state._lock:
            saved_gb = self.state.space_saved_bytes / (1024**3)
            ratio = self.state.compression_ratio * 100
            status = "ACTIVE" if not self.state.shutdown_requested else "SHUTTING DOWN"
            color = "green" if not self.state.shutdown_requested else "yellow"

            lines = [
                f"Status: [bold {color}]{status}[/]",
                f"Threads: {self.state.current_threads} | Done: {self.state.completed_count} | Failed: {self.state.failed_count} | Skipped: {self.state.skipped_count}",
                f"Storage: {saved_gb:.2f} GB saved ({ratio:.1f}% avg ratio)"
            ]

            # Add discovery info if available
            if self.state.discovery_finished:
                lines.append(
                    f"Files to compress: {self.state.files_to_process} | Already compressed: {self.state.already_compressed_count}"
                )
                lines.append(
                    f"Ignored: size: {self.state.ignored_small_count} | err: {self.state.ignored_err_count} | "
                    f"av1: {self.state.ignored_av1_count} | hw_cap: {self.state.hw_cap_count}"
                )

        return Panel("\n".join(lines), title="COMPRESSION STATUS", border_style="cyan")

    def _generate_progress_panel(self) -> Panel:
        with self.state._lock:
            eta_str = "calculating..."
            throughput_str = "0 MB/s"

            # Calculate throughput if we have completed files
            if self.state.processing_start_time and self.state.completed_count > 0:
                elapsed = (datetime.now() - self.state.processing_start_time).total_seconds()
                if elapsed > 0:
                    # Throughput in MB/s
                    throughput_bytes_per_sec = self.state.total_input_bytes / elapsed
                    throughput_mb = throughput_bytes_per_sec / (1024 * 1024)
                    throughput_str = f"{throughput_mb:.1f} MB/s"

                    # ETA calculation
                    total_to_process = self.state.files_to_process
                    completed = self.state.completed_count + self.state.failed_count
                    remaining = total_to_process - completed

                    if remaining > 0 and completed > 0:
                        # Average time per file
                        avg_time_per_file = elapsed / completed
                        eta_seconds = avg_time_per_file * remaining
                        eta_str = self.format_time(eta_seconds)

        content = f"ETA: {eta_str} | Throughput: {throughput_str}"
        return Panel(content, border_style="green")

    def _generate_processing_panel(self) -> Panel:
        with self.state._lock:
            if not self.state.active_jobs:
                return Panel("No files processing", title="CURRENTLY PROCESSING", border_style="yellow")

            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("", width=1, style="yellow")
            table.add_column("File", style="yellow", width=40, no_wrap=True, overflow="ellipsis")
            table.add_column("Res", width=3, justify="right", style="cyan")
            table.add_column("FPS", width=6, justify="right", style="cyan")
            table.add_column("Size", justify="right")
            table.add_column("Time", justify="right")

            spinner_frames = "●○◉◎"
            for idx, job in enumerate(self.state.active_jobs):
                spinner_char = spinner_frames[(self._spinner_frame + idx) % len(spinner_frames)]

                # Calculate elapsed time
                filename = job.source_file.path.name
                elapsed = 0.0
                if filename in self.state.job_start_times:
                    elapsed = (datetime.now() - self.state.job_start_times[filename]).total_seconds()

                table.add_row(
                    spinner_char,
                    filename[:40],
                    self.format_resolution(job.source_file.metadata),
                    self.format_fps(job.source_file.metadata),
                    self.format_size(job.source_file.size_bytes),
                    self.format_time(elapsed)
                )

        return Panel(table, title="CURRENTLY PROCESSING", border_style="yellow")

    def _generate_recent_panel(self) -> Panel:
        with self.state._lock:
            if not self.state.recent_jobs:
                return Panel("No files completed yet", title="LAST COMPLETED", border_style="green")

            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("", width=1, style="green")
            table.add_column("File", style="green", width=40, no_wrap=True, overflow="ellipsis")
            table.add_column("Res", width=3, justify="right", style="cyan")
            table.add_column("FPS", width=6, justify="right", style="cyan")
            table.add_column("Input", justify="right", style="cyan")
            table.add_column("→", width=1, justify="center", style="dim")
            table.add_column("Output", justify="right", style="cyan")
            table.add_column("Saved", justify="right", style="green")
            table.add_column("Time", justify="right", style="yellow")
            table.add_column("", width=2, justify="center", style="magenta")

            for job in list(self.state.recent_jobs)[:5]:
                if job.status == JobStatus.COMPLETED:
                    # Calculate compression ratio
                    input_size = job.source_file.size_bytes
                    output_size = job.output_size_bytes or 0
                    ratio = ((input_size - output_size) / input_size * 100) if input_size > 0 else 0.0

                    # Check if original was kept (min_ratio_skip)
                    warn_icon = "📋" if job.error_message and "kept original" in job.error_message else ""

                    table.add_row(
                        "✓",
                        job.source_file.path.name[:40],
                        self.format_resolution(job.source_file.metadata),
                        self.format_fps(job.source_file.metadata),
                        self.format_size(input_size),
                        "→",
                        self.format_size(output_size),
                        f"{ratio:.1f}%",
                        self.format_time(job.duration_seconds or 0),
                        warn_icon
                    )
                else:
                    # Failed job - show status instead of compression info
                    status_text = job.status.value if hasattr(job.status, 'value') else str(job.status)
                    table.add_row(
                        "✓",
                        job.source_file.path.name[:40],
                        self.format_resolution(job.source_file.metadata),
                        self.format_fps(job.source_file.metadata),
                        self.format_size(job.source_file.size_bytes),
                        "",
                        f"[red]{status_text}[/]",
                        "",
                        self.format_time(job.duration_seconds or 0),
                        ""
                    )

        return Panel(table, title="LAST COMPLETED", border_style="green")

    def _generate_queue_panel(self) -> Panel:
        with self.state._lock:
            if not self.state.pending_files:
                return Panel("Queue empty", title="NEXT IN QUEUE", border_style="blue")

            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("", width=1, style="dim")
            table.add_column("File", width=40, no_wrap=True, overflow="ellipsis")
            table.add_column("Res", width=3, justify="right", style="cyan")
            table.add_column("FPS", width=6, justify="right", style="cyan")
            table.add_column("Size", justify="right")
            table.add_column("Codec", width=5, justify="center", no_wrap=True, overflow="ellipsis")

            # Show first 5 pending files
            for vf in list(self.state.pending_files)[:5]:
                # Now we have VideoFile objects with metadata
                table.add_row(
                    "»",
                    vf.path.name[:40],
                    self.format_resolution(vf.metadata),
                    self.format_fps(vf.metadata),
                    self.format_size(vf.size_bytes),
                    vf.metadata.codec[:5] if vf.metadata and vf.metadata.codec else ""
                )

        return Panel(table, title="NEXT IN QUEUE", border_style="blue")

    def _generate_summary_panel(self) -> Panel:
        with self.state._lock:
            summary = (
                f"✓ {self.state.completed_count} success  "
                f"✗ {self.state.failed_count} errors  "
                f"⚠ {self.state.hw_cap_count} hw_cap  "
                f"📋 {self.state.min_ratio_skip_count} ratio  "
                f"⊘ {self.state.skipped_count} skipped"
            )
        return Panel(summary, border_style="white")

    def create_display(self) -> Group:
        """Creates display with all 7 panels."""
        return Group(
            self._generate_menu_panel(),
            self._generate_status_panel(),
            self._generate_progress_panel(),
            self._generate_processing_panel(),
            self._generate_recent_panel(),
            self._generate_queue_panel(),
            self._generate_summary_panel()
        )

    def _refresh_loop(self):
        """Background thread to update Live display."""
        while not self._stop_refresh.is_set():
            if self._live:
                self._spinner_frame = (self._spinner_frame + 1) % 4
                display = self.create_display()
                with self._ui_lock:
                    self._live.update(display)
            time.sleep(1.0)

    def start(self):
        """Starts the Live display and refresh thread."""
        self._live = Live(self.create_display(), console=self.console, refresh_per_second=10)
        self._live.start()
        self._stop_refresh.clear()
        self._refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._refresh_thread.start()
        return self

    def stop(self):
        """Stops the Live display and refresh thread."""
        self._stop_refresh.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=1.0)
        if self._live:
            self._live.stop()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()