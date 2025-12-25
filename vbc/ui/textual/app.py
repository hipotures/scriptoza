"""Main Textual Dashboard Application for VBC."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive

from vbc.domain.events import (
    ActionMessage,
    DiscoveryFinished,
    DiscoveryStarted,
    HardwareCapabilityExceeded,
    JobCompleted,
    JobFailed,
    JobProgressUpdated,
    JobStarted,
    ProcessingFinished,
    QueueUpdated,
    RefreshRequested,
)
from vbc.ui.textual.screens.dashboard import DashboardScreen
from vbc.ui.textual.screens.job_details import JobDetailsScreen
from vbc.ui.textual.screens.stats_browser import StatsBrowserScreen
from vbc.ui.textual.state_bridge import DashboardState, StateBridge
from vbc.ui.textual.themes import AVAILABLE_THEMES, DEFAULT_THEME, get_theme_path

if TYPE_CHECKING:
    from vbc.config.models import AppConfig
    from vbc.infrastructure.event_bus import EventBus
    from vbc.ui.state import UIState


class TextualDashboardApp(App):
    """VBC Textual Dashboard Application.

    A modern TUI dashboard for video batch compression with:
    - 4 switchable themes
    - Real-time progress tracking
    - GPU metrics visualization
    - Job details modal
    - Stats browser for error categories
    """

    TITLE = "VBC - Video Batch Compression"
    SUB_TITLE = "Textual Dashboard"

    # CSS will be loaded dynamically in __init__
    CSS_PATH = None

    BINDINGS = [
        Binding("m", "toggle_menu", "Menu", show=True),
        Binding("c", "toggle_config", "Config", show=True),
        Binding("l", "toggle_legend", "Legend", show=True),
        Binding("s", "request_shutdown", "Shutdown", show=True),
        Binding("r", "refresh_queue", "Refresh", show=True),
        Binding("g", "rotate_gpu_metric", "GPU", show=True),
        Binding("t", "cycle_theme", "Theme", show=True),
        Binding("left_square_bracket", "sort_prev_column", "Sort◄", show=False),
        Binding("right_square_bracket", "sort_next_column", "Sort►", show=False),
        Binding("slash", "toggle_sort_order", "Sort↕", show=False),
        Binding("comma", "decrease_threads", "-Thread", show=False),
        Binding("period", "increase_threads", "+Thread", show=False),
        Binding("less_than_sign", "decrease_threads", "-Thread", show=False),
        Binding("greater_than_sign", "increase_threads", "+Thread", show=False),
        Binding("escape", "close_overlay", "Close", show=False),
        Binding("j", "job_details", "Details", show=True),
        Binding("h", "stats_browser", "Health", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    SCREENS = {
        "dashboard": DashboardScreen,
        "stats_browser": StatsBrowserScreen,
    }

    # Reactive state
    theme_name: reactive[str] = reactive(DEFAULT_THEME)
    dashboard_state: reactive[DashboardState] = reactive(DashboardState, init=False)

    def __init__(
        self,
        ui_state: UIState,
        event_bus: EventBus,
        config: AppConfig,
        theme: str | None = None,
    ):
        """Initialize the Textual dashboard.

        Args:
            ui_state: Thread-safe UI state manager
            event_bus: Event bus for domain events
            config: Application configuration
            theme: Optional theme name override
        """
        super().__init__()

        self.ui_state = ui_state
        self.event_bus = event_bus
        self.config = config

        # State bridge for thread-safe state access
        self.state_bridge = StateBridge(ui_state)

        # Set initial theme
        if theme and theme in AVAILABLE_THEMES:
            self.theme_name = theme
        elif hasattr(config, "textual") and hasattr(config.textual, "default_theme"):
            self.theme_name = config.textual.default_theme
        else:
            self.theme_name = DEFAULT_THEME

        # Load theme CSS immediately
        theme_path = get_theme_path(self.theme_name)
        if theme_path.exists():
            self.CSS_PATH = str(theme_path)

        # Track selected job for details modal
        self._selected_job_index = 0

    def on_mount(self) -> None:
        """Called when app is mounted."""
        # Load theme CSS
        self._load_theme()

        # Subscribe to domain events
        self._subscribe_to_events()

        # Start state sync worker
        self._start_state_sync()

        # Push initial screen
        self.push_screen("dashboard")

    def _load_theme(self) -> None:
        """Load the current theme CSS."""
        try:
            theme_path = get_theme_path(self.theme_name)
            if theme_path.exists():
                # Clear existing styles and load new theme
                self.stylesheet.clear()
                self.stylesheet.read(theme_path)
                self.refresh_css()
        except Exception as e:
            self.log(f"Error loading theme {self.theme_name}: {e}")

    def watch_theme_name(self, new_theme: str) -> None:
        """React to theme changes."""
        self._load_theme()
        # Show action message
        self.ui_state.set_last_action(f"Theme: {new_theme}")

    def _subscribe_to_events(self) -> None:
        """Subscribe to domain events from the event bus."""
        self.event_bus.subscribe(DiscoveryStarted, self._on_discovery_started)
        self.event_bus.subscribe(DiscoveryFinished, self._on_discovery_finished)
        self.event_bus.subscribe(JobStarted, self._on_job_started)
        self.event_bus.subscribe(JobProgressUpdated, self._on_job_progress)
        self.event_bus.subscribe(JobCompleted, self._on_job_completed)
        self.event_bus.subscribe(JobFailed, self._on_job_failed)
        self.event_bus.subscribe(HardwareCapabilityExceeded, self._on_hw_cap_exceeded)
        self.event_bus.subscribe(QueueUpdated, self._on_queue_updated)
        self.event_bus.subscribe(ActionMessage, self._on_action_message)
        self.event_bus.subscribe(ProcessingFinished, self._on_processing_finished)

    @work(exclusive=True, thread=True)
    def _start_state_sync(self) -> None:
        """Start background state synchronization."""
        import time

        refresh_interval = 0.25  # 4Hz
        while not self.ui_state.finished:
            try:
                # Check if app is still running
                if not self.is_running:
                    break
                # Sync state in thread
                new_state = self.state_bridge.sync()
                # Update reactive (will trigger UI refresh)
                self.call_from_thread(self._update_state, new_state)
            except Exception:
                # Ignore errors during shutdown
                break
            time.sleep(refresh_interval)

    def _update_state(self, new_state: DashboardState) -> None:
        """Update dashboard state (called from main thread)."""
        try:
            if self.is_mounted:
                self.dashboard_state = new_state
        except Exception:
            # Ignore errors during shutdown or before mount
            pass

    # Event handlers
    def _on_discovery_started(self, event: DiscoveryStarted) -> None:
        """Handle discovery started event."""
        pass  # UIManager handles state updates

    def _on_discovery_finished(self, event: DiscoveryFinished) -> None:
        """Handle discovery finished event."""
        # Track ignored files for stats browser
        # (This would need integration with orchestrator)
        pass

    def _on_job_started(self, event: JobStarted) -> None:
        """Handle job started event."""
        pass  # UIManager handles state updates

    def _on_job_progress(self, event: JobProgressUpdated) -> None:
        """Handle job progress update."""
        pass  # UIManager handles state updates

    def _on_job_completed(self, event: JobCompleted) -> None:
        """Handle job completed event."""
        pass  # UIManager handles state updates

    def _on_job_failed(self, event: JobFailed) -> None:
        """Handle job failed event."""
        # Track for stats browser
        job = event.job
        self.state_bridge.add_failed_job(
            job.source_file.path,
            job.source_file.size_bytes,
            event.error_message,
        )

    def _on_hw_cap_exceeded(self, event: HardwareCapabilityExceeded) -> None:
        """Handle hardware capability exceeded event."""
        job = event.job
        self.state_bridge.add_hw_cap_file(
            job.source_file.path,
            job.source_file.size_bytes,
        )

    def _on_queue_updated(self, event: QueueUpdated) -> None:
        """Handle queue update event."""
        pass  # UIManager handles state updates

    def _on_action_message(self, event: ActionMessage) -> None:
        """Handle action message event."""
        pass  # UIManager handles state updates

    def _on_processing_finished(self, event: ProcessingFinished) -> None:
        """Handle processing finished event."""
        pass  # UIManager handles state updates

    # Actions
    def action_toggle_menu(self) -> None:
        """Toggle menu overlay."""
        try:
            with self.ui_state._lock:
                self.ui_state.show_menu = not self.ui_state.show_menu
                if self.ui_state.show_menu:
                    self.ui_state.show_config = False
                    self.ui_state.show_legend = False
        except Exception as e:
            self.log(f"Error toggling menu: {e}")

    def action_toggle_config(self) -> None:
        """Toggle config overlay."""
        try:
            with self.ui_state._lock:
                self.ui_state.show_config = not self.ui_state.show_config
                if self.ui_state.show_config:
                    self.ui_state.show_menu = False
                    self.ui_state.show_legend = False
        except Exception as e:
            self.log(f"Error toggling config: {e}")

    def action_toggle_legend(self) -> None:
        """Toggle legend overlay."""
        try:
            with self.ui_state._lock:
                self.ui_state.show_legend = not self.ui_state.show_legend
                if self.ui_state.show_legend:
                    self.ui_state.show_menu = False
                    self.ui_state.show_config = False
        except Exception as e:
            self.log(f"Error toggling legend: {e}")

    def action_request_shutdown(self) -> None:
        """Toggle shutdown request."""
        with self.ui_state._lock:
            self.ui_state.shutdown_requested = not self.ui_state.shutdown_requested
            status = "Shutdown requested" if self.ui_state.shutdown_requested else "Shutdown cancelled"
            self.ui_state.set_last_action(status)

    def action_refresh_queue(self) -> None:
        """Request queue refresh."""
        self.event_bus.publish(RefreshRequested())
        self.ui_state.set_last_action("Queue refresh requested")

    def action_rotate_gpu_metric(self) -> None:
        """Rotate GPU sparkline metric."""
        metric_names = ["Temperature", "Fan Speed", "Power", "GPU %", "Memory %"]
        with self.ui_state._lock:
            self.ui_state.gpu_sparkline_metric_idx = (
                self.ui_state.gpu_sparkline_metric_idx + 1
            ) % 5
            idx = self.ui_state.gpu_sparkline_metric_idx
        self.ui_state.set_last_action(f"GPU Metric: {metric_names[idx]}")

    def action_cycle_theme(self) -> None:
        """Cycle through available themes."""
        current_idx = AVAILABLE_THEMES.index(self.theme_name)
        next_idx = (current_idx + 1) % len(AVAILABLE_THEMES)
        self.theme_name = AVAILABLE_THEMES[next_idx]

    def action_decrease_threads(self) -> None:
        """Decrease thread count."""
        with self.ui_state._lock:
            if self.ui_state.current_threads > 1:
                self.ui_state.current_threads -= 1
                self.ui_state.set_last_action(
                    f"Threads: {self.ui_state.current_threads}"
                )

    def action_increase_threads(self) -> None:
        """Increase thread count."""
        with self.ui_state._lock:
            max_threads = self.config.general.threads * 2  # Allow some headroom
            if self.ui_state.current_threads < max_threads:
                self.ui_state.current_threads += 1
                self.ui_state.set_last_action(
                    f"Threads: {self.ui_state.current_threads}"
                )

    def action_close_overlay(self) -> None:
        """Close all overlays."""
        with self.ui_state._lock:
            self.ui_state.show_menu = False
            self.ui_state.show_config = False
            self.ui_state.show_legend = False

    def action_job_details(self) -> None:
        """Show job details modal."""
        # Get all jobs (active + recent)
        state = self.state_bridge.state
        all_jobs = list(state.active_jobs) + list(state.recent_jobs)

        if all_jobs:
            self.push_screen(
                JobDetailsScreen(
                    jobs=all_jobs,
                    initial_index=self._selected_job_index,
                    job_start_times=state.job_start_times,
                ),
                callback=self._on_job_details_closed,
            )

    def _on_job_details_closed(self, index: int | None) -> None:
        """Handle job details modal closing."""
        if index is not None:
            self._selected_job_index = index

    def action_stats_browser(self) -> None:
        """Show stats browser screen."""
        self.push_screen("stats_browser")

    def action_sort_prev_column(self) -> None:
        """Cycle to previous sort column in Queue panel."""
        try:
            from vbc.ui.textual.widgets.queue_panel import SortColumn

            dashboard = self.screen
            if hasattr(dashboard, 'query_one'):
                queue_panel = dashboard.query_one("QueuePanel")
                columns = [SortColumn.NAME, SortColumn.SIZE, SortColumn.FPS]
                current_idx = columns.index(queue_panel.queue_sort_column)
                next_idx = (current_idx - 1) % len(columns)
                queue_panel.queue_sort_column = columns[next_idx]
                self.ui_state.set_last_action(f"Sort: {columns[next_idx].value}")
        except Exception:
            pass

    def action_sort_next_column(self) -> None:
        """Cycle to next sort column in Queue panel."""
        try:
            from vbc.ui.textual.widgets.queue_panel import SortColumn

            dashboard = self.screen
            if hasattr(dashboard, 'query_one'):
                queue_panel = dashboard.query_one("QueuePanel")
                columns = [SortColumn.NAME, SortColumn.SIZE, SortColumn.FPS]
                current_idx = columns.index(queue_panel.queue_sort_column)
                next_idx = (current_idx + 1) % len(columns)
                queue_panel.queue_sort_column = columns[next_idx]
                self.ui_state.set_last_action(f"Sort: {columns[next_idx].value}")
        except Exception:
            pass

    def action_toggle_sort_order(self) -> None:
        """Toggle sort order in Queue panel."""
        try:
            from vbc.ui.textual.widgets.queue_panel import SortOrder

            dashboard = self.screen
            if hasattr(dashboard, 'query_one'):
                queue_panel = dashboard.query_one("QueuePanel")
                if queue_panel.queue_sort_order == SortOrder.ASC:
                    queue_panel.queue_sort_order = SortOrder.DESC
                    arrow = "▼"
                else:
                    queue_panel.queue_sort_order = SortOrder.ASC
                    arrow = "▲"
                self.ui_state.set_last_action(f"Sort: {arrow}")
        except Exception:
            pass

    def action_quit(self) -> None:
        """Quit the application."""
        # Mark as finished to stop sync worker
        self.ui_state.finished = True
        self.exit()
