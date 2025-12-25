"""Progress panel widget for VBC Textual Dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ProgressBar, Static

if TYPE_CHECKING:
    from vbc.ui.textual.state_bridge import DashboardState


class ProgressPanel(Widget):
    """Panel showing overall compression progress."""

    DEFAULT_CSS = """
    ProgressPanel {
        height: 4;
        padding: 0 1;
        border: solid #00ffff;
    }

    ProgressPanel ProgressBar {
        padding: 0;
        margin-top: 1;
    }
    """

    # Reactive properties
    state: reactive[DashboardState | None] = reactive(None)

    def compose(self) -> ComposeResult:
        """Compose the progress panel."""
        yield Static(id="progress-header")
        yield ProgressBar(id="progress-bar", total=100, show_eta=False)

    def on_mount(self) -> None:
        """Set border title on mount."""
        self.border_title = "PROGRESS"

    def watch_state(self, state: DashboardState | None) -> None:
        """Update progress when state changes."""
        if state is None:
            return

        header = self.query_one("#progress-header", Static)
        progress_bar = self.query_one("#progress-bar", ProgressBar)

        # Calculate progress
        total = state.files_to_process
        done = (
            state.completed_count
            + state.failed_count
            + state.skipped_count
            + state.min_ratio_skip_count
            + state.hw_cap_count
            + state.interrupted_count
        )

        if total > 0:
            percent = (done / total) * 100
        else:
            percent = 0.0

        # Update header
        header.update(f"PROGRESS │ Done: {done}/{total} ({percent:.1f}%)")

        # Update progress bar
        progress_bar.update(progress=percent)
