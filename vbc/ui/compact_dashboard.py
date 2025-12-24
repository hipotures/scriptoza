import re
import threading
import time
from datetime import datetime
from typing import Optional
from rich.live import Live
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.progress_bar import ProgressBar
from rich.align import Align
from rich.segment import Segment
from rich._loop import loop_last
from vbc.ui.state import UIState
from vbc.domain.models import JobStatus


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


class CompactDashboard:
    """Compact two-column UI implementation."""

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
        sanitized = "".join(c for c in filename if ord(c) < 128)
        return sanitized.lstrip()

    def _format_kv_line(self, line: str) -> str:
        """Format key-value lines for config overlay."""
        if ": " not in line:
            return line
        def _mark_key(match: re.Match) -> str:
            prefix = match.group(1)
            key = match.group(2)
            return f"{prefix}[grey70]{key}:[/] "

        return re.sub(r"(^|[|(]\s*)([^:|()]+):\s+", _mark_key, line)

    def _generate_top_status_bar(self) -> Panel:
        """Top status bar: status + ETA + throughput + savings + keybinds."""
        with self.state._lock:
            # Status indicator
            if self.state.finished:
                status = "[green]FINISHED[/]"
                indicator = "[green]●[/]"
            elif self.state.shutdown_requested:
                status = "[yellow]SHUTTING DOWN[/]"
                indicator = "[yellow]◐[/]"
            elif self.state.interrupt_requested:
                status = "[bright_red]INTERRUPTED[/]"
                indicator = "[red]![/]"
            else:
                status = "[bright_cyan]ACTIVE[/]"
                indicator = "[green]●[/]"

            # ETA calculation (reuse logic from dashboard.py)
            eta_str = "calculating..."
            if self.state.processing_start_time and self.state.completed_count > 0:
                elapsed = (datetime.now() - self.state.processing_start_time).total_seconds()
                if elapsed > 0:
                    total_to_process = self.state.files_to_process
                    completed = self.state.completed_count + self.state.failed_count
                    remaining = total_to_process - completed

                    if remaining > 0 and completed > 0:
                        avg_time_per_file = elapsed / completed
                        eta_seconds = avg_time_per_file * remaining
                        eta_str = self.format_time(eta_seconds)

            # Throughput (copy from dashboard.py lines 242-248)
            throughput_str = "0.0 MB/s"
            if self.state.processing_start_time and self.state.completed_count > 0:
                elapsed = (datetime.now() - self.state.processing_start_time).total_seconds()
                if elapsed > 0:
                    throughput_bytes_per_sec = self.state.total_input_bytes / elapsed
                    throughput_mb = throughput_bytes_per_sec / (1024 * 1024)
                    throughput_str = f"{throughput_mb:.1f} MB/s"

            # Savings
            saved = self.state.space_saved_bytes
            saved_str = self.format_size(saved)
            ratio = self.state.compression_ratio

            # Build status lines
            line1 = f"[{indicator}] {status} • Threads: {self.state.current_threads}"
            line2 = f"⏱ ETA: {eta_str} • ⚡ {throughput_str} • 💾 {saved_str} saved ({ratio:.1f}%)"
            line3 = "[dim]<> threads | S stop | R refresh | C config[/]"

            content = f"{line1}\n{line2}\n{line3}"

        return Panel(content, border_style="cyan", title="VBC")

    def _generate_progress_section(self) -> Panel:
        """Overall progress with bar and counters."""
        with self.state._lock:
            total = self.state.files_to_process
            done = self.state.completed_count
            failed = self.state.failed_count
            skipped = self.state.skipped_count

            # Create table for progress bar
            table = Table.grid(padding=(0, 1))
            table.add_column(ratio=1)
            table.add_column(no_wrap=True)

            if total > 0:
                pct = (done / total) * 100
                table.add_row(
                    ProgressBar(total=total, completed=done, width=None),
                    f"{done}/{total}"
                )
            else:
                table.add_row("No files to process", "")

            stats = f"Done: {done} | Failed: {failed} | Skipped: {skipped}"

            content = Group(table, stats)

        return Panel(content, title="PROGRESS", border_style="cyan")

    def _generate_active_jobs(self) -> Panel:
        """Currently processing jobs table."""
        with self.state._lock:
            if not self.state.active_jobs:
                return Panel("[dim]No active jobs[/]", title="ACTIVE JOBS", border_style="cyan")

            # Main table with 3 rows per job
            table = Table(show_header=False, box=None, padding=(0, 0), expand=True)
            table.add_column("Job", no_wrap=True, overflow="ellipsis")

            spinner_frames = "●◐◓◑◒"
            for idx, job in enumerate(self.state.active_jobs):
                # Spinner (use rotating spinner for all jobs)
                spinner = spinner_frames[(self._spinner_frame + idx) % len(spinner_frames)]

                # File info
                filename = self._sanitize_filename(job.source_file.path.name)
                res = self.format_resolution(job.source_file.metadata)
                fps = self.format_fps(job.source_file.metadata)
                size = self.format_size(job.source_file.size_bytes)

                # Progress
                prog_pct = job.progress_percent or 0

                # Calculate ETA
                eta_str = "calculating..."
                start_key = job.source_file.path.name
                if start_key in self.state.job_start_times:
                    elapsed = (datetime.now() - self.state.job_start_times[start_key]).total_seconds()
                    if 0 < prog_pct < 100 and elapsed > 0:
                        eta_seconds = (elapsed / prog_pct) * (100 - prog_pct)
                        eta_str = self.format_time(eta_seconds)

                # Create progress grid for line 3
                progress_grid = Table.grid(padding=(0, 1), expand=True)
                progress_grid.add_column(width=4, no_wrap=True)
                progress_grid.add_column(ratio=1)
                progress_grid.add_column(no_wrap=True, width=7)
                progress_grid.add_column(no_wrap=True, width=1)
                progress_grid.add_column(no_wrap=True, width=8)

                progress_grid.add_row(
                    "",
                    ProgressBar(total=100, completed=int(prog_pct), width=None),
                    f"{prog_pct:>5.1f}%",
                    "•",
                    eta_str
                )

                # Line 1: spinner + filename (will be cut with ...)
                table.add_row(f"{spinner} {filename}")
                # Line 2: metadata
                table.add_row(f"    {res} {fps}  {size}")
                # Line 3: progress bar
                table.add_row(progress_grid)

                # Spacer between jobs
                if idx < len(self.state.active_jobs) - 1:
                    table.add_row("")

        return Panel(table, title="ACTIVE JOBS", border_style="cyan")

    def _generate_activity_feed(self) -> Panel:
        """Unified feed: completed/failed/skipped/interrupted."""
        with self.state._lock:
            if not self.state.recent_jobs:
                return Panel("[dim]No recent activity[/]", title="ACTIVITY FEED", border_style="cyan")

            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("Status", width=1)
            table.add_column("Details", ratio=1)

            for job in list(self.state.recent_jobs)[:10]:  # Show up to 10
                filename = self._sanitize_filename(job.source_file.path.name)

                if job.status == JobStatus.COMPLETED:
                    icon = "[green]✓[/]"
                    in_size = self.format_size(job.source_file.size_bytes)
                    out_size = self.format_size(job.output_size_bytes)
                    ratio = ((job.source_file.size_bytes - job.output_size_bytes) / job.source_file.size_bytes) * 100
                    time_taken = self.format_time(job.duration_seconds)

                    table.add_row(icon, f"{filename}")
                    table.add_row("", f"  [green]{in_size}→{out_size}  {ratio:.1f}% • {time_taken}[/]")

                elif job.status == JobStatus.FAILED:
                    icon = "[red]✗[/]"
                    error_msg = job.error_message or "Unknown error"
                    table.add_row(icon, f"{filename}")
                    table.add_row("", f"  [red]FAILED: {error_msg}[/]")

                elif job.status == JobStatus.INTERRUPTED:
                    icon = "[bright_red]⚡[/]"
                    table.add_row(icon, f"{filename}")
                    table.add_row("", "  [bright_red]INTERRUPTED[/]")

                elif job.status == JobStatus.SKIPPED:
                    icon = "[yellow]⊘[/]"
                    table.add_row(icon, f"{filename}")
                    table.add_row("", "  [yellow]SKIPPED: kept original[/]")

                # Spacer between entries
                table.add_row("", "")

        return Panel(table, title="ACTIVITY FEED", border_style="cyan")

    def _generate_queue(self) -> Panel:
        """Next files in queue."""
        with self.state._lock:
            if not self.state.pending_files:
                return Panel("[dim]Queue empty[/]", title="QUEUE (Next 5)", border_style="cyan")

            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("", width=1)
            table.add_column("File", ratio=1)

            for file in list(self.state.pending_files)[:5]:
                filename = self._sanitize_filename(file.path.name)
                res = self.format_resolution(file.metadata)
                fps = self.format_fps(file.metadata)
                size = self.format_size(file.size_bytes)

                table.add_row("»", filename)
                table.add_row("", f"  {res} {fps}  {size}")
                table.add_row("", "")  # Spacer between items

        return Panel(table, title="QUEUE (Next 5)", border_style="cyan")

    def _generate_bottom_status(self) -> Panel:
        """Health metrics + last action."""
        with self.state._lock:
            # Health metrics
            threads = self.state.current_threads
            ig_size = self.state.ignored_small_count
            ig_err = self.state.ignored_err_count
            ig_av1 = self.state.ignored_av1_count
            ig_hwcap = self.state.hw_cap_count
            ig_ratio = self.state.min_ratio_skip_count

            health = (
                f"Threads: {threads} | "
                f"Ignored: size:{ig_size} err:{ig_err} av1:{ig_av1} hw_cap:{ig_hwcap} ratio:{ig_ratio}"
            )

            # Last action (show if < 60s old)
            action_line = ""
            if self.state.last_action and self.state.last_action_time:
                age = (datetime.now() - self.state.last_action_time).total_seconds()
                if age < 60:
                    action_line = f"\nLast action: {self.state.last_action}"

            content = health + action_line

        return Panel(content, title="HEALTH", border_style="cyan")

    def _generate_config_overlay(self) -> Panel:
        """Config overlay (copy from dashboard.py lines 146-164)."""
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

    def create_display(self):
        """Creates compact two-column layout with Rich Layout."""
        # Create main layout
        layout = Layout()

        # Split into 3 rows: top, middle, bottom
        layout.split_column(
            Layout(name="top", size=5),      # Top status bar
            Layout(name="middle"),            # Main content
            Layout(name="bottom", size=4)     # Bottom status
        )

        # Split middle into 2 columns (equal width)
        layout["middle"].split_row(
            Layout(name="left"),     # Progress + Active Jobs
            Layout(name="right")     # Activity Feed + Queue
        )

        # Update top
        layout["top"].update(self._generate_top_status_bar())

        # Update left column
        left_group = Group(
            self._generate_progress_section(),
            self._generate_active_jobs()
        )
        layout["left"].update(left_group)

        # Update right column
        right_group = Group(
            self._generate_activity_feed(),
            self._generate_queue()
        )
        layout["right"].update(right_group)

        # Update bottom
        layout["bottom"].update(self._generate_bottom_status())

        # Handle overlays
        if self.state.show_config:
            return _Overlay(layout, self._generate_config_overlay(), overlay_width=80)
        elif self.state.show_info:
            info_panel = Panel(
                Align.center(self.state.info_message),
                title="NOTICE",
                border_style="yellow",
                width=60,
                style="white on black",
                expand=False
            )
            return _Overlay(layout, info_panel, overlay_width=60)

        return layout

    def _refresh_loop(self):
        """Background refresh thread."""
        while not self._stop_refresh.is_set():
            if self._live:
                self._spinner_frame = (self._spinner_frame + 1) % 5
                display = self.create_display()
                with self._ui_lock:
                    self._live.update(display)
            time.sleep(0.5)

    def start(self):
        """Start the UI refresh thread."""
        self._live = Live(self.create_display(), console=self.console, refresh_per_second=10)
        self._live.start()
        self._stop_refresh.clear()
        self._refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._refresh_thread.start()
        return self

    def stop(self):
        """Stop the UI refresh thread."""
        self._stop_refresh.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=1.0)
        if self._live:
            with self._ui_lock:
                self._live.update(self.create_display())
            self._live.stop()

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False
