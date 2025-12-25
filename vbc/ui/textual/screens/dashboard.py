"""Main dashboard screen for VBC Textual Dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from vbc.ui.textual.widgets.active_jobs import ActiveJobsPanel
from vbc.ui.textual.widgets.activity_feed import ActivityFeed
from vbc.ui.textual.widgets.gpu_sparkline import GPUSparkline
from vbc.ui.textual.widgets.header import HeaderWidget
from vbc.ui.textual.widgets.health_footer import HealthFooter
from vbc.ui.textual.widgets.progress_panel import ProgressPanel
from vbc.ui.textual.widgets.queue_panel import QueuePanel

if TYPE_CHECKING:
    from vbc.ui.textual.app import TextualDashboardApp


class MenuOverlay(Static):
    """Menu overlay showing keyboard shortcuts."""

    DEFAULT_CSS = """
    MenuOverlay {
        layer: overlay;
        dock: top;
        width: 100%;
        height: 100%;
        align: center middle;
    }

    MenuOverlay #menu-container {
        width: 50;
        height: auto;
        padding: 1 2;
        background: #1a1a2e;
        border: solid #00ffff;
    }

    MenuOverlay .menu-title {
        text-style: bold;
        text-align: center;
        padding-bottom: 1;
    }

    MenuOverlay .menu-section {
        padding-top: 1;
    }

    MenuOverlay .menu-item {
        padding-left: 2;
    }

    MenuOverlay .key {
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the menu overlay."""
        with Container(id="menu-container"):
            yield Static("KEYBOARD SHORTCUTS", classes="menu-title")

            yield Static("Navigation & Control", classes="menu-section")
            yield Static("[key]M[/]   Menu toggle", classes="menu-item")
            yield Static("[key]Esc[/] Close overlays", classes="menu-item")
            yield Static("[key]Q[/]   Quit application", classes="menu-item")

            yield Static("Job Management", classes="menu-section")
            yield Static("[key]S[/]   Toggle shutdown", classes="menu-item")
            yield Static("[key]< ,[/] Decrease threads", classes="menu-item")
            yield Static("[key]> .[/] Increase threads", classes="menu-item")
            yield Static("[key]R[/]   Refresh queue", classes="menu-item")

            yield Static("Queue Sorting", classes="menu-section")
            yield Static("[key][ ][/]   Previous column", classes="menu-item")
            yield Static("[key]] [/]   Next column", classes="menu-item")
            yield Static("[key]/ [/]   Toggle order (↕)", classes="menu-item")

            yield Static("Information Panels", classes="menu-section")
            yield Static("[key]C[/]   Config overlay", classes="menu-item")
            yield Static("[key]L[/]   Legend overlay", classes="menu-item")
            yield Static("[key]G[/]   Rotate GPU metric", classes="menu-item")
            yield Static("[key]J[/]   Job details", classes="menu-item")
            yield Static("[key]H[/]   Health/Stats browser", classes="menu-item")

            yield Static("Theme", classes="menu-section")
            yield Static("[key]T[/]   Cycle theme", classes="menu-item")


class ConfigOverlay(Static):
    """Config overlay showing current configuration."""

    DEFAULT_CSS = """
    ConfigOverlay {
        layer: overlay;
        dock: top;
        width: 100%;
        height: 100%;
        align: center middle;
    }

    ConfigOverlay #config-container {
        width: 60;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        overflow-y: auto;
        background: #1a1a2e;
        border: solid #00ffff;
    }

    ConfigOverlay .config-title {
        text-style: bold;
        text-align: center;
        padding-bottom: 1;
    }

    ConfigOverlay .config-line {
        padding: 0;
    }
    """

    def __init__(self, config_lines: list[str]) -> None:
        super().__init__()
        self.config_lines = config_lines

    def compose(self) -> ComposeResult:
        """Compose the config overlay."""
        with Container(id="config-container"):
            yield Static("CONFIGURATION", classes="config-title")
            for line in self.config_lines:
                if ":" in line:
                    key, value = line.split(":", 1)
                    yield Static(f"[grey70]{key}:[/]{value}", classes="config-line")
                else:
                    yield Static(line, classes="config-line")


class LegendOverlay(Static):
    """Legend overlay explaining status symbols."""

    DEFAULT_CSS = """
    LegendOverlay {
        layer: overlay;
        dock: top;
        width: 100%;
        height: 100%;
        align: center middle;
    }

    LegendOverlay #legend-container {
        width: 50;
        height: auto;
        padding: 1 2;
        background: #1a1a2e;
        border: solid #00ffff;
    }

    LegendOverlay .legend-title {
        text-style: bold;
        text-align: center;
        padding-bottom: 1;
    }

    LegendOverlay .legend-section {
        padding-top: 1;
    }

    LegendOverlay .legend-item {
        padding-left: 2;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the legend overlay."""
        with Container(id="legend-container"):
            yield Static("LEGEND", classes="legend-title")

            yield Static("Status Indicators", classes="legend-section")
            yield Static("[green]●[/] Active - Processing", classes="legend-item")
            yield Static("[yellow]◐[/] Shutdown requested", classes="legend-item")
            yield Static("[red]![/] Interrupt in progress", classes="legend-item")

            yield Static("Job Status Icons", classes="legend-section")
            yield Static("[green]✓[/] Completed successfully", classes="legend-item")
            yield Static("[red]✗[/] Failed with error", classes="legend-item")
            yield Static("[dim]≡[/] Kept original (low ratio)", classes="legend-item")
            yield Static("[red]⚡[/] Interrupted by user", classes="legend-item")

            yield Static("Health Counters", classes="legend-section")
            yield Static("[red]fail[/] FFmpeg errors", classes="legend-item")
            yield Static("[red]err[/] Files with .err marker", classes="legend-item")
            yield Static("[yellow]hw_cap[/] Hardware limit exceeded", classes="legend-item")
            yield Static("[yellow]skip[/] Skipped files", classes="legend-item")
            yield Static("[dim]kept[/] Original kept", classes="legend-item")
            yield Static("[dim]small[/] Below min size", classes="legend-item")
            yield Static("[dim]av1[/] Already AV1", classes="legend-item")
            yield Static("[dim]cam[/] Camera filter", classes="legend-item")


class DashboardScreen(Screen):
    """Main dashboard screen showing all panels."""

    DEFAULT_CSS = """
    DashboardScreen {
        layers: base overlay;
    }

    DashboardScreen #main-container {
        width: 100%;
        height: 100%;
    }

    DashboardScreen #header {
        dock: top;
        height: 3;
    }

    DashboardScreen #content {
        width: 100%;
        height: 1fr;
        margin: 0;
        padding: 0;
    }

    DashboardScreen #top-row {
        height: 5;
        width: 100%;
        margin: 0;
    }

    DashboardScreen #progress-panel {
        width: 1fr;
    }

    DashboardScreen #gpu-sparkline {
        width: 1fr;
    }

    DashboardScreen #main-row {
        height: 1fr;
        width: 100%;
        padding: 0;
    }

    DashboardScreen #active-jobs {
        width: 1fr;
        height: 1fr;
    }

    DashboardScreen #right-column {
        width: 1fr;
        padding: 0;
    }

    DashboardScreen #activity-feed {
        height: auto;
        min-height: 8;
    }

    DashboardScreen #queue-panel {
        height: 1fr;
    }
    """

    BINDINGS = []  # Bindings handled by app

    def compose(self) -> ComposeResult:
        """Compose the dashboard screen."""
        with Container(id="main-container"):
            yield HeaderWidget(id="header")

            with Container(id="content"):
                # Top row: Progress + GPU
                with Horizontal(id="top-row"):
                    yield ProgressPanel(id="progress-panel")
                    yield GPUSparkline(id="gpu-sparkline")

                # Main row: Active jobs | Activity + Queue
                with Horizontal(id="main-row"):
                    yield ActiveJobsPanel(id="active-jobs")
                    with Vertical(id="right-column"):
                        yield ActivityFeed(id="activity-feed")
                        yield QueuePanel(id="queue-panel")

            yield HealthFooter(id="health-footer")

        yield Footer()

    def on_mount(self) -> None:
        """Set up state watching."""
        # Get app reference
        app: TextualDashboardApp = self.app  # type: ignore

        # Watch for state changes
        self.watch(app, "dashboard_state", self._on_state_change)

    def _on_state_change(self, state) -> None:
        """Handle state changes from app."""
        if state is None:
            return

        # Update all widgets with new state
        header = self.query_one("#header", HeaderWidget)
        header.state = state

        progress = self.query_one("#progress-panel", ProgressPanel)
        progress.state = state

        gpu = self.query_one("#gpu-sparkline", GPUSparkline)
        gpu.state = state

        active = self.query_one("#active-jobs", ActiveJobsPanel)
        active.state = state

        activity = self.query_one("#activity-feed", ActivityFeed)
        activity.state = state

        queue = self.query_one("#queue-panel", QueuePanel)
        queue.state = state

        footer = self.query_one("#health-footer", HealthFooter)
        footer.state = state

        # Handle overlays
        self._update_overlays(state)

    def _update_overlays(self, state) -> None:
        """Show/hide overlays based on state."""
        # Remove existing overlays
        for overlay in self.query("MenuOverlay, ConfigOverlay, LegendOverlay"):
            overlay.remove()

        # Show appropriate overlay
        if state.show_menu:
            self.mount(MenuOverlay())
        elif state.show_config:
            self.mount(ConfigOverlay(state.config_lines))
        elif state.show_legend:
            self.mount(LegendOverlay())

    def on_active_jobs_panel_job_selected(self, event: ActiveJobsPanel.JobSelected) -> None:
        """Handle job selection - open details."""
        app: TextualDashboardApp = self.app  # type: ignore
        app._selected_job_index = event.index
        app.action_job_details()

    def on_health_footer_category_clicked(self, event: HealthFooter.CategoryClicked) -> None:
        """Handle category click - open stats browser."""
        app: TextualDashboardApp = self.app  # type: ignore
        # TODO: Pass category to stats browser
        app.action_stats_browser()
