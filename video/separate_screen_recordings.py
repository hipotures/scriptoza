#!/usr/bin/env python3
"""Separate screen captures from renamed Android camera recordings."""

from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

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
from rich.text import Text


@dataclass(frozen=True)
class Entry:
    source: Path
    category: str
    destination: Path | None


MOVED_CATEGORIES = {"screen", "other"}
CAMERA_RATIO = 16 / 9
SCREEN_RATIO = 20 / 9
RATIO_TOLERANCE = 0.02


def aspect_ratio(tags: dict) -> float | None:
    """Long side over short side, so portrait and landscape are equal."""
    width, height = tags.get("ImageWidth"), tags.get("ImageHeight")
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return None
    if width <= 0 or height <= 0:
        return None
    return max(width, height) / min(width, height)


def classify(tags: dict) -> str:
    """GPS decides, and the aspect ratio must agree (camera 16:9, screen 20:9)."""
    if tags.get("Error") or tags.get("Warning") or not tags.get("AndroidVersion"):
        return "unknown"
    ratio = aspect_ratio(tags)
    if ratio is None:
        return "unknown"
    if tags.get("GPSCoordinates"):
        # Phone camera clips are stored rotated; an unrotated GPS clip is another source.
        rotation = tags.get("Rotation")
        if rotation in (90, 270):
            expected, label = CAMERA_RATIO, "camera"
        elif rotation == 0:
            expected, label = CAMERA_RATIO, "other"
        else:
            return "unknown"
    else:
        expected, label = SCREEN_RATIO, "screen"
    return label if abs(ratio - expected) <= RATIO_TOLERANCE * expected else "unknown"


def read_tags(
    paths: Sequence[Path], advance: Callable[[int], None] | None = None
) -> dict[Path, dict]:
    """Read metadata in bounded batches before any files are moved."""
    tags_by_path = {}
    for start in range(0, len(paths), 200):
        batch = paths[start : start + 200]
        result = subprocess.run(
            [
                "exiftool", "-json", "-n", "-ImageWidth", "-ImageHeight",
                "-CompressorID", "-GPSCoordinates", "-AndroidVersion", "-Rotation",
                *(str(path) for path in batch),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise ValueError(f"ExifTool scan failed: {result.stderr.strip()}")
        rows = json.loads(result.stdout)
        if not isinstance(rows, list):
            raise ValueError("ExifTool returned an invalid metadata list")
        for row in rows:
            if not isinstance(row, dict) or not row.get("SourceFile"):
                raise ValueError("ExifTool returned an invalid metadata entry")
            tags_by_path[Path(row["SourceFile"])] = row
        if any(path not in tags_by_path for path in batch):
            raise ValueError("ExifTool omitted files from the metadata scan")
        if advance:
            advance(len(batch))
    return tags_by_path


def validate_destination(path: Path, output: Path) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"Destination already exists: {path}")
    for parent in path.parents:
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError(f"Invalid destination directory: {parent}")
        if parent == output:
            break


def build_plan(
    folders: Sequence[Path], output: Path, progress: Progress | None = None
) -> list[Entry]:
    roots = [folder.expanduser().resolve(strict=True) for folder in folders]
    output = output.expanduser().resolve()
    if any(not root.is_dir() for root in roots):
        raise ValueError("Each input must be a directory")
    if len({root.name for root in roots}) != len(roots):
        raise ValueError("Input folders must have different names")
    for index, root in enumerate(roots):
        if output.is_relative_to(root) or root.is_relative_to(output):
            raise ValueError("Output and input folders must not overlap")
        for other in roots[index + 1 :]:
            if root.is_relative_to(other) or other.is_relative_to(root):
                raise ValueError("Input folders must not overlap")

    files: list[tuple[Path, Path]] = []
    for root in roots:
        def scan_error(error: OSError) -> None:
            raise error

        for directory, directories, names in os.walk(root, onerror=scan_error):
            directories[:] = sorted(
                name for name in directories
                if not (Path(directory) / name).is_symlink()
            )
            for name in sorted(names):
                path = Path(directory) / name
                if path.suffix.lower() == ".mp4" and not path.is_symlink() and path.is_file():
                    files.append((root, path))

    paths = [path for _, path in files]
    if progress is None:
        metadata = read_tags(paths)
    else:
        task = progress.add_task("Reading metadata".ljust(25), total=len(paths))
        metadata = read_tags(paths, lambda count: progress.advance(task, count))
    plan = []
    for root, path in files:
        category = classify(metadata[path])
        destination = (
            output / root.name / path.relative_to(root)
            if category in MOVED_CATEGORIES else None
        )
        if destination is not None:
            validate_destination(destination, output)
        plan.append(Entry(path, category, destination))
    return plan


def move_file(source: Path, destination: Path) -> None:
    """Move without overwriting; use an exclusive copy across filesystems."""
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Source is no longer a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination, follow_symlinks=False)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        with destination.open("xb") as target:
            try:
                with source.open("rb") as original:
                    shutil.copyfileobj(original, target)
                target.flush()
                os.fsync(target.fileno())
                shutil.copystat(source, destination)
            except BaseException:
                destination.unlink()
                raise
    source.unlink()


def make_progress(console: Console) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        expand=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="+", type=Path, help="Input folders to scan recursively")
    parser.add_argument("--output", required=True, type=Path, help="Destination for screen recordings")
    parser.add_argument("--run", action="store_true", help="Actually move files; without it only the plan is printed")
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve()
    dry_run = not args.run
    console = Console(highlight=False)
    if dry_run:
        console.print("[bold yellow]DRY RUN: no files will be moved. Use --run to apply the plan.[/bold yellow]")
    try:
        with make_progress(console) as progress:
            plan = build_plan(args.folders, output, progress)
        counts = Counter(entry.category for entry in plan)
        moves = [entry for entry in plan if entry.destination is not None]
        unknown = [entry for entry in plan if entry.category == "unknown"]
        if moves:
            title = "Screen recordings to move" if not dry_run else "Screen recordings that would be moved"
            console.print(f"\n[bold green]{title} ({len(moves)}):[/bold green]")
            for entry in moves:
                console.print(Text(f"  {entry.source}"))
                console.print(Text(f"    -> {entry.destination}", style="green"))
        if unknown:
            console.print(f"\n[bold yellow]Unrecognized, left in place ({len(unknown)}):[/bold yellow]")
            for entry in unknown:
                console.print(Text(f"  {entry.source}"))
        console.print()
        console.print(
            f"Summary: camera={counts['camera']}, screen={counts['screen']}, other={counts['other']}, "
            f"unknown={counts['unknown']}; mode={'dry-run' if dry_run else 'move'}",
            markup=False,
        )
        if dry_run:
            console.print("[bold yellow]DRY RUN: nothing was moved. Use --run to apply the plan.[/bold yellow]")
        else:
            with make_progress(console) as progress:
                task = progress.add_task("Moving screen recordings".ljust(25), total=len(moves))
                for entry in moves:
                    validate_destination(entry.destination, output)
                    move_file(entry.source, entry.destination)
                    progress.advance(task)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
