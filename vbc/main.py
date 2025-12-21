import typer
import threading
import warnings
from pathlib import Path
from typing import Optional, List

# Silence all warnings (especially from pyexiftool) to prevent UI glitches
warnings.filterwarnings("ignore")
from vbc.config.loader import load_config
from vbc.infrastructure.logging import setup_logging
from vbc.infrastructure.event_bus import EventBus
from vbc.infrastructure.file_scanner import FileScanner
from vbc.infrastructure.exif_tool import ExifToolAdapter
from vbc.infrastructure.ffprobe import FFprobeAdapter
from vbc.infrastructure.ffmpeg import FFmpegAdapter
from vbc.infrastructure.housekeeping import HousekeepingService
from vbc.pipeline.orchestrator import Orchestrator
from vbc.ui.state import UIState
from vbc.ui.manager import UIManager
from vbc.ui.dashboard import Dashboard
from vbc.ui.keyboard import KeyboardListener, ThreadControlEvent, RequestShutdown
from vbc.domain.events import (
    HardwareCapabilityExceeded, JobStarted, JobCompleted, JobFailed, DiscoveryFinished
)

app = typer.Typer(help="VBC (Video Batch Compression) - Modular Version")

@app.command()
def compress(
    input_dir: Path = typer.Argument(..., help="Directory containing videos to compress"),
    config_path: Optional[Path] = typer.Option(Path("conf/vbc.yaml"), "--config", "-c", help="Path to YAML config"),
    threads: Optional[int] = typer.Option(None, "--threads", "-t", help="Override number of threads"),
    cq: Optional[int] = typer.Option(None, "--cq", help="Override constant quality (0-63)"),
    gpu: Optional[bool] = typer.Option(None, "--gpu/--cpu", help="Enable/disable GPU acceleration"),
    clean_errors: bool = typer.Option(False, "--clean-errors", help="Remove existing .err markers and retry"),
    skip_av1: bool = typer.Option(False, "--skip-av1", help="Skip files already encoded in AV1"),
    min_size: Optional[int] = typer.Option(None, "--min-size", help="Minimum input size in bytes to process"),
    debug: bool = typer.Option(False, "--debug/--no-debug", help="Enable verbose debug logging")
):
    """Batch compress videos in a directory with full feature parity."""
    if not input_dir.exists():
        typer.secho(f"Error: Directory {input_dir} does not exist.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    try:
        config = load_config(config_path)
        # Apply CLI overrides
        if threads: config.general.threads = threads
        if cq: config.general.cq = cq
        if gpu is not None: config.general.gpu = gpu
        if clean_errors: config.general.clean_errors = True
        if skip_av1: config.general.skip_av1 = True
        if min_size is not None: config.general.min_size_bytes = min_size
        if debug: config.general.debug = True

        # Setup output directory and logging FIRST
        output_dir = input_dir.with_name(f"{input_dir.name}_out")
        logger = setup_logging(output_dir, debug=config.general.debug)
        logger.info(f"VBC started: input={input_dir}, output={output_dir}")
        logger.info(f"Config: threads={config.general.threads}, cq={config.general.cq}, gpu={config.general.gpu}, debug={config.general.debug}")

        bus = EventBus()
        ui_state = UIState()
        ui_state.current_threads = config.general.threads
        
        # Housekeeping (Cleanup stale files)
        housekeeper = HousekeepingService()
        housekeeper.cleanup_temp_files(input_dir)
        if config.general.clean_errors:
            # Also cleanup in output dir if it exists
            output_dir = input_dir.with_name(f"{input_dir.name}_out")
            if output_dir.exists():
                housekeeper.cleanup_error_markers(output_dir)
        
        ui_manager = UIManager(bus, ui_state)

        # Components
        scanner = FileScanner(
            extensions=config.general.extensions,
            min_size_bytes=config.general.min_size_bytes
        )
        exif = ExifToolAdapter()
        exif.et.run()  # Start ExifTool ONCE before processing
        logger.info("ExifTool started")

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
        
        keyboard.start()
        try:
            with dashboard:
                orchestrator.run(input_dir)
        finally:
            keyboard.stop()
            # Cleanup ExifTool
            if exif.et.running:
                exif.et.terminate()
                logger.info("ExifTool terminated")

    except KeyboardInterrupt:
        typer.echo("\nInterrupted by user")
        raise typer.Exit(code=130)

    except Exception as e:
        with open("error.log", "a") as f:
            import traceback
            traceback.print_exc(file=f)
        typer.secho(f"Fatal Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()