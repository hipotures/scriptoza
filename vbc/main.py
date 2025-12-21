import typer
import threading
from pathlib import Path
from typing import Optional
from vbc.config.loader import load_config
from vbc.infrastructure.event_bus import EventBus
from vbc.infrastructure.file_scanner import FileScanner
from vbc.infrastructure.exif_tool import ExifToolAdapter
from vbc.infrastructure.ffprobe import FFprobeAdapter
from vbc.infrastructure.ffmpeg import FFmpegAdapter
from vbc.pipeline.orchestrator import Orchestrator
from vbc.ui.state import UIState
from vbc.ui.manager import UIManager
from vbc.ui.dashboard import Dashboard
from vbc.ui.keyboard import KeyboardListener, ThreadControlEvent, RequestShutdown

app = typer.Typer(help="VBC (Video Batch Compression) - Modular Version")

@app.command()
def compress(
    input_dir: Path = typer.Argument(..., help="Directory containing videos to compress"),
    config_path: Optional[Path] = typer.Option(Path("conf/vbc.yaml"), "--config", "-c", help="Path to YAML config"),
    threads: Optional[int] = typer.Option(None, "--threads", "-t", help="Override number of threads"),
    cq: Optional[int] = typer.Option(None, "--cq", help="Override constant quality (0-63)"),
    gpu: Optional[bool] = typer.Option(None, "--gpu/--cpu", help="Enable/disable GPU acceleration")
):
    """Batch compress videos in a directory with interactive UI."""
    if not input_dir.exists():
        typer.secho(f"Error: Directory {input_dir} does not exist.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    try:
        config = load_config(config_path)
        if threads: config.general.threads = threads
        if cq: config.general.cq = cq
        if gpu is not None: config.general.gpu = gpu
        
        bus = EventBus()
        ui_state = UIState()
        ui_state.current_threads = config.general.threads
        
        # UI Manager connects bus to ui_state
        ui_manager = UIManager(bus, ui_state)
        
        # Listen for thread changes to update UI state
        @bus.subscribe(ThreadControlEvent)
        def on_thread_change(e: ThreadControlEvent):
            with ui_state._lock:
                new_val = ui_state.current_threads + e.change
                ui_state.current_threads = max(1, min(16, new_val))

        @bus.subscribe(RequestShutdown)
        def on_shutdown(e: RequestShutdown):
            with ui_state._lock:
                ui_state.shutdown_requested = True

        # Components
        scanner = FileScanner(
            extensions=config.general.extensions,
            min_size_bytes=config.general.min_size_bytes
        )
        exif = ExifToolAdapter()
        ffprobe = FFprobeAdapter()
        ffmpeg = FFmpegAdapter(event_bus=bus)
        
        orchestrator = Orchestrator(
            config=config,
            event_bus=bus,
            file_scanner=scanner,
            exif_adapter=exif,
            ffprobe_adapter=ffprobe,
            ffmpeg_adapter=ffmpeg
        )
        
        keyboard = KeyboardListener(bus)
        dashboard = Dashboard(ui_state)
        
        # Start runtime
        keyboard.start()
        
        with dashboard.start():
            orchestrator.run(input_dir)
            
        keyboard.stop()
        typer.echo("\nProcessing complete.")
        
    except Exception as e:
        typer.secho(f"Fatal Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
