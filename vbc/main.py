import typer
from pathlib import Path
from typing import Optional
from vbc.config.loader import load_config

app = typer.Typer(help="VBC (Video Batch Compression) - Modular Version")

@app.command()
def compress(
    input_dir: Path = typer.Argument(..., help="Directory containing videos to compress"),
    config_path: Optional[Path] = typer.Option(Path("conf/vbc.yaml"), "--config", "-c", help="Path to YAML config"),
    threads: Optional[int] = typer.Option(None, "--threads", "-t", help="Override number of threads"),
    cq: Optional[int] = typer.Option(None, "--cq", help="Override constant quality (0-63)"),
    gpu: Optional[bool] = typer.Option(None, "--gpu/--cpu", help="Enable/disable GPU acceleration")
):
    """Batch compress videos in a directory."""
    typer.echo(f"Initializing VBC for: {input_dir}")
    
    try:
        config = load_config(config_path)
        # Apply overrides
        if threads: config.general.threads = threads
        if cq: config.general.cq = cq
        if gpu is not None: config.general.gpu = gpu
        
        typer.echo(f"Config loaded successfully. Threads: {config.general.threads}, CQ: {config.general.cq}")
        typer.echo("Modular pipeline scaffold ready. Logic implementation follows in next tracks.")
        
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
