"""Active jobs panel widget for VBC Textual Dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ProgressBar, Static

if TYPE_CHECKING:
    from vbc.domain.models import CompressionJob
    from vbc.ui.textual.state_bridge import DashboardState


SPINNER_FRAMES = ["●", "◐", "◓", "◑", "◒"]


def format_bytes(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_duration(seconds: float) -> str:
    """Format seconds to MM:SS or HH:MM:SS."""
    if seconds < 0:
        return "--:--"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def truncate_filename(name: str, max_len: int = 30) -> str:
    """Truncate filename with ellipsis in middle."""
    if len(name) <= max_len:
        return name
    half = (max_len - 1) // 2
    return f"{name[:half]}…{name[-half:]}"


class JobRow(Widget):
    """A single job row in the active jobs panel."""

    DEFAULT_CSS = """
    JobRow {
        height: 3;
        padding: 0 1;
    }

    JobRow .job-line-1 {
        height: 1;
    }

    JobRow .job-line-2 {
        height: 1;
    }

    JobRow .job-line-3 {
        height: 1;
    }
    """

    can_focus = True

    class Selected(Message):
        """Message when job is selected."""

        def __init__(self, job: CompressionJob, index: int) -> None:
            self.job = job
            self.index = index
            super().__init__()

    def __init__(
        self,
        job: CompressionJob,
        index: int,
        start_time: datetime | None = None,
        spinner_offset: int = 0,
    ) -> None:
        super().__init__()
        self.job = job
        self.index = index
        self.start_time = start_time
        self.spinner_offset = spinner_offset
        self._frame_counter = 0

    def compose(self) -> ComposeResult:
        """Compose the job row."""
        with Vertical():
            yield Static(id="job-line-1", classes="job-line-1")
            yield Static(id="job-line-2", classes="job-line-2")
            yield Static(id="job-line-3", classes="job-line-3")

    def on_mount(self) -> None:
        """Initial render."""
        self._update_display()

    def on_click(self) -> None:
        """Handle click - select this job."""
        self.post_message(self.Selected(self.job, self.index))

    def update_job(
        self,
        job: CompressionJob,
        start_time: datetime | None = None,
        frame: int = 0,
    ) -> None:
        """Update the job data and re-render."""
        self.job = job
        self.start_time = start_time
        self._frame_counter = frame
        self._update_display()

    def _update_display(self) -> None:
        """Update the display with current job data."""
        job = self.job

        # Spinner
        spinner_idx = (self._frame_counter + self.spinner_offset) % len(SPINNER_FRAMES)
        spinner = SPINNER_FRAMES[spinner_idx]

        # Filename
        filename = truncate_filename(job.source_file.path.name)

        # Metadata
        metadata_parts = []
        if job.source_file.metadata:
            meta = job.source_file.metadata
            if meta.duration:
                mins = int(meta.duration // 60)
                secs = int(meta.duration % 60)
                metadata_parts.append(f"dur {mins}:{secs:02d}")
            if meta.fps:
                metadata_parts.append(f"{meta.fps:.0f}fps")
        metadata_parts.append(f"in {format_bytes(job.source_file.size_bytes)}")
        metadata = " • ".join(metadata_parts)

        # Progress
        progress = job.progress_percent
        bar_width = 20
        filled = int(progress / 100 * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        # ETA
        eta_str = ""
        if self.start_time and progress > 0:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            if elapsed > 0:
                total_estimated = elapsed / (progress / 100)
                remaining = total_estimated - elapsed
                eta_str = format_duration(remaining)

        # Update lines
        line1 = self.query_one("#job-line-1", Static)
        line2 = self.query_one("#job-line-2", Static)
        line3 = self.query_one("#job-line-3", Static)

        line1.update(f"[spinner]{spinner}[/] [job-filename]{filename}[/]")
        line2.update(f"  [job-metadata]{metadata}[/]")
        line3.update(f"  [job-progress][{bar}] {progress:.1f}%[/] • {eta_str}")


class ActiveJobsPanel(Widget):
    """Panel showing currently active compression jobs."""

    # Reactive properties
    state: reactive[DashboardState | None] = reactive(None)

    DEFAULT_CSS = """
    ActiveJobsPanel {
        height: auto;
        min-height: 5;
        padding: 0 1;
        border: solid #00ffff;
    }

    ActiveJobsPanel #jobs-container {
        height: auto;
        max-height: 20;
    }

    ActiveJobsPanel .no-jobs {
        padding: 1;
    }
    """

    class JobSelected(Message):
        """Message when a job is selected."""

        def __init__(self, job: CompressionJob, index: int) -> None:
            self.job = job
            self.index = index
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._frame = 0

    def compose(self) -> ComposeResult:
        """Compose the active jobs panel."""
        yield VerticalScroll(id="jobs-container")

    def on_mount(self) -> None:
        """Set border title on mount."""
        self.border_title = "ACTIVE JOBS"

    def watch_state(self, state: DashboardState | None) -> None:
        """Update jobs when state changes."""
        if state is None:
            return

        self._frame += 1
        self._update_jobs(state)

    def _update_jobs(self, state: DashboardState) -> None:
        """Update the jobs list."""
        container = self.query_one("#jobs-container", VerticalScroll)

        # Get current job rows
        existing_rows = list(container.query(JobRow))
        active_jobs = state.active_jobs

        if not active_jobs:
            # Show no jobs message
            container.remove_children()
            container.mount(Static("No active jobs", classes="no-jobs"))
            return

        # Remove "no jobs" message if present
        for child in container.query(".no-jobs"):
            child.remove()

        # Update existing rows or add new ones
        for i, job in enumerate(active_jobs):
            start_time = state.job_start_times.get(job.source_file.path.name)
            spinner_offset = hash(job.source_file.path.name) % len(SPINNER_FRAMES)

            if i < len(existing_rows):
                # Update existing row
                existing_rows[i].update_job(job, start_time, self._frame)
            else:
                # Add new row
                row = JobRow(job, i, start_time, spinner_offset)
                container.mount(row)

        # Remove extra rows
        for i in range(len(active_jobs), len(existing_rows)):
            existing_rows[i].remove()

    def on_job_row_selected(self, event: JobRow.Selected) -> None:
        """Handle job row selection."""
        self.post_message(self.JobSelected(event.job, event.index))
