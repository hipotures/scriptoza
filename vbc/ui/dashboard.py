from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from vbc.ui.state import UIState

class Dashboard:
    """Renders the real-time interactive dashboard using Rich."""
    
    def __init__(self, state: UIState):
        self.state = state
        self.console = Console()

    def _generate_status_panel(self) -> Panel:
        with self.state._lock:
            status_text = Text.assemble(
                ("Status: ", "bold"),
                ("ACTIVE" if not self.state.shutdown_requested else "SHUTTING DOWN", "green" if not self.state.shutdown_requested else "yellow"),
                " | ",
                ("Threads: ", "bold"), f"{self.state.current_threads}",
                " | ",
                ("Done: ", "bold"), f"{self.state.completed_count}",
                " | ",
                ("Failed: ", "bold"), (f"{self.state.failed_count}", "red"),
                " | ",
                ("Skipped: ", "bold"), f"{self.state.skipped_count}"
            )
        return Panel(status_text, title="System Status", border_style="blue")

    def _generate_active_jobs_table(self) -> Panel:
        table = Table(box=None, expand=True)
        table.add_column("File", style="cyan")
        table.add_column("Camera", style="magenta")
        table.add_column("Status", style="yellow")
        
        with self.state._lock:
            for job in self.state.active_jobs:
                camera = job.source_file.metadata.camera_model if job.source_file.metadata else "N/A"
                table.add_row(job.source_file.path.name, camera, job.status)
                
        return Panel(table, title="Currently Processing", border_style="green")

    def _generate_recent_jobs_table(self) -> Panel:
        table = Table(box=None, expand=True)
        table.add_column("File", style="cyan")
        table.add_column("Ratio", style="green")
        table.add_column("Status", style="bold")
        
        with self.state._lock:
            for job in self.state.recent_jobs:
                # Simplified ratio for display
                ratio_str = "N/A"
                if job.output_path and job.output_path.exists():
                    in_size = job.source_file.size_bytes
                    out_size = job.output_path.stat().st_size
                    ratio_str = f"{(out_size/in_size)*100:.1f}%"
                
                status_style = "green" if job.status == "COMPLETED" else "red"
                table.add_row(job.source_file.path.name, ratio_str, Text(job.status, style=status_style))
                
        return Panel(table, title="Recently Completed", border_style="white")

    def _generate_summary_panel(self) -> Panel:
        with self.state._lock:
            saved_gb = self.state.space_saved_bytes / (1024**3)
            ratio = self.state.compression_ratio * 100
            summary_text = Text.assemble(
                ("Total Saved: ", "bold"), f"{saved_gb:.2f} GB",
                " | ",
                ("Avg Ratio: ", "bold"), f"{ratio:.1f}%"
            )
        return Panel(summary_text, title="Session Summary", border_style="yellow")

    def make_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3)
        )
        layout["main"].split_row(
            Layout(name="left"),
            Layout(name="right")
        )
        
        layout["header"].update(self._generate_status_panel())
        layout["left"].update(self._generate_active_jobs_table())
        layout["right"].update(self._generate_recent_jobs_table())
        layout["footer"].update(self._generate_summary_panel())
        
        return layout

    def start(self):
        """Starts the live dashboard loop."""
        return Live(self.make_layout(), console=self.console, refresh_per_second=4)
