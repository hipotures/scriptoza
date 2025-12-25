"""Header widget for VBC Textual Dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
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


def format_duration(seconds: float) -> str:
    """Format seconds to HH:MM:SS or MM:SS."""
    if seconds < 0:
        return "--:--"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class HeaderWidget(Widget):
    """Top bar widget showing status, threads, ETA, throughput, and GPU info."""

    DEFAULT_CSS = """
    HeaderWidget {
        height: 3;
        padding: 0 1;
        border: solid #00ffff;
        overflow: hidden;
    }

    HeaderWidget Horizontal {
        height: 100%;
        align: center middle;
        overflow: hidden;
    }

    HeaderWidget .status-section {
        width: 1fr;
    }

    HeaderWidget .gpu-section {
        width: auto;
    }

    HeaderWidget .status-active {
    }

    HeaderWidget .status-shutdown {
    }

    HeaderWidget .status-interrupt {
    }
    """

    # Reactive properties
    state: reactive[DashboardState | None] = reactive(None)

    def compose(self) -> ComposeResult:
        """Compose the header layout."""
        with Horizontal():
            yield Static(id="status-section", classes="status-section")
            yield Static(id="gpu-section", classes="gpu-section")

    def watch_state(self, state: DashboardState | None) -> None:
        """Update header when state changes."""
        if state is None:
            return

        self._update_status_section(state)
        self._update_gpu_section(state)

    def _update_status_section(self, state: DashboardState) -> None:
        """Update the status section."""
        status_widget = self.query_one("#status-section", Static)

        # Status indicator
        indicator = state.status_indicator
        status_class = state.status_class

        # Thread info
        threads = state.current_threads

        # Calculate ETA
        eta_str = self._calculate_eta(state)

        # Throughput (bytes/sec)
        throughput_str = self._calculate_throughput(state)

        # Space saved
        saved = format_bytes(state.space_saved_bytes)

        # Build status line
        parts = [
            f"[{status_class}]{indicator}[/]",
            f"Threads: {threads}",
        ]

        if eta_str:
            parts.append(f"ETA: {eta_str}")

        if throughput_str:
            parts.append(throughput_str)

        parts.append(f"Saved: {saved}")

        status_widget.update(" │ ".join(parts))

    def _update_gpu_section(self, state: DashboardState) -> None:
        """Update the GPU metrics section."""
        gpu_widget = self.query_one("#gpu-section", Static)

        if not state.gpu_data:
            gpu_widget.update("")
            return

        gpu = state.gpu_data

        # Get values with defaults (nvtop keys)
        temp = gpu.get("temp", 0)
        fan = gpu.get("fan_speed", 0)
        power = gpu.get("power_draw", 0)
        gpu_util = gpu.get("gpu_util", 0)
        mem_util = gpu.get("mem_util", 0)
        device = gpu.get("device_name", "GPU")

        # Temperature color
        if temp < 50:
            temp_color = "sparkline-cool"
        elif temp < 70:
            temp_color = "sparkline-warm"
        else:
            temp_color = "sparkline-hot"

        # Highlight current metric
        metric_idx = state.gpu_sparkline_metric_idx
        metrics = [
            (f"[{temp_color}]{int(temp)}°C[/]", 0),
            (f"fan {int(fan)}%%", 1),
            (f"pwr {int(power)}W", 2),
            (f"gpu {int(gpu_util)}%%", 3),
            (f"mem {int(mem_util)}%%", 4),
        ]

        metric_strs = []
        for metric_str, idx in metrics:
            if idx == metric_idx:
                metric_strs.append(f"[bold reverse]{metric_str}[/]")
            else:
                metric_strs.append(metric_str)

        # Skróć nazwę GPU dla oszczędności miejsca
        short_device = device.replace("NVIDIA GeForce ", "").replace("GeForce ", "")
        gpu_widget.update(f"{short_device} │ {' │ '.join(metric_strs)}")

    def _calculate_eta(self, state: DashboardState) -> str:
        """Calculate estimated time remaining."""
        if not state.processing_start_time:
            return ""

        total = state.files_to_process
        if total == 0:
            return ""

        done = (
            state.completed_count
            + state.failed_count
            + state.skipped_count
            + state.min_ratio_skip_count
            + state.hw_cap_count
            + state.interrupted_count
        )

        if done == 0:
            return ""

        elapsed = (datetime.now() - state.processing_start_time).total_seconds()
        if elapsed < 1:
            return ""

        avg_time_per_job = elapsed / done
        remaining = total - done
        eta_seconds = avg_time_per_job * remaining

        return format_duration(eta_seconds)

    def _calculate_throughput(self, state: DashboardState) -> str:
        """Calculate throughput in bytes/second."""
        if not state.processing_start_time:
            return ""

        elapsed = (datetime.now() - state.processing_start_time).total_seconds()
        if elapsed < 1:
            return ""

        total_bytes = state.total_input_bytes
        if total_bytes == 0:
            return ""

        bytes_per_sec = total_bytes / elapsed
        return f"{format_bytes(int(bytes_per_sec))}/s"
