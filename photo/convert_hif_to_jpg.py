#!/usr/bin/env python3

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

DEFAULT_SCALE_PERCENT = 25
DEFAULT_JPEG_QUALITY = 95
SUPPORTED_EXTENSIONS = {".hif", ".heif"}

console = Console()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert HIF/HEIF files from the current directory to JPG files in a pX subdirectory."
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=DEFAULT_SCALE_PERCENT,
        help=f"Output size as percent of original resolution (default: {DEFAULT_SCALE_PERCENT})",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_JPEG_QUALITY,
        help=f"JPEG quality for ImageMagick backend (default: {DEFAULT_JPEG_QUALITY})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing JPG files in the target directory",
    )
    return parser.parse_args()


def detect_backend():
    if shutil.which("magick"):
        return "magick"
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    return None


def list_source_files(directory: Path):
    files = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS]
    files.sort()
    return files


def convert_with_magick(source: Path, destination: Path, scale: int, quality: int):
    command = [
        "magick",
        str(source),
        "-auto-orient",
        "-colorspace",
        "sRGB",
        "-filter",
        "Lanczos",
        "-resize",
        f"{scale}%",
        "-sampling-factor",
        "4:4:4",
        "-depth",
        "8",
        "-quality",
        str(quality),
        str(destination),
    ]
    subprocess.run(command, capture_output=True, text=True, check=True)


def convert_with_ffmpeg(source: Path, destination: Path, scale: int, overwrite: bool):
    overwrite_flag = "-y" if overwrite else "-n"
    scale_ratio = scale / 100
    command = [
        "ffmpeg",
        overwrite_flag,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vf",
        f"scale=trunc(iw*{scale_ratio}/2)*2:trunc(ih*{scale_ratio}/2)*2:flags=lanczos",
        "-pix_fmt",
        "yuvj444p",
        "-q:v",
        "1",
        str(destination),
    ]
    subprocess.run(command, capture_output=True, text=True, check=True)


def convert_file(source: Path, destination: Path, backend: str, scale: int, quality: int, overwrite: bool):
    if backend == "magick":
        convert_with_magick(source, destination, scale, quality)
        return
    if backend == "ffmpeg":
        convert_with_ffmpeg(source, destination, scale, overwrite)
        return
    raise RuntimeError("No supported backend available")


def build_summary_table(target_dir: Path, backend: str, converted: int, skipped: int, failed: int):
    table = Table(title="Conversion Summary", expand=False)
    table.add_column("Item", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Target directory", str(target_dir))
    table.add_row("Backend", backend)
    table.add_row("Converted", str(converted))
    table.add_row("Skipped", str(skipped))
    table.add_row("Failed", str(failed))
    return table


def main():
    args = parse_args()

    if not 1 <= args.scale <= 100:
        console.print("[red]Error: --scale must be between 1 and 100.[/red]")
        sys.exit(1)

    if not 1 <= args.quality <= 100:
        console.print("[red]Error: --quality must be between 1 and 100.[/red]")
        sys.exit(1)

    backend = detect_backend()
    if backend is None:
        console.print("[red]Error: install ImageMagick or ffmpeg to enable conversion.[/red]")
        sys.exit(1)

    current_dir = Path.cwd()
    target_dir = current_dir / f"p{args.scale}"
    target_dir.mkdir(exist_ok=True)

    source_files = list_source_files(current_dir)
    if not source_files:
        console.print("[yellow]No HIF/HEIF files found in the current directory.[/yellow]")
        return

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        expand=False,
    )

    converted = 0
    skipped = 0
    failed = 0

    with progress:
        task_id = progress.add_task("Converting HIF files".ljust(25), total=len(source_files))
        for source in source_files:
            destination = target_dir / f"{source.stem}.jpg"

            if destination.exists() and not args.overwrite:
                skipped += 1
                progress.advance(task_id)
                continue

            try:
                convert_file(source, destination, backend, args.scale, args.quality, args.overwrite)
                converted += 1
            except subprocess.CalledProcessError as error:
                failed += 1
                message = error.stderr.strip() or error.stdout.strip() or str(error)
                console.print(f"[red]Failed:[/red] {source.name} -> {message}")
            except Exception as error:
                failed += 1
                console.print(f"[red]Failed:[/red] {source.name} -> {error}")
            finally:
                progress.advance(task_id)

        progress.update(task_id, description="[bold green]Finished![/bold green]".ljust(25))

    console.print(build_summary_table(target_dir, backend, converted, skipped, failed))


if __name__ == "__main__":
    main()
