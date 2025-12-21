import re
import threading
import time
from datetime import datetime
from typing import Optional, Dict
from rich.console import Console, Group
from rich.align import Align
from rich.segment import Segment
from rich._loop import loop_last

class _Overlay:
    """Render overlay panel centered over a background renderable."""

    def __init__(self, background, overlay, overlay_width: int):
        self.background = background
        self.overlay = overlay
        self.overlay_width = overlay_width

    def _slice_line(self, line, start: int, end: int):
        if start >= end:
            return []
        result = []
        pos = 0
        for segment in line:
            seg_len = segment.cell_length
            if seg_len == 0:
                if result:
                    result.append(segment)
                continue
            seg_end = pos + seg_len
            if seg_end <= start:
                pos = seg_end
                continue
            if pos >= end:
                break
            cut_start = max(start - pos, 0)
            cut_end = min(end - pos, seg_len)
            if cut_start == 0 and cut_end == seg_len:
                result.append(segment)
            else:
                _, right = segment.split_cells(cut_start)
                mid_len = cut_end - cut_start
                mid, _ = right.split_cells(mid_len)
                result.append(mid)
            pos = seg_end
        return result

    def __rich_console__(self, console, options):
        width, height = options.size

        bg_lines = console.render_lines(self.background, options, pad=True)
        bg_lines = Segment.set_shape(bg_lines, width, height)

        overlay_lines = console.render_lines(
            self.overlay,
            options.update(width=self.overlay_width),
            pad=True
        )
        overlay_lines = [
            Segment.adjust_line_length(line, self.overlay_width) for line in overlay_lines
        ]

        overlay_height = len(overlay_lines)
        left = max((width - self.overlay_width) // 2, 0)
        top = max((height - overlay_height) // 2, 0)

        for idx, overlay_line in enumerate(overlay_lines):
            target_row = top + idx
            if target_row < 0 or target_row >= height:
                continue
            bg_line = bg_lines[target_row]
            left_seg = self._slice_line(bg_line, 0, left)
            right_seg = self._slice_line(bg_line, left + self.overlay_width, width)
            bg_lines[target_row] = left_seg + overlay_line + right_seg

        for last, line in loop_last(bg_lines):
            yield from line
            if not last:
                yield Segment.line()
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

    def _sanitize_filename(self, filename: str) -> str:
        """Remove non-ASCII characters for display."""
        if not self.state.strip_unicode_display:
            return filename
        return "".join(c for c in filename if ord(c) < 128)

    def _generate_menu_panel(self) -> Panel:
        return Panel(
            "[bright_red]<[/bright_red] decrease threads | [bright_red]>[/bright_red] increase threads | [bright_red]S[/bright_red] stop | [bright_red]R[/bright_red] refresh | [bright_red]C[/bright_red] config | [bright_red]Esc[/bright_red] close",
            title="MENU",
            border_style="white"
        )

    def _generate_config_overlay(self) -> Panel:
        with self.state._lock:
            lines = self.state.config_lines[:]
        if lines:
            formatted = [self._format_kv_line(line) for line in lines]
            content = "\n".join(formatted)
        else:
            content = "No configuration available."
        width = self.console.size.width
        panel_width = max(40, int(width * 0.6))
        panel_width = min(panel_width, max(20, width - 4))
        return Panel(
            content,
            title="CONFIGURATION",
            border_style="cyan",
            width=panel_width,
            style="white on black",
            expand=False
        )

    def _generate_status_panel(self) -> Panel:
        with self.state._lock:
            saved_gb = self.state.space_saved_bytes / (1024**3)
            ratio = self.state.compression_ratio * 100
            if self.state.interrupt_requested:
                status = "INTERRUPTED"
                color = "bright_red"
            elif self.state.shutdown_requested:
                status = "SHUTTING DOWN"
                color = "yellow"
            elif self.state.finished:
                status = "FINISHED"
                color = "cyan"
            else:
                status = "ACTIVE"
                color = "green"

            lines = [
                f"[dim]Status:[/] [bold {color}]{status}[/]",
                (
                    f"[dim]Threads:[/] {self.state.current_threads} | "
                    f"[dim]Done:[/] {self.state.completed_count} | "
                    f"[dim]Failed:[/] {self.state.failed_count} | "
                    f"[dim]Skipped:[/] {self.state.skipped_count}"
                ),
                f"[dim]Storage:[/] {saved_gb:.2f} GB saved ({ratio:.1f}% avg ratio)"
            ]

            # Add discovery info if available
            if self.state.discovery_finished:
                lines.append(
                    f"[dim]Files to compress:[/] {self.state.files_to_process} | "
                    f"[dim]Already compressed:[/] {self.state.already_compressed_count}"
                )
                lines.append(
                    f"[dim]Ignored:[/] [dim]size:[/] {self.state.ignored_small_count} | "
                    f"[dim]err:[/] {self.state.ignored_err_count} | "
                    f"[dim]av1:[/] {self.state.ignored_av1_count} | "
                    f"[dim]cam:[/] {self.state.cam_skipped_count} | "
                    f"[dim]hw_cap:[/] {self.state.hw_cap_count} | "
                    f"[dim]ratio:[/] {self.state.min_ratio_skip_count}"
                )

        return Panel("\n".join(lines), title="COMPRESSION STATUS", border_style="cyan")

    def _format_kv_line(self, line: str) -> str:
        if ": " not in line:
            return line
        def _mark_key(match: re.Match) -> str:
            prefix = match.group(1)
            key = match.group(2)
            return f"{prefix}[grey70]{key}:[/] "

        return re.sub(r"(^|[|(]\s*)([^:|()]+):\s+", _mark_key, line)

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

            # Get last action message (like old vbc.py line 1343-1344)
            last_action = self.state.get_last_action()

        content = f"ETA: {eta_str} | Throughput: {throughput_str}"
        if last_action:
            # Highlight action messages in bright red for visibility
            content += f" | [bright_red]{last_action}[/bright_red]"
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
            spinner_rotating = "◐◓◑◒"
            for idx, job in enumerate(self.state.active_jobs):
                use_spinner = spinner_rotating if (job.rotation_angle or 0) > 0 else spinner_frames
                spinner_char = use_spinner[(self._spinner_frame + idx) % len(use_spinner)]

                # Calculate elapsed time
                filename = self._sanitize_filename(job.source_file.path.name)
                elapsed = 0.0
                start_key = job.source_file.path.name
                if start_key in self.state.job_start_times:
                    elapsed = (datetime.now() - self.state.job_start_times[start_key]).total_seconds()

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
                display_name = self._sanitize_filename(job.source_file.path.name)
                if job.status == JobStatus.COMPLETED:
                    # Calculate compression ratio
                    input_size = job.source_file.size_bytes
                    output_size = job.output_size_bytes or 0
                    ratio = ((input_size - output_size) / input_size * 100) if input_size > 0 else 0.0

                    # Check if original was kept (min_ratio_skip)
                    warn_icon = "📋" if job.error_message and "kept original" in job.error_message else ""

                    table.add_row(
                        "✓",
                        display_name[:40],
                        self.format_resolution(job.source_file.metadata),
                        self.format_fps(job.source_file.metadata),
                        self.format_size(input_size),
                        "→",
                        self.format_size(output_size),
                        f"{ratio:.1f}%",
                        self.format_time(job.duration_seconds or 0),
                        warn_icon
                    )
                elif job.status == JobStatus.INTERRUPTED:
                    # Interrupted job (Ctrl+C) - show in bright red
                    table.add_row(
                        "✗",
                        display_name[:40],
                        self.format_resolution(job.source_file.metadata),
                        self.format_fps(job.source_file.metadata),
                        self.format_size(job.source_file.size_bytes),
                        "",
                        f"[bright_red]INTERRUPTED[/bright_red]",
                        "",
                        self.format_time(job.duration_seconds or 0),
                        "⚠"
                    )
                else:
                    # Failed job - show status instead of compression info
                    status_text = job.status.value if hasattr(job.status, 'value') else str(job.status)
                    table.add_row(
                        "✗",
                        display_name[:40],
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
            table.add_column("Cam", width=18, style="magenta", no_wrap=True, overflow="ellipsis")
            table.add_column("Res", width=3, justify="right", style="cyan")
            table.add_column("FPS", width=6, justify="right", style="cyan")
            table.add_column("Size", justify="right")
            table.add_column("Codec", width=5, justify="center", no_wrap=True, overflow="ellipsis")

            # Show first 5 pending files
            for vf in list(self.state.pending_files)[:5]:
                # Metadata is already cached by orchestrator
                display_name = self._sanitize_filename(vf.path.name)
                cam_model = ""
                if vf.metadata:
                    cam_model = vf.metadata.camera_model or vf.metadata.camera_raw or ""
                cam_model = self._sanitize_filename(cam_model)

                table.add_row(
                    "»",
                    display_name[:40],
                    cam_model[:18],
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
                f"⚡ {self.state.interrupted_count} interrupted  "
                f"⚠ {self.state.hw_cap_count} hw_cap  "
                f"📋 {self.state.min_ratio_skip_count} ratio  "
                f"⊘ {self.state.skipped_count} skipped"
            )
        return Panel(summary, title="SESSION STATUS", border_style="white")

    def create_display(self) -> Group:
        """Creates display with all 7 panels."""
        if self.state.show_config:
            overlay = self._generate_config_overlay()
            base = Group(
                self._generate_menu_panel(),
                self._generate_status_panel(),
                self._generate_progress_panel(),
                self._generate_processing_panel(),
                self._generate_recent_panel(),
                self._generate_queue_panel(),
                self._generate_summary_panel()
            )
            return _Overlay(base, overlay, overlay.width or int(self.console.size.width * 0.6))

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
            with self._ui_lock:
                self._live.update(self.create_display())
            self._live.stop()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
