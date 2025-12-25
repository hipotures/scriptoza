"""Queue panel widget for VBC Textual Dashboard."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Static

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


def truncate_filename(name: str, max_len: int = 35) -> str:
    """Truncate filename with ellipsis in middle."""
    if len(name) <= max_len:
        return name
    half = (max_len - 1) // 2
    return f"{name[:half]}…{name[-half:]}"


class SortColumn(Enum):
    """Sort column options."""

    NAME = "name"
    SIZE = "size"
    FPS = "fps"


class SortOrder(Enum):
    """Sort order options."""

    ASC = "asc"
    DESC = "desc"


class QueuePanel(Widget):
    """Panel showing pending files in queue with sorting/filtering."""

    # Reactive properties
    state: reactive[DashboardState | None] = reactive(None)
    queue_sort_column: reactive[SortColumn] = reactive(SortColumn.NAME)
    queue_sort_order: reactive[SortOrder] = reactive(SortOrder.ASC)
    filter_extension: reactive[str | None] = reactive(None)

    DEFAULT_CSS = """
    QueuePanel {
        height: auto;
        min-height: 5;
        padding: 0 1;
        border: solid #00ffff;
    }

    QueuePanel #sort-info {
        height: 1;
        padding: 0 0 1 0;
    }

    QueuePanel #queue-table {
        width: 100%;
        height: 1fr;
    }

    QueuePanel .no-queue {
        padding: 1;
    }
    """


    class SortChanged(Message):
        """Message when sort changes."""

        def __init__(self, column: SortColumn, order: SortOrder) -> None:
            self.column = column
            self.order = order
            super().__init__()

    def compose(self) -> ComposeResult:
        """Compose the queue panel."""
        yield Static(id="sort-info")
        yield DataTable(id="queue-table")

    def on_mount(self) -> None:
        """Initialize the data table and set border title."""
        self.border_title = "QUEUE"
        table = self.query_one("#queue-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("", "File", "Size", "FPS")
        self._update_sort_info()

    def watch_state(self, state: DashboardState | None) -> None:
        """Update queue when state changes."""
        if state is None:
            return

        self._update_queue(state)

    def watch_queue_sort_column(self, column: SortColumn) -> None:
        """Update sort info when sort column changes."""
        self._update_sort_info()
        if self.state:
            self._update_queue(self.state)

    def watch_queue_sort_order(self, order: SortOrder) -> None:
        """Update sort info when sort order changes."""
        self._update_sort_info()
        if self.state:
            self._update_queue(self.state)

    def _update_sort_info(self) -> None:
        """Update the sort info line."""
        sort_info = self.query_one("#sort-info", Static)

        arrow = "▲" if self.queue_sort_order == SortOrder.ASC else "▼"
        column_name = self.queue_sort_column.value.capitalize()

        sort_info.update(
            f"[dim]Sort:[/] {column_name} {arrow}  [dim]│  [ ] / ] to change column  │  / to toggle order[/]"
        )

    def _update_queue(self, state: DashboardState) -> None:
        """Update the queue table."""
        table = self.query_one("#queue-table", DataTable)

        pending = list(state.pending_files)

        # Sort files
        pending = self._sort_files(pending)

        # Filter by extension if set
        if self.filter_extension:
            pending = [
                f
                for f in pending
                if f.path.suffix.lower() == self.filter_extension.lower()
            ]

        # Clear and repopulate table
        table.clear()

        if not pending:
            # Show message in empty table
            return

        for f in pending[:50]:  # Limit to 50 items for performance
            name = truncate_filename(f.path.name)
            size = format_bytes(f.size_bytes)
            fps = ""
            if f.metadata and f.metadata.fps:
                fps = f"{f.metadata.fps:.0f}"

            table.add_row("»", name, size, fps)

        # Show count if more items
        if len(pending) > 50:
            remaining = len(pending) - 50
            table.add_row("", f"... +{remaining} more", "", "")

    def _sort_files(self, files: list[Any]) -> list[Any]:
        """Sort files based on current sort settings."""
        reverse = self.queue_sort_order == SortOrder.DESC

        if self.queue_sort_column == SortColumn.NAME:
            return sorted(files, key=lambda f: f.path.name.lower(), reverse=reverse)
        elif self.queue_sort_column == SortColumn.SIZE:
            return sorted(files, key=lambda f: f.size_bytes, reverse=reverse)
        elif self.queue_sort_column == SortColumn.FPS:

            def get_fps(f: Any) -> float:
                if f.metadata and f.metadata.fps:
                    return f.metadata.fps
                return 0.0

            return sorted(files, key=get_fps, reverse=reverse)

        return files

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle table header clicks for sorting."""
        # Map column index to sort column
        # Columns: ["", "File", "Size", "FPS"]
        column_map = {
            1: SortColumn.NAME,   # File column
            2: SortColumn.SIZE,   # Size column
            3: SortColumn.FPS,    # FPS column
        }

        selected_column = column_map.get(event.column_index)
        if selected_column is None:
            return  # Clicked on icon column, ignore

        if self.queue_sort_column == selected_column:
            # Toggle order
            self.queue_sort_order = (
                SortOrder.DESC
                if self.queue_sort_order == SortOrder.ASC
                else SortOrder.ASC
            )
        else:
            # New column - set default order
            self.queue_sort_column = selected_column
            if selected_column == SortColumn.NAME:
                self.queue_sort_order = SortOrder.ASC
            else:
                self.queue_sort_order = SortOrder.DESC  # Size/FPS default to descending

        self.post_message(self.SortChanged(self.queue_sort_column, self.queue_sort_order))
