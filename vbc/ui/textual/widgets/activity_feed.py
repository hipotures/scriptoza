"""Activity feed widget for VBC Textual Dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from vbc.domain.models import JobStatus

if TYPE_CHECKING:
    from vbc.domain.models import CompressionJob
    from vbc.ui.textual.state_bridge import DashboardState


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


def truncate_filename(name: str, max_len: int = 25) -> str:
    """Truncate filename with ellipsis in middle."""
    if len(name) <= max_len:
        return name
    half = (max_len - 1) // 2
    return f"{name[:half]}…{name[-half:]}"


class ActivityRow(Widget):
    """A single row in the activity feed."""

    DEFAULT_CSS = """
    ActivityRow {
        height: 2;
        padding: 0 1;
    }

    ActivityRow .activity-line-1 {
        height: 1;
    }

    ActivityRow .activity-line-2 {
        height: 1;
    }
    """

    def __init__(self, job: CompressionJob) -> None:
        super().__init__()
        self.job = job

    def compose(self) -> ComposeResult:
        """Compose the activity row."""
        yield Static(id="activity-line-1", classes="activity-line-1")
        yield Static(id="activity-line-2", classes="activity-line-2")

    def on_mount(self) -> None:
        """Initial render."""
        self._update_display()

    def update_job(self, job: CompressionJob) -> None:
        """Update the job data."""
        self.job = job
        self._update_display()

    def _update_display(self) -> None:
        """Update the display."""
        job = self.job
        line1 = self.query_one("#activity-line-1", Static)
        line2 = self.query_one("#activity-line-2", Static)

        filename = truncate_filename(job.source_file.path.name)

        # Determine status icon and details
        if job.status == JobStatus.COMPLETED:
            icon = "[status-success]✓[/]"
            input_size = format_bytes(job.source_file.size_bytes)
            output_size = format_bytes(job.output_size_bytes or 0)
            if job.source_file.size_bytes > 0 and job.output_size_bytes:
                ratio = (1 - job.output_size_bytes / job.source_file.size_bytes) * 100
                details = f"{input_size} → {output_size} ({ratio:.1f}%)"
            else:
                details = f"{input_size} → {output_size}"
        elif job.status == JobStatus.FAILED:
            icon = "[status-error]✗[/]"
            details = job.error_message or "Unknown error"
        elif job.status == JobStatus.SKIPPED:
            icon = "[status-kept]≡[/]"
            details = "kept (below threshold)"
        elif job.status == JobStatus.INTERRUPTED:
            icon = "[status-interrupted]⚡[/]"
            details = "INTERRUPTED"
        elif job.status == JobStatus.HW_CAP_LIMIT:
            icon = "[status-error]⚠[/]"
            details = "Hardware capability exceeded"
        else:
            icon = "[status-kept]○[/]"
            details = str(job.status)

        # Format duration if available
        duration_str = ""
        if job.duration_seconds:
            mins = int(job.duration_seconds // 60)
            secs = int(job.duration_seconds % 60)
            duration_str = f" • {mins}:{secs:02d}"

        line1.update(f"{icon} {filename}")
        line2.update(f"  {details}{duration_str}")


class ActivityFeed(Widget):
    """Panel showing recently completed jobs."""

    DEFAULT_CSS = """
    ActivityFeed {
        height: auto;
        min-height: 5;
        padding: 0 1;
        border: solid #00ffff;
    }

    ActivityFeed #activity-container {
        height: auto;
        max-height: 15;
    }

    ActivityFeed .no-activity {
        padding: 1;
    }
    """

    # Reactive properties
    state: reactive[DashboardState | None] = reactive(None)

    def compose(self) -> ComposeResult:
        """Compose the activity feed panel."""
        yield VerticalScroll(id="activity-container")

    def on_mount(self) -> None:
        """Set border title on mount."""
        self.border_title = "ACTIVITY FEED"

    def watch_state(self, state: DashboardState | None) -> None:
        """Update activity when state changes."""
        if state is None:
            return

        self._update_activity(state)

    def _update_activity(self, state: DashboardState) -> None:
        """Update the activity list."""
        container = self.query_one("#activity-container", VerticalScroll)
        recent_jobs = state.recent_jobs

        if not recent_jobs:
            container.remove_children()
            container.mount(Static("No completed jobs yet", classes="no-activity"))
            return

        # Remove "no activity" message if present
        for child in container.query(".no-activity"):
            child.remove()

        # Get current rows
        existing_rows = list(container.query(ActivityRow))

        # Update existing rows or add new ones
        for i, job in enumerate(recent_jobs):
            if i < len(existing_rows):
                existing_rows[i].update_job(job)
            else:
                row = ActivityRow(job)
                container.mount(row)

        # Remove extra rows
        for i in range(len(recent_jobs), len(existing_rows)):
            existing_rows[i].remove()
