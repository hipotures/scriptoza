import typer
from pathlib import Path
from typing import Optional
from vbc.config.loader import load_config
from vbc.infrastructure.event_bus import EventBus
from vbc.infrastructure.file_scanner import FileScanner
from vbc.infrastructure.exif_tool import ExifToolAdapter
from vbc.infrastructure.ffprobe import FFprobeAdapter
from vbc.infrastructure.ffmpeg import FFmpegAdapter
from vbc.pipeline.orchestrator import Orchestrator
from vbc.domain.events import JobStarted, JobCompleted, JobFailed, DiscoveryStarted, DiscoveryFinished

app = typer.Typer(help="VBC (Video Batch Compression) - Modular Version")

def setup_ui(bus: EventBus):
    """Simple event-driven UI for verification."""
    @bus.subscribe(DiscoveryStarted)
    def on_discovery_start(e: DiscoveryStarted):
        typer.echo(f"Scanning directory: {e.directory}")

    @bus.subscribe(DiscoveryFinished)
    def on_discovery_finish(e: DiscoveryFinished):
        typer.echo(f"Found {e.files_found} files to process.")

    @bus.subscribe(JobStarted)
    def on_job_start(e: JobStarted):
        typer.echo(f"Starting: {e.job.source_file.path.name}")

    @bus.subscribe(JobCompleted)
    def on_job_complete(e: JobCompleted):
        typer.secho(f"Done: {e.job.source_file.path.name}", fg=typer.colors.GREEN)

    @bus.subscribe(JobFailed)
    def on_job_failed(e: JobFailed):
        typer.secho(f"Failed: {e.job.source_file.path.name} - {e.error_message}", fg=typer.colors.RED)

@app.command()
def compress(
    input_dir: Path = typer.Argument(..., help="Directory containing videos to compress"),
    config_path: Optional[Path] = typer.Option(Path("conf/vbc.yaml"), "--config", "-c", help="Path to YAML config"),
    threads: Optional[int] = typer.Option(None, "--threads", "-t", help="Override number of threads"),
    cq: Optional[int] = typer.Option(None, "--cq", help="Override constant quality (0-63)"),
    gpu: Optional[bool] = typer.Option(None, "--gpu/--cpu", help="Enable/disable GPU acceleration")
):
    """Batch compress videos in a directory."""
    if not input_dir.exists():
        typer.secho(f"Error: Directory {input_dir} does not exist.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    try:
        config = load_config(config_path)
        # Apply overrides
        if threads: config.general.threads = threads
        if cq: config.general.cq = cq
        if gpu is not None: config.general.gpu = gpu
        
        bus = EventBus()
        setup_ui(bus)
        
        # Instantiate adapters
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
        
        orchestrator.run(input_dir)
        typer.echo("Processing complete.")
        
    except Exception as e:
        typer.secho(f"Unexpected Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()