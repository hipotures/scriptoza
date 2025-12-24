import re
import threading
import time
from datetime import datetime
from typing import Optional, List, Tuple, Any
from rich.live import Live
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.progress_bar import ProgressBar
from rich.align import Align
from rich.segment import Segment
from rich._loop import loop_last
from rich.text import Text
from vbc.ui.state import UIState
from vbc.domain.models import JobStatus

# Layout Constants
TOP_BAR_LINES = 3  # Status + KPI + Hint
FOOTER_LINES = 1   # Health counters
MIN_2COL_W = 110   # Breakpoint for 2-column layout

# Panel content min/max heights (lines within frame)
PROGRESS_MIN = 2   # Done/Total + bar
PROGRESS_MAX = 2   # Compact mode
ACTIVE_MIN = 1
ACTIVITY_MIN = 1
QUEUE_MIN = 1


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
    """Adaptive UI implementation with dynamic density control."""

    def __init__(self, state: UIState):
        self.state = state
        self.console = Console()
        self._live: Optional[Live] = None
        self._refresh_thread: Optional[threading.Thread] = None
        self._stop_refresh = threading.Event()
        self._ui_lock = threading.Lock()
        self._spinner_frame = 0

    # --- Formatters ---

    def format_size(self, size: int) -> str:
        """Format size: 123B, 1.2KB, 45.1MB, 3.2GB."""
        if size == 0:
            return "0B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        idx = 0
        val = float(size)
        while val >= 1024.0 and idx < len(units) - 1:
            val /= 1024.0
            idx += 1
        
        if idx < 2: # B, KB -> no decimal usually, but let's stick to spec
            if idx == 0: return f"{int(val)}B"
            return f"{val:.1f}KB"
        return f"{val:.1f}{units[idx]}"

    def format_time(self, seconds: float) -> str:
        """Format time: mm:ss (for <1h) or hh:mm."""
        if seconds is None:
            return "--:--"
        if seconds < 3600:
            return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"
        else:
            return f"{int(seconds // 3600):02d}h {int((seconds % 3600) // 60):02d}m"
            
    def format_global_eta(self, seconds: float) -> str:
        """Format global ETA: hh:mm or mm:ss."""
        if seconds is None:
            return "--:--"
        if seconds < 60:
            return f"{int(seconds):02d}s"
        elif seconds < 3600:
            return f"{int(seconds // 60):02d}m {int(seconds % 60):02d}s"
        else:
            return f"{int(seconds // 3600):02d}h {int((seconds % 3600) // 60):02d}m"

    def format_resolution(self, metadata) -> str:
        if metadata and metadata.width and metadata.height:
            megapixels = round((metadata.width * metadata.height) / 1_000_000)
            return f"{megapixels}M"
        return ""

    def format_fps(self, metadata) -> str:
        if metadata and metadata.fps:
            return f"{int(metadata.fps)}fps"
        return ""
        
    def _sanitize_filename(self, filename: str, max_len: int = 30) -> str:
        """Sanitize and truncate filename: prefix...suffix."""
        if self.state.strip_unicode_display:
            filename = "".join(c for c in filename if ord(c) < 128)
        filename = filename.lstrip()
        
        if len(filename) <= max_len:
            return filename
            
        part_len = (max_len - 1) // 2
        return f"{filename[:part_len]}…{filename[-part_len:]}"

    # --- Render Logic ---

    def _render_list(self, items: List[Any], available_lines: int, 
                     levels: List[Tuple[str, int]], render_func) -> Table:
        """Generic list renderer with density degradation."""
        table = Table(show_header=False, box=None, padding=(0, 0), expand=True)
        table.add_column("Content", ratio=1)
        
        if available_lines <= 0:
            return table
            
        if not items:
            # table.add_row("[dim]Empty[/]") 
            # Better to show nothing for empty lists to save space visual noise
            return table

        selected_level = levels[-1][0] # Default to lowest density
        items_to_show = []
        has_more = False
        more_count = 0
        
        # Select highest density that allows showing at least 1 item
        for level_name, lines_per_item in levels:
            max_items = available_lines // lines_per_item
            if max_items >= 1:
                selected_level = level_name
                # Check if we need "more" line
                if len(items) <= max_items:
                    items_to_show = items
                    has_more = False
                elif available_lines >= lines_per_item + 1: # Reserve 1 line for "... +N more"
                     max_items_res = (available_lines - 1) // lines_per_item
                     if max_items_res >= 1:
                         items_to_show = items[:max_items_res]
                         more_count = len(items) - max_items_res
                         has_more = True
                     else:
                         # Not enough space for more line, show what fits
                         items_to_show = items[:max_items]
                         has_more = False # Or just implicit cut
                else:
                    items_to_show = items[:max_items]
                    has_more = True # Implicit
                    more_count = len(items) - max_items
                break
        
        # Render items
        for i, item in enumerate(items_to_show):
            content = render_func(item, selected_level)
            table.add_row(content)
            # Add spacer if needed? No, strict lines packing.
            
        if has_more and more_count > 0:
            table.add_row(f"[dim]… +{more_count} more")
            
        return table

    def _render_active_job(self, job, level: str) -> RenderableType:
        """Render active job based on density level."""
        filename = self._sanitize_filename(job.source_file.path.name, max_len=40)
        spinner_chars = "●◐◓◑◒"
        spinner = spinner_chars[(self._spinner_frame + hash(filename)) % 5]
        
        # Metadata
        meta = job.source_file.metadata
        dur_sec = meta.duration if meta else 0
        dur = self.format_time(dur_sec)
        fps = self.format_fps(meta)
        size = self.format_size(job.source_file.size_bytes)
        
        # Progress
        pct = job.progress_percent or 0.0
        
        # ETA calculation
        eta_str = "--:--"
        start_key = job.source_file.path.name
        if start_key in self.state.job_start_times:
            elapsed = (datetime.now() - self.state.job_start_times[start_key]).total_seconds()
            if 0 < pct < 100 and elapsed > 0:
                eta_seconds = (elapsed / pct) * (100 - pct)
                eta_str = self.format_time(eta_seconds)

        if level == "A": # 3 lines
            # L1: ● filename
            # L2: dur 01:02 • 30fps • in 762.4MB
            # L3: [====] 37.9% • 03:26
            
            l1 = f"[green]{spinner}[/] {filename}"
            l2 = f"  [dim]dur {dur} • {fps} • in {size}[/]"
            
            bar = ProgressBar(total=100, completed=int(pct), width=15)
            l3_grid = Table.grid(padding=(0, 1))
            l3_grid.add_row(" ", bar, f"{pct:>5.1f}%", "•", eta_str)
            
            g = Group(l1, l2, l3_grid)
            return g
            
        elif level == "B": # 2 lines
            # L1: ● filename
            # L2: 37.9% • 03:26 • 762.4MB • 30fps
            l1 = f"{spinner} {filename}"
            l2 = f"{pct:>5.1f}% • {eta_str} • {size} • {fps}"
            return Group(l1, l2)
            
        else: # C: 1 line
            # ● filename  37.9%  03:26
            return f"{spinner} {filename}  {pct:.1f}%  {eta_str}"

    def _render_activity_item(self, job, level: str) -> RenderableType:
        """Render activity feed item."""
        filename = self._sanitize_filename(job.source_file.path.name, max_len=30)
        
        if job.status == JobStatus.COMPLETED:
            icon = "[green]✓[/]"
            in_s = job.source_file.size_bytes
            out_s = job.output_size_bytes
            diff = in_s - out_s
            ratio = (diff / in_s) * 100 if in_s > 0 else 0
            dur = self.format_time(job.duration_seconds)
            
            s_in = self.format_size(in_s)
            s_out = self.format_size(out_s)
            
            if level == "A": # 2 lines
                l1 = f"{icon} {filename}"
                l2 = f"  [green]{s_in}→{s_out} ({ratio:.1f}%) • {dur}[/]"
                return Group(l1, l2)
            else: # B: 1 line
                return f"{icon} {filename}  [green]-{ratio:.1f}%  {dur}[/]"
                
        elif job.status == JobStatus.SKIPPED:
            # Kept original logic usually means ratio check or similar
            icon = "[dim]≡[/]"
            reason = "kept"
            if level == "A":
                return Group(f"{icon} {filename}", f"  [dim]{reason} (below threshold)[/]")
            return f"{icon} {filename}  [dim]{reason}[/]"

        elif job.status == JobStatus.FAILED:
            icon = "[red]✗[/]"
            err = job.error_message or "error"
            if level == "A":
                return Group(f"{icon} {filename}", f"  [red]{err}[/]")
            return f"{icon} {filename}  [red]err[/]"
            
        elif job.status == JobStatus.INTERRUPTED:
             icon = "[red]⚡[/]"
             return f"{icon} {filename} [red]INTERRUPTED[/]"
             
        return f"? {filename}"

    def _render_queue_item(self, file, level: str) -> RenderableType:
        """Render queue item (always 1 line)."""
        filename = self._sanitize_filename(file.path.name, max_len=30)
        size = self.format_size(file.size_bytes)
        fps = self.format_fps(file.metadata)
        return f"[dim]»[/] {filename}  [dim]{size}  {fps}[/]"

    # --- Panel Generators ---

    def _generate_top_bar(self) -> Panel:
        """Status, KPI, Hints."""
        with self.state._lock:
            # L1: Status + Threads
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
            
            paused = "" # Add pause logic if exists in state
            active_threads = len(self.state.active_jobs)
            l1 = f"{indicator} {status} • Threads: {active_threads}/{self.state.current_threads}{paused}"
            
            # L2: KPI
            eta_str = "--:--"
            throughput_str = "0.0 MB/s"
            
            if self.state.processing_start_time and self.state.completed_count > 0:
                elapsed = (datetime.now() - self.state.processing_start_time).total_seconds()
                if elapsed > 0:
                    # ETA
                    total = self.state.files_to_process
                    done = self.state.completed_count + self.state.failed_count
                    rem = total - done
                    if rem > 0 and done > 0:
                        avg = elapsed / done
                        eta_str = self.format_global_eta(avg * rem)
                    
                    # Throughput
                    tp = self.state.total_input_bytes / elapsed
                    throughput_str = f"{tp / 1024 / 1024:.1f} MB/s"
            
            saved = self.format_size(self.state.space_saved_bytes)
            ratio = self.state.compression_ratio
            l2 = f"ETA: {eta_str} • {throughput_str} • {saved} saved ({ratio:.1f}%)"
            
            # L3: Hint
            l3 = "[dim]‹/› threads | S stop | R refresh | C config[/]"
            
            content = f"{l1}\n{l2}\n{l3}"
            
        return Panel(content, border_style="cyan", title="VBC")

    def _generate_progress(self, h_lines: int) -> Panel:
        """Progress bar + counters."""
        with self.state._lock:
            total = self.state.files_to_process
            done = self.state.completed_count
            failed = self.state.failed_count
            skipped = self.state.skipped_count
            
            # Always show Global Bar (Line 1-2)
            pct = 0.0
            if total > 0:
                pct = (done / total) * 100
                
            # Header combined with non-zero stats
            stats = []
            if failed > 0: stats.append(f"[red]Failed: {failed}[/]")
            if skipped > 0: stats.append(f"[yellow]Skipped: {skipped}[/]")
            stats_str = f" • {' • '.join(stats)}" if stats else ""
            
            header = f"Done: {done}/{total} ({pct:.1f}%){stats_str}"
            bar = ProgressBar(total=total, completed=done, width=None)
            
            rows = [header, bar]
            content = Group(*rows)
            
        return Panel(content, title="PROGRESS", border_style="cyan")

    def _generate_active_jobs_panel(self, h_lines: int) -> Panel:
        with self.state._lock:
            jobs = self.state.active_jobs
            levels = [("A", 3), ("B", 2), ("C", 1)]
            table = self._render_list(jobs, h_lines, levels, self._render_active_job)
            return Panel(table, title="ACTIVE JOBS", border_style="cyan")

    def _generate_activity_panel(self, h_lines: int) -> Panel:
        with self.state._lock:
            jobs = list(self.state.recent_jobs) # already sorted roughly
            levels = [("A", 2), ("B", 1)]
            table = self._render_list(jobs, h_lines, levels, self._render_activity_item)
            return Panel(table, title="ACTIVITY FEED", border_style="cyan")

    def _generate_queue_panel(self, h_lines: int) -> Panel:
        with self.state._lock:
            files = list(self.state.pending_files)
            levels = [("A", 1)]
            table = self._render_list(files, h_lines, levels, self._render_queue_item)
            return Panel(table, title="QUEUE", border_style="cyan")
            
    def _generate_footer(self) -> RenderableType:
        with self.state._lock:
            err = self.state.ignored_err_count
            hw = self.state.hw_cap_count
            kept = self.state.min_ratio_skip_count
            small = self.state.ignored_small_count
            
            # Right side: Health counters
            parts = []
            if err > 0: parts.append(f"[red]err:{err}[/]")
            if hw > 0: parts.append(f"[yellow]hw_cap:{hw}[/]")
            if kept > 0: parts.append(f"[dim white]kept:{kept}[/]")
            if small > 0: parts.append(f"[dim white]small:{small}[/]")
            
            health_text = " • ".join(parts) if parts else "[green]Health: OK[/]"
            
            # Left side: Last Action
            action_text = ""
            if self.state.last_action and self.state.last_action_time:
                age = (datetime.now() - self.state.last_action_time).total_seconds()
                if age < 10: # 10s TTL
                    action_text = f"[dim]{self.state.last_action}[/]"

            grid = Table.grid(expand=True)
            grid.add_column(justify="left", ratio=1)
            grid.add_column(justify="right", ratio=1)
            grid.add_row(action_text, health_text)
            
            return grid

    def _generate_config_overlay(self) -> Panel:
        # Same as before
        with self.state._lock:
            lines = self.state.config_lines[:]
            
        def _fmt(line):
            if ": " not in line: return line
            return re.sub(r"(^|[|(]\s*)([^:|()]+):\s+", lambda m: f"{m.group(1)}[grey70]{m.group(2)}:[/] ", line)
            
        content = "\n".join([_fmt(l) for l in lines]) if lines else "No config."
        w = self.console.size.width
        pw = min(max(40, int(w * 0.6)), max(20, w - 4))
        return Panel(content, title="CONFIG", border_style="cyan", width=pw, style="white on black")

    # --- Main Layout Engine ---

    def create_display(self):
        w, h = self.console.size
        
        # 1. Determine fixed heights
        top_h = TOP_BAR_LINES + 2 # +2 for border
        foot_h = FOOTER_LINES 
        
        # Hint logic
        show_hint = h >= 18
        if not show_hint:
            # We need to hack the top bar content if we hide hint, 
            # but for now simpler is just keep Top Bar as is, 
            # or recreate it without line 3.
            # Let's handle it by passing param to _generate_top_bar if needed, 
            # but spec says "Top bar (2-3 lines)". Let's assume Top Bar is elastic based on logic inside.
            pass
            
        fixed_h = top_h + foot_h
        h_work = max(0, h - fixed_h)
        
        # 2. Determine Mode
        is_2col = w >= MIN_2COL_W
        
        # 3. Allocation
        
        # Defaults
        h_progress = 0
        h_active = 0
        h_activity = 0
        h_queue = 0
        
        layout = Layout()
        layout.split_column(
            Layout(name="top", size=top_h),      # Top status bar
            Layout(name="middle"),            # Main content
            Layout(name="bottom", size=foot_h)     # Bottom status
        )
        
        if is_2col:
            # 2 Columns
            layout["middle"].split_row(
                Layout(name="left"),     # Progress + Active Jobs
                Layout(name="right")     # Activity Feed + Queue
            )
            
            # Left: Progress + Active
            # Progress gets min, grows to max if space
            h_progress_frame = min(PROGRESS_MAX + 2, h_work // 3) # Try to fit MAX
            h_progress_frame = PROGRESS_MAX + 2
            if h_progress_frame > h_work: h_progress_frame = h_work
            
            h_active_frame = h_work - h_progress_frame
            if h_active_frame < (ACTIVE_MIN + 2):
                # Shrink progress
                h_progress_frame = max(PROGRESS_MIN + 2, h_work - (ACTIVE_MIN + 2))
                h_active_frame = h_work - h_progress_frame
            
            # Right: Activity + Queue
            # Activity > Queue
            h_activity_frame = h_work // 2
            h_queue_frame = h_work - h_activity_frame
            
            if h_queue_frame < (QUEUE_MIN + 2):
                h_queue_frame = 0 # Hide queue
                h_activity_frame = h_work
            
            # Update Layouts
            layout["left"].split_column(
                Layout(name="progress", size=h_progress_frame),
                Layout(name="active", size=h_active_frame)
            )
            
            right_splits = [Layout(name="activity", size=h_activity_frame)]
            if h_queue_frame > 0:
                right_splits.append(Layout(name="queue", size=h_queue_frame))
            layout["right"].split_column(*right_splits)
            
            # Content Heights (remove 2 for borders)
            h_progress = max(0, h_progress_frame - 2)
            h_active = max(0, h_active_frame - 2)
            h_activity = max(0, h_activity_frame - 2)
            h_queue = max(0, h_queue_frame - 2)

        else:
            # 1 Column (Stack)
            # Progress > Active > Activity > Queue
            h_rem = h_work
            
            h_progress_frame = min(PROGRESS_MAX + 2, h_rem)
            h_rem -= h_progress_frame
            
            h_active_frame = h_rem
            h_activity_frame = 0
            h_queue_frame = 0
            
            # If we have spare space, add activity
            if h_active_frame > 10: # Arbitrary threshold for "enough active space"
                 h_activity_frame = min(h_active_frame // 2, 8)
                 h_active_frame -= h_activity_frame
            
            splits = [
                Layout(name="progress", size=h_progress_frame),
                Layout(name="active", size=h_active_frame)
            ]
            if h_activity_frame > 0:
                splits.append(Layout(name="activity", size=h_activity_frame))
                
            layout["middle"].split_column(*splits)
            
            h_progress = max(0, h_progress_frame - 2)
            h_active = max(0, h_active_frame - 2)
            h_activity = max(0, h_activity_frame - 2)

        # 4. Generate Content
        layout["top"].update(self._generate_top_bar())
        
        # Middle components
        def safe_update(name, content):
            try:
                pass 
            except: pass

        # Assign directly based on tree structure we just built
        if is_2col:
             layout["left"]["progress"].update(self._generate_progress(h_progress))
             layout["left"]["active"].update(self._generate_active_jobs_panel(h_active))
             layout["right"]["activity"].update(self._generate_activity_panel(h_activity))
             if h_queue_frame > 0:
                 layout["right"]["queue"].update(self._generate_queue_panel(h_queue))
        else:
             layout["middle"]["progress"].update(self._generate_progress(h_progress))
             layout["middle"]["active"].update(self._generate_active_jobs_panel(h_active))
             if h_activity_frame > 0:
                 layout["middle"]["activity"].update(self._generate_activity_panel(h_activity))

        # Footer
        layout["bottom"].update(self._generate_footer())

        # Overlays
        if self.state.show_config:
            return _Overlay(layout, self._generate_config_overlay(), overlay_width=80)
        elif self.state.show_info:
             info = Panel(Align.center(self.state.info_message), title="NOTICE", border_style="yellow", width=60)
             return _Overlay(layout, info, overlay_width=60)

        return layout

    def _refresh_loop(self):
        while not self._stop_refresh.is_set():
            if self._live:
                self._spinner_frame = (self._spinner_frame + 1) % 5
                try:
                    display = self.create_display()
                    with self._ui_lock:
                        self._live.update(display)
                except Exception:
                    pass # Resilience
            time.sleep(0.5)

    def start(self):
        self._live = Live(self.create_display(), console=self.console, refresh_per_second=4)
        self._live.start()
        self._stop_refresh.clear()
        self._refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._refresh_thread.start()
        return self

    def stop(self):
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
        return False