"""Stats browser screen for VBC Textual Dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, ListView, ListItem, Static

if TYPE_CHECKING:
    from vbc.ui.textual.app import TextualDashboardApp
    from vbc.ui.textual.state_bridge import StatsCategory


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


def truncate_path(path: Path, max_len: int = 50) -> str:
    """Truncate path with ellipsis."""
    path_str = str(path)
    if len(path_str) <= max_len:
        return path_str
    return "..." + path_str[-(max_len - 3) :]


class CategoryListItem(ListItem):
    """A category item in the list."""

    def __init__(self, category_name: str, label: str, count: int) -> None:
        super().__init__()
        self.category_name = category_name
        self.label_text = label
        self.count = count

    def compose(self) -> ComposeResult:
        """Compose the list item."""
        if self.count > 0:
            yield Static(f"{self.label_text} ({self.count})")
        else:
            yield Static(f"[dim]{self.label_text} (0)[/]")


class StatsBrowserScreen(Screen):
    """Screen for browsing health/stats categories and their files."""

    DEFAULT_CSS = """
    StatsBrowserScreen {
        layout: grid;
        grid-size: 2;
        grid-columns: 25 1fr;
    }

    StatsBrowserScreen #categories-panel {
        height: 100%;
    }

    StatsBrowserScreen .panel-title {
        text-style: bold;
        padding: 1;
    }

    StatsBrowserScreen #categories-list {
        height: 1fr;
    }

    StatsBrowserScreen #categories-list ListItem {
        padding: 0 1;
    }

    StatsBrowserScreen #categories-list ListItem:hover {
    }

    StatsBrowserScreen #categories-list ListItem.-selected {
    }

    StatsBrowserScreen #files-panel {
        height: 100%;
    }

    StatsBrowserScreen #files-table {
        height: 1fr;
    }

    StatsBrowserScreen .no-files {
        padding: 2;
        text-align: center;
    }

    StatsBrowserScreen .category-count-zero ListItem {
    }
    """

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("b", "go_back", "Back"),
    ]

    def __init__(self, initial_category: str | None = None) -> None:
        super().__init__()
        self.initial_category = initial_category
        self.current_category: str | None = None
        self.categories: dict[str, StatsCategory] = {}

    def compose(self) -> ComposeResult:
        """Compose the stats browser screen."""
        yield Header(show_clock=False)

        with Container(id="categories-panel"):
            yield Static("CATEGORIES", classes="panel-title")
            yield ListView(id="categories-list")

        with Container(id="files-panel"):
            yield Static("FILES", id="files-title", classes="panel-title")
            yield DataTable(id="files-table")
            yield Static("Select a category to view files", id="no-files", classes="no-files")

        yield Footer()

    def on_mount(self) -> None:
        """Set up the screen."""
        # Get app reference
        app: TextualDashboardApp = self.app  # type: ignore

        # Get categories from state
        state = app.state_bridge.state
        self.categories = state.stats_categories

        # Populate categories list
        self._populate_categories()

        # Set up files table
        table = self.query_one("#files-table", DataTable)
        table.add_columns("Path", "Size", "Reason")
        table.cursor_type = "row"
        table.display = False  # Hide until category selected

        # Select initial category if provided
        if self.initial_category and self.initial_category in self.categories:
            self._select_category(self.initial_category)

    def _populate_categories(self) -> None:
        """Populate the categories list."""
        categories_list = self.query_one("#categories-list", ListView)

        # Category display order
        category_order = ["fail", "err", "hw_cap", "skip", "kept", "small", "av1", "cam"]

        for cat_name in category_order:
            if cat_name in self.categories:
                cat = self.categories[cat_name]
                item = CategoryListItem(cat_name, cat.label, cat.count)
                categories_list.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle category selection."""
        if isinstance(event.item, CategoryListItem):
            self._select_category(event.item.category_name)

    def _select_category(self, category_name: str) -> None:
        """Select a category and show its files."""
        self.current_category = category_name

        if category_name not in self.categories:
            return

        category = self.categories[category_name]

        # Update title
        title = self.query_one("#files-title", Static)
        title.update(f"FILES - {category.label} ({category.count})")

        # Update table
        table = self.query_one("#files-table", DataTable)
        no_files = self.query_one("#no-files", Static)

        table.clear()

        if category.files:
            table.display = True
            no_files.display = False

            for path, size, reason in category.files:
                table.add_row(
                    truncate_path(path),
                    format_bytes(size),
                    reason[:40] if len(reason) > 40 else reason,
                )
        else:
            table.display = False
            no_files.display = True
            if category.count > 0:
                no_files.update(
                    f"Category has {category.count} items but file details not available.\n"
                    "File tracking is enabled for new items."
                )
            else:
                no_files.update("No files in this category")

    def action_go_back(self) -> None:
        """Go back to dashboard."""
        self.app.pop_screen()

    def refresh_data(self) -> None:
        """Refresh data from state."""
        app: TextualDashboardApp = self.app  # type: ignore
        state = app.state_bridge.state
        self.categories = state.stats_categories

        # Re-populate if category selected
        if self.current_category:
            self._select_category(self.current_category)
