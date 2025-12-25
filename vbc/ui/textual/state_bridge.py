"""Bridge between UIState (thread-safe) and Textual reactive system."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vbc.domain.models import CompressionJob, JobStatus

if TYPE_CHECKING:
    from vbc.ui.state import UIState


@dataclass
class StatsCategory:
    """Represents a category of files for the stats browser."""

    name: str
    label: str
    count: int = 0
    files: list[tuple[Path, int, str]] = field(default_factory=list)  # (path, size, reason)


@dataclass
class DashboardState:
    """Snapshot of UI state for Textual components.

    This is a non-thread-safe copy of UIState data that Textual components
    can safely read without locking.
    """

    # Counters
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    hw_cap_count: int = 0
    cam_skipped_count: int = 0
    min_ratio_skip_count: int = 0
    interrupted_count: int = 0

    # Discovery counters
    files_to_process: int = 0
    already_compressed_count: int = 0
    ignored_small_count: int = 0
    ignored_err_count: int = 0
    ignored_av1_count: int = 0

    # Bytes tracking
    total_input_bytes: int = 0
    total_output_bytes: int = 0
    space_saved_bytes: int = 0
    compression_ratio: float = 0.0

    # Job lists (copies, not references)
    active_jobs: list[CompressionJob] = field(default_factory=list)
    recent_jobs: list[CompressionJob] = field(default_factory=list)
    pending_files: list[Any] = field(default_factory=list)

    # Job timing
    job_start_times: dict[str, datetime] = field(default_factory=dict)

    # Global status
    discovery_finished: bool = False
    discovery_finished_time: datetime | None = None
    total_files_found: int = 0
    current_threads: int = 0
    shutdown_requested: bool = False
    interrupt_requested: bool = False
    finished: bool = False
    strip_unicode_display: bool = True
    processing_start_time: datetime | None = None

    # Overlay states
    show_config: bool = False
    show_legend: bool = False
    show_menu: bool = False
    config_lines: list[str] = field(default_factory=list)

    # Action message
    last_action: str = ""
    last_action_time: datetime | None = None

    # GPU metrics
    gpu_data: dict[str, Any] | None = None
    gpu_sparkline_metric_idx: int = 0
    gpu_history_temp: list[float] = field(default_factory=list)
    gpu_history_pwr: list[float] = field(default_factory=list)
    gpu_history_gpu: list[float] = field(default_factory=list)
    gpu_history_mem: list[float] = field(default_factory=list)
    gpu_history_fan: list[float] = field(default_factory=list)

    # Stats browser data (NEW for Textual dashboard)
    stats_categories: dict[str, StatsCategory] = field(default_factory=dict)

    @property
    def progress_percent(self) -> float:
        """Calculate overall progress percentage."""
        total = self.files_to_process
        if total == 0:
            return 0.0
        done = self.completed_count + self.failed_count + self.skipped_count
        done += self.min_ratio_skip_count + self.hw_cap_count + self.interrupted_count
        return min(100.0, (done / total) * 100)

    @property
    def status_indicator(self) -> str:
        """Get status indicator symbol."""
        if self.interrupt_requested:
            return "!"
        elif self.shutdown_requested:
            return "◐"
        else:
            return "●"

    @property
    def status_class(self) -> str:
        """Get CSS class for status indicator."""
        if self.interrupt_requested:
            return "status-interrupt"
        elif self.shutdown_requested:
            return "status-shutdown"
        else:
            return "status-active"


class StateBridge:
    """Bridges UIState (thread-safe) to Textual-friendly DashboardState.

    This class periodically copies data from UIState to a DashboardState
    snapshot that Textual components can safely access.
    """

    def __init__(self, ui_state: UIState):
        self.ui_state = ui_state
        self._state = DashboardState()

        # Extended tracking for stats browser (not in original UIState)
        self._ignored_small_files: list[tuple[Path, int, str]] = []
        self._ignored_err_files: list[tuple[Path, int, str]] = []
        self._failed_jobs: list[tuple[Path, int, str]] = []
        self._kept_jobs: list[tuple[Path, int, str]] = []
        self._av1_files: list[tuple[Path, int, str]] = []
        self._cam_skipped_files: list[tuple[Path, int, str]] = []
        self._hw_cap_files: list[tuple[Path, int, str]] = []

    @property
    def state(self) -> DashboardState:
        """Get the current state snapshot."""
        return self._state

    def sync(self) -> DashboardState:
        """Synchronize state from UIState to DashboardState.

        This should be called periodically (e.g., 4Hz) from Textual's event loop.
        """
        with self.ui_state._lock:
            self._state = DashboardState(
                # Counters
                completed_count=self.ui_state.completed_count,
                failed_count=self.ui_state.failed_count,
                skipped_count=self.ui_state.skipped_count,
                hw_cap_count=self.ui_state.hw_cap_count,
                cam_skipped_count=self.ui_state.cam_skipped_count,
                min_ratio_skip_count=self.ui_state.min_ratio_skip_count,
                interrupted_count=self.ui_state.interrupted_count,
                # Discovery counters
                files_to_process=self.ui_state.files_to_process,
                already_compressed_count=self.ui_state.already_compressed_count,
                ignored_small_count=self.ui_state.ignored_small_count,
                ignored_err_count=self.ui_state.ignored_err_count,
                ignored_av1_count=self.ui_state.ignored_av1_count,
                # Bytes
                total_input_bytes=self.ui_state.total_input_bytes,
                total_output_bytes=self.ui_state.total_output_bytes,
                space_saved_bytes=self.ui_state.space_saved_bytes,
                compression_ratio=self.ui_state.compression_ratio,
                # Job lists (deep copy to avoid threading issues)
                active_jobs=list(self.ui_state.active_jobs),
                recent_jobs=list(self.ui_state.recent_jobs),
                pending_files=list(self.ui_state.pending_files),
                # Job timing
                job_start_times=dict(self.ui_state.job_start_times),
                # Global status
                discovery_finished=self.ui_state.discovery_finished,
                discovery_finished_time=self.ui_state.discovery_finished_time,
                total_files_found=self.ui_state.total_files_found,
                current_threads=self.ui_state.current_threads,
                shutdown_requested=self.ui_state.shutdown_requested,
                interrupt_requested=self.ui_state.interrupt_requested,
                finished=self.ui_state.finished,
                strip_unicode_display=self.ui_state.strip_unicode_display,
                processing_start_time=self.ui_state.processing_start_time,
                # Overlays
                show_config=self.ui_state.show_config,
                show_legend=self.ui_state.show_legend,
                show_menu=self.ui_state.show_menu,
                config_lines=list(self.ui_state.config_lines),
                # Action message
                last_action=self.ui_state.get_last_action(),
                last_action_time=self.ui_state.last_action_time,
                # GPU
                gpu_data=dict(self.ui_state.gpu_data) if self.ui_state.gpu_data else None,
                gpu_sparkline_metric_idx=self.ui_state.gpu_sparkline_metric_idx,
                gpu_history_temp=list(self.ui_state.gpu_history_temp),
                gpu_history_pwr=list(self.ui_state.gpu_history_pwr),
                gpu_history_gpu=list(self.ui_state.gpu_history_gpu),
                gpu_history_mem=list(self.ui_state.gpu_history_mem),
                gpu_history_fan=list(self.ui_state.gpu_history_fan),
                # Stats categories
                stats_categories=self._build_stats_categories(),
            )
        return self._state

    def _build_stats_categories(self) -> dict[str, StatsCategory]:
        """Build stats categories from current state."""
        return {
            "fail": StatsCategory(
                name="fail",
                label="Failed",
                count=self.ui_state.failed_count,
                files=self._failed_jobs.copy(),
            ),
            "err": StatsCategory(
                name="err",
                label="Error Files",
                count=self.ui_state.ignored_err_count,
                files=self._ignored_err_files.copy(),
            ),
            "hw_cap": StatsCategory(
                name="hw_cap",
                label="HW Capability",
                count=self.ui_state.hw_cap_count,
                files=self._hw_cap_files.copy(),
            ),
            "skip": StatsCategory(
                name="skip",
                label="Skipped",
                count=self.ui_state.skipped_count,
                files=[],
            ),
            "kept": StatsCategory(
                name="kept",
                label="Kept Original",
                count=self.ui_state.min_ratio_skip_count,
                files=self._kept_jobs.copy(),
            ),
            "small": StatsCategory(
                name="small",
                label="Too Small",
                count=self.ui_state.ignored_small_count,
                files=self._ignored_small_files.copy(),
            ),
            "av1": StatsCategory(
                name="av1",
                label="Already AV1",
                count=self.ui_state.ignored_av1_count,
                files=self._av1_files.copy(),
            ),
            "cam": StatsCategory(
                name="cam",
                label="Camera Filter",
                count=self.ui_state.cam_skipped_count,
                files=self._cam_skipped_files.copy(),
            ),
        }

    # Methods to track files for stats browser
    def add_ignored_small(self, path: Path, size: int):
        """Track a file that was ignored due to size."""
        self._ignored_small_files.append((path, size, "Below minimum size"))

    def add_ignored_err(self, path: Path, size: int = 0):
        """Track a file with existing .err marker."""
        self._ignored_err_files.append((path, size, "Previous error"))

    def add_failed_job(self, path: Path, size: int, error: str):
        """Track a failed job."""
        self._failed_jobs.append((path, size, error))

    def add_kept_job(self, path: Path, size: int):
        """Track a job where original was kept."""
        self._kept_jobs.append((path, size, "Compression ratio too low"))

    def add_av1_file(self, path: Path, size: int):
        """Track an already-AV1 file."""
        self._av1_files.append((path, size, "Already AV1 encoded"))

    def add_cam_skipped(self, path: Path, size: int, camera: str):
        """Track a camera-filtered file."""
        self._cam_skipped_files.append((path, size, f"Camera: {camera}"))

    def add_hw_cap_file(self, path: Path, size: int):
        """Track a hardware capability exceeded file."""
        self._hw_cap_files.append((path, size, "Hardware limit exceeded"))
