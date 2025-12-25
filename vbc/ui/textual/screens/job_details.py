"""Job details modal screen for VBC Textual Dashboard."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from vbc.domain.models import CompressionJob, JobStatus

if TYPE_CHECKING:
    pass


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
    """Format seconds to HH:MM:SS."""
    if seconds < 0:
        return "--:--:--"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class JobDetailsScreen(ModalScreen[int | None]):
    """Modal screen showing detailed information about a job."""

    DEFAULT_CSS = """
    JobDetailsScreen {
        align: center middle;
    }

    JobDetailsScreen #details-container {
        width: 80;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        background: #1a1a2e;
        border: solid #00ffff;
    }

    JobDetailsScreen .details-title {
        text-style: bold;
        text-align: center;
        padding-bottom: 1;
    }

    JobDetailsScreen .detail-row {
        height: 1;
        padding: 0;
    }

    JobDetailsScreen .detail-label {
        width: 18;
    }

    JobDetailsScreen .detail-value {
        width: 1fr;
    }

    JobDetailsScreen .section-title {
        padding-top: 1;
        text-style: bold;
    }

    JobDetailsScreen #ffmpeg-container {
        height: auto;
        max-height: 10;
        padding: 1;
        margin-top: 1;
        overflow-y: auto;
        background: #12121f;
        border: solid #444;
    }

    JobDetailsScreen .ffmpeg-command {
    }

    JobDetailsScreen #button-row {
        height: 3;
        align: center middle;
        padding-top: 1;
    }

    JobDetailsScreen Button {
        margin: 0 1;
    }

    JobDetailsScreen .nav-counter {
        width: auto;
        padding: 0 2;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("left", "previous", "Previous"),
        ("right", "next", "Next"),
    ]

    def __init__(
        self,
        jobs: list[CompressionJob],
        initial_index: int = 0,
        job_start_times: dict[str, datetime] | None = None,
    ) -> None:
        super().__init__()
        self.jobs = jobs
        self.current_index = min(initial_index, len(jobs) - 1)
        self.job_start_times = job_start_times or {}

    def compose(self) -> ComposeResult:
        """Compose the job details modal."""
        with Container(id="details-container"):
            yield Static("JOB DETAILS", classes="details-title")

            with VerticalScroll(id="details-scroll"):
                # File info section
                yield Static("File Information", classes="section-title")
                with Horizontal(classes="detail-row"):
                    yield Static("Path:", classes="detail-label")
                    yield Static(id="detail-path", classes="detail-value")
                with Horizontal(classes="detail-row"):
                    yield Static("Filename:", classes="detail-label")
                    yield Static(id="detail-filename", classes="detail-value")
                with Horizontal(classes="detail-row"):
                    yield Static("Status:", classes="detail-label")
                    yield Static(id="detail-status", classes="detail-value")
                with Horizontal(classes="detail-row"):
                    yield Static("Size:", classes="detail-label")
                    yield Static(id="detail-size", classes="detail-value")

                # Metadata section
                yield Static("Video Metadata", classes="section-title")
                with Horizontal(classes="detail-row"):
                    yield Static("Resolution:", classes="detail-label")
                    yield Static(id="detail-resolution", classes="detail-value")
                with Horizontal(classes="detail-row"):
                    yield Static("FPS:", classes="detail-label")
                    yield Static(id="detail-fps", classes="detail-value")
                with Horizontal(classes="detail-row"):
                    yield Static("Duration:", classes="detail-label")
                    yield Static(id="detail-duration", classes="detail-value")
                with Horizontal(classes="detail-row"):
                    yield Static("Codec:", classes="detail-label")
                    yield Static(id="detail-codec", classes="detail-value")
                with Horizontal(classes="detail-row"):
                    yield Static("Camera:", classes="detail-label")
                    yield Static(id="detail-camera", classes="detail-value")
                with Horizontal(classes="detail-row"):
                    yield Static("Color Space:", classes="detail-label")
                    yield Static(id="detail-colorspace", classes="detail-value")

                # Processing section
                yield Static("Processing", classes="section-title")
                with Horizontal(classes="detail-row"):
                    yield Static("Progress:", classes="detail-label")
                    yield Static(id="detail-progress", classes="detail-value")
                with Horizontal(classes="detail-row"):
                    yield Static("Processing Time:", classes="detail-label")
                    yield Static(id="detail-time", classes="detail-value")
                with Horizontal(classes="detail-row"):
                    yield Static("Rotation:", classes="detail-label")
                    yield Static(id="detail-rotation", classes="detail-value")

                # Error section (if applicable)
                with Horizontal(classes="detail-row"):
                    yield Static("Error:", classes="detail-label")
                    yield Static(id="detail-error", classes="detail-value")

                # FFmpeg command section
                yield Static("FFmpeg Command", classes="section-title")
                with Container(id="ffmpeg-container"):
                    yield Static(id="ffmpeg-command", classes="ffmpeg-command")

            # Navigation buttons
            with Horizontal(id="button-row"):
                yield Button("< Prev", id="btn-prev", variant="default")
                yield Static(id="nav-counter", classes="nav-counter")
                yield Button("Close", id="btn-close", variant="primary")
                yield Button("Next >", id="btn-next", variant="default")

    def on_mount(self) -> None:
        """Initial display."""
        self._update_display()

    def _update_display(self) -> None:
        """Update the display with current job data."""
        if not self.jobs:
            return

        job = self.jobs[self.current_index]

        # Update navigation counter
        counter = self.query_one("#nav-counter", Static)
        counter.update(f"{self.current_index + 1} / {len(self.jobs)}")

        # Update button states
        prev_btn = self.query_one("#btn-prev", Button)
        next_btn = self.query_one("#btn-next", Button)
        prev_btn.disabled = self.current_index == 0
        next_btn.disabled = self.current_index >= len(self.jobs) - 1

        # File info
        self.query_one("#detail-path", Static).update(str(job.source_file.path.parent))
        self.query_one("#detail-filename", Static).update(job.source_file.path.name)

        # Status with color
        status_colors = {
            JobStatus.PENDING: "dim",
            JobStatus.PROCESSING: "primary",
            JobStatus.COMPLETED: "green",
            JobStatus.FAILED: "red",
            JobStatus.SKIPPED: "yellow",
            JobStatus.HW_CAP_LIMIT: "yellow",
            JobStatus.INTERRUPTED: "red",
        }
        status_color = status_colors.get(job.status, "white")
        self.query_one("#detail-status", Static).update(f"[{status_color}]{job.status.value}[/]")

        # Size
        input_size = format_bytes(job.source_file.size_bytes)
        if job.output_size_bytes:
            output_size = format_bytes(job.output_size_bytes)
            ratio = (1 - job.output_size_bytes / job.source_file.size_bytes) * 100
            size_str = f"{input_size} → {output_size} ([green]{ratio:.1f}% saved[/])"
        else:
            size_str = input_size
        self.query_one("#detail-size", Static).update(size_str)

        # Metadata
        meta = job.source_file.metadata
        if meta:
            if meta.width and meta.height:
                self.query_one("#detail-resolution", Static).update(
                    f"{meta.width}x{meta.height}"
                )
            else:
                self.query_one("#detail-resolution", Static).update("-")

            if meta.fps:
                self.query_one("#detail-fps", Static).update(f"{meta.fps:.2f}")
            else:
                self.query_one("#detail-fps", Static).update("-")

            if meta.duration:
                self.query_one("#detail-duration", Static).update(
                    format_duration(meta.duration)
                )
            else:
                self.query_one("#detail-duration", Static).update("-")

            self.query_one("#detail-codec", Static).update(meta.codec or "-")
            self.query_one("#detail-camera", Static).update(meta.camera_model or "-")
            self.query_one("#detail-colorspace", Static).update(meta.color_space or "-")
        else:
            for field in ["resolution", "fps", "duration", "codec", "camera", "colorspace"]:
                self.query_one(f"#detail-{field}", Static).update("-")

        # Processing info
        self.query_one("#detail-progress", Static).update(f"{job.progress_percent:.1f}%")

        # Processing time
        if job.duration_seconds:
            self.query_one("#detail-time", Static).update(
                format_duration(job.duration_seconds)
            )
        else:
            # Try to calculate from start time
            start_time = self.job_start_times.get(job.source_file.path.name)
            if start_time:
                elapsed = (datetime.now() - start_time).total_seconds()
                self.query_one("#detail-time", Static).update(
                    f"{format_duration(elapsed)} (in progress)"
                )
            else:
                self.query_one("#detail-time", Static).update("-")

        # Rotation
        if job.rotation_angle:
            self.query_one("#detail-rotation", Static).update(f"{job.rotation_angle}°")
        else:
            self.query_one("#detail-rotation", Static).update("None")

        # Error
        if job.error_message:
            self.query_one("#detail-error", Static).update(f"[red]{job.error_message}[/]")
        else:
            self.query_one("#detail-error", Static).update("-")

        # FFmpeg command (placeholder - would need to store actual command)
        ffmpeg = self.query_one("#ffmpeg-command", Static)
        ffmpeg.update(
            f"ffmpeg -i \"{job.source_file.path}\" "
            f"-c:v av1_nvenc -cq 45 "
            f"-c:a copy "
            f"\"{job.output_path or 'output.mp4'}\""
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-prev":
            self.action_previous()
        elif event.button.id == "btn-next":
            self.action_next()
        elif event.button.id == "btn-close":
            self.action_close()

    def action_previous(self) -> None:
        """Go to previous job."""
        if self.current_index > 0:
            self.current_index -= 1
            self._update_display()

    def action_next(self) -> None:
        """Go to next job."""
        if self.current_index < len(self.jobs) - 1:
            self.current_index += 1
            self._update_display()

    def action_close(self) -> None:
        """Close the modal and return current index."""
        self.dismiss(self.current_index)
