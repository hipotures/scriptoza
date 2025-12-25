"""Health footer widget for VBC Textual Dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from vbc.ui.textual.state_bridge import DashboardState


class HealthCounter(Widget):
    """A single health counter that can be clicked."""

    DEFAULT_CSS = """
    HealthCounter {
        width: auto;
        height: 1;
        padding: 0 1;
    }

    HealthCounter:hover {
    }

    HealthCounter .counter-label {
        width: auto;
    }
    """

    can_focus = True

    class Clicked(Message):
        """Message when counter is clicked."""

        def __init__(self, category: str, count: int) -> None:
            self.category = category
            self.count = count
            super().__init__()

    def __init__(
        self,
        category: str,
        label: str,
        count: int,
        css_class: str,
    ) -> None:
        super().__init__()
        self.category = category
        self.label = label
        self.count = count
        self.css_class = css_class

    def compose(self) -> ComposeResult:
        """Compose the counter."""
        yield Static(id="counter-label", classes="counter-label")

    def on_mount(self) -> None:
        """Initial render."""
        self._update_display()

    def update_count(self, count: int) -> None:
        """Update the count."""
        self.count = count
        self._update_display()

    def _update_display(self) -> None:
        """Update the display."""
        label_widget = self.query_one("#counter-label", Static)
        if self.count > 0:
            label_widget.update(f"[{self.css_class}]{self.label}:{self.count}[/]")
        else:
            label_widget.update(f"[dim]{self.label}:0[/]")

    def on_click(self) -> None:
        """Handle click."""
        if self.count > 0:
            self.post_message(self.Clicked(self.category, self.count))


class HealthFooter(Widget):
    """Footer showing health counters that can be clicked to view details."""

    DEFAULT_CSS = """
    HealthFooter {
        dock: bottom;
        height: 1;
        padding: 0 1;
    }

    HealthFooter Horizontal {
        height: 100%;
        align: left middle;
    }

    HealthFooter .separator {
        width: auto;
        padding: 0 1;
    }

    HealthFooter .action-message {
        width: 1fr;
        text-align: right;
    }
    """

    # Reactive properties
    state: reactive[DashboardState | None] = reactive(None)

    class CategoryClicked(Message):
        """Message when a category is clicked."""

        def __init__(self, category: str) -> None:
            self.category = category
            super().__init__()

    def compose(self) -> ComposeResult:
        """Compose the health footer."""
        with Horizontal():
            yield HealthCounter("fail", "fail", 0, "health-fail")
            yield Static("•", classes="separator")
            yield HealthCounter("err", "err", 0, "health-fail")
            yield Static("•", classes="separator")
            yield HealthCounter("hw_cap", "hw_cap", 0, "health-warning")
            yield Static("•", classes="separator")
            yield HealthCounter("skip", "skip", 0, "health-warning")
            yield Static("•", classes="separator")
            yield HealthCounter("kept", "kept", 0, "health-dim")
            yield Static("•", classes="separator")
            yield HealthCounter("small", "small", 0, "health-dim")
            yield Static("•", classes="separator")
            yield HealthCounter("av1", "av1", 0, "health-dim")
            yield Static("•", classes="separator")
            yield HealthCounter("cam", "cam", 0, "health-dim")
            yield Static(id="action-message", classes="action-message")

    def watch_state(self, state: DashboardState | None) -> None:
        """Update counters when state changes."""
        if state is None:
            return

        self._update_counters(state)

    def _update_counters(self, state: DashboardState) -> None:
        """Update all health counters."""
        # Map categories to state values
        counter_values = {
            "fail": state.failed_count,
            "err": state.ignored_err_count,
            "hw_cap": state.hw_cap_count,
            "skip": state.skipped_count,
            "kept": state.min_ratio_skip_count,
            "small": state.ignored_small_count,
            "av1": state.ignored_av1_count,
            "cam": state.cam_skipped_count,
        }

        # Update each counter
        for counter in self.query(HealthCounter):
            if counter.category in counter_values:
                counter.update_count(counter_values[counter.category])

        # Update action message
        action_widget = self.query_one("#action-message", Static)
        if state.last_action:
            # Fade based on time
            if state.last_action_time:
                from datetime import datetime

                elapsed = (datetime.now() - state.last_action_time).total_seconds()
                if elapsed < 5:
                    action_widget.update(f"[white]{state.last_action}[/]")
                elif elapsed < 10:
                    action_widget.update(f"[grey70]{state.last_action}[/]")
                else:
                    action_widget.update(f"[grey30]{state.last_action}[/]")
            else:
                action_widget.update(state.last_action)
        else:
            action_widget.update("")

    def on_health_counter_clicked(self, event: HealthCounter.Clicked) -> None:
        """Handle counter click - open stats browser for category."""
        self.post_message(self.CategoryClicked(event.category))
