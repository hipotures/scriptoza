"""GPU sparkline widget for VBC Textual Dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from vbc.ui.textual.state_bridge import DashboardState


# Sparkline block characters (8 levels)
BLOCKS = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
MISSING_MARKER = "·"

# Metric definitions
METRICS = [
    {"name": "Temperature", "key": "temp", "unit": "°C", "min": 35, "max": 70},
    {"name": "Fan Speed", "key": "fan", "unit": "%", "min": 0, "max": 100},
    {"name": "Power Draw", "key": "pwr", "unit": "W", "min": 100, "max": 400},
    {"name": "GPU Util", "key": "gpu", "unit": "%", "min": 0, "max": 100},
    {"name": "Memory Util", "key": "mem", "unit": "%", "min": 0, "max": 100},
]


def value_to_block(value: float | None, min_val: float, max_val: float) -> tuple[str, str]:
    """Convert a value to a block character with color class.

    Returns:
        Tuple of (block_char, color_class)
    """
    if value is None:
        return MISSING_MARKER, "sparkline-cool"

    # Clamp to range
    clamped = max(min_val, min(max_val, value))

    # Normalize to 0-1
    if max_val > min_val:
        normalized = (clamped - min_val) / (max_val - min_val)
    else:
        normalized = 0.5

    # Map to block index (0-7)
    block_idx = int(normalized * 7)
    block_idx = max(0, min(7, block_idx))

    # Determine color based on value position
    if normalized < 0.4:
        color = "sparkline-cool"
    elif normalized < 0.7:
        color = "sparkline-warm"
    else:
        color = "sparkline-hot"

    return BLOCKS[block_idx], color


class GPUSparkline(Widget):
    """GPU metrics sparkline visualization widget."""

    DEFAULT_CSS = """
    GPUSparkline {
        height: 4;
        padding: 0 1;
        border: solid #00ffff;
    }

    GPUSparkline .metric-header {
        height: 1;
    }

    GPUSparkline .metric-label {
        text-style: bold;
    }

    GPUSparkline .metric-value {
    }

    GPUSparkline .sparkline-container {
        height: 2;
    }

    GPUSparkline .sparkline {
        height: 1;
    }

    GPUSparkline .sparkline-cool {
    }

    GPUSparkline .sparkline-warm {
    }

    GPUSparkline .sparkline-hot {
    }

    GPUSparkline .no-gpu {
        padding: 1;
    }
    """

    # Reactive properties
    state: reactive[DashboardState | None] = reactive(None)

    def compose(self) -> ComposeResult:
        """Compose the sparkline widget."""
        yield Static(id="metric-header", classes="metric-header")
        yield Static(id="sparkline", classes="sparkline")
        yield Static(id="sparkline-scale", classes="sparkline")

    def on_mount(self) -> None:
        """Set border title on mount."""
        self.border_title = "GPU METRICS"

    def watch_state(self, state: DashboardState | None) -> None:
        """Update sparkline when state changes."""
        if state is None:
            return

        self._update_display(state)

    def _update_display(self, state: DashboardState) -> None:
        """Update the sparkline display."""
        header = self.query_one("#metric-header", Static)
        sparkline = self.query_one("#sparkline", Static)
        scale = self.query_one("#sparkline-scale", Static)

        if not state.gpu_data:
            header.update("[no-gpu]No GPU data available[/]")
            sparkline.update("")
            scale.update("")
            return

        # Get current metric
        metric_idx = state.gpu_sparkline_metric_idx
        metric = METRICS[metric_idx]

        # Get history for this metric
        history_map = {
            "temp": state.gpu_history_temp,
            "fan": state.gpu_history_fan,
            "pwr": state.gpu_history_pwr,
            "gpu": state.gpu_history_gpu,
            "mem": state.gpu_history_mem,
        }
        history = history_map.get(metric["key"], [])

        # Get current value (nvtop keys)
        value_map = {
            "temp": state.gpu_data.get("temp", 0),
            "fan": state.gpu_data.get("fan_speed", 0),
            "pwr": state.gpu_data.get("power_draw", 0),
            "gpu": state.gpu_data.get("gpu_util", 0),
            "mem": state.gpu_data.get("mem_util", 0),
        }
        current_value = value_map.get(metric["key"], 0)

        # Update header
        header.update(
            f"[metric-label]{metric['name']}[/]: "
            f"[metric-value]{current_value}{metric['unit']}[/] "
            f"[dim](press G to rotate)[/]"
        )

        # Build sparkline
        min_val = metric["min"]
        max_val = metric["max"]

        sparkline_chars = []
        for value in history:
            block, color = value_to_block(value, min_val, max_val)
            sparkline_chars.append(f"[{color}]{block}[/]")

        # Pad to 60 chars if needed
        while len(sparkline_chars) < 60:
            sparkline_chars.insert(0, f"[sparkline-cool]{MISSING_MARKER}[/]")

        # Only show last 60
        sparkline_chars = sparkline_chars[-60:]

        sparkline.update("".join(sparkline_chars))

        # Scale indicators
        scale.update(
            f"[dim]{min_val}{metric['unit']}[/]"
            + " " * 50
            + f"[dim]{max_val}{metric['unit']}[/]"
        )
