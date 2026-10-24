#!/usr/bin/env python3
"""Convert WAV files found under a directory to high-quality VBR MP3 files."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
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

console = Console()

DURATION_TOLERANCE_SECONDS = 1.0
APPROX_VBR_KBPS = (245, 225, 190, 175, 165, 130, 115, 100, 85, 65)


class ConversionError(Exception):
    pass


def find_wav_files(root: Path) -> list[Path]:
    wavs: list[Path] = []
    for directory, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() == ".wav" and path.is_file() and not path.is_symlink():
                wavs.append(path)
    return sorted(wavs)


def next_available_path(path: Path, reserved: set[Path]) -> Path:
    candidate = path
    counter = 1
    while candidate in reserved or os.path.lexists(candidate):
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        counter += 1
    return candidate


def plan_targets(wavs: list[Path]) -> list[tuple[Path, Path]]:
    reserved: set[Path] = set()
    plan: list[tuple[Path, Path]] = []
    for wav in wavs:
        target = next_available_path(wav.with_suffix(".mp3"), reserved)
        reserved.add(target)
        plan.append((wav, target))
    return plan


def probe_audio(path: Path) -> tuple[str | None, float | None, int | None]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name:format=duration,bit_rate",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None, None, None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, None, None
    streams = data.get("streams") or []
    codec = streams[0].get("codec_name") if streams else None
    try:
        duration = float(data["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        duration = None
    try:
        bitrate = round(int(data["format"]["bit_rate"]) / 1000)
    except (KeyError, ValueError, TypeError):
        bitrate = None
    return codec, duration, bitrate


def encode_to_temp(wav: Path, quality: int) -> tuple[Path, int | None]:
    handle, temp_name = tempfile.mkstemp(prefix=".wav2mp3.", suffix=".mp3", dir=wav.parent)
    os.close(handle)
    temp = Path(temp_name)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(wav),
                "-map", "0:a:0", "-vn", "-map_metadata", "0",
                "-c:a", "libmp3lame", "-q:a", str(quality),
                "-id3v2_version", "3", str(temp),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ConversionError(f"ffmpeg failed: {result.stderr.strip() or result.returncode}")
        bitrate = verify_mp3(wav, temp)
        shutil.copymode(wav, temp)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return temp, bitrate


def verify_mp3(wav: Path, mp3: Path) -> int | None:
    if mp3.stat().st_size == 0:
        raise ConversionError("output file is empty")
    codec, duration, bitrate = probe_audio(mp3)
    if codec != "mp3":
        raise ConversionError(f"output has no valid MP3 stream (codec: {codec})")
    _source_codec, source_duration, _source_bitrate = probe_audio(wav)
    if source_duration is not None and duration is not None:
        if abs(source_duration - duration) > DURATION_TOLERANCE_SECONDS:
            raise ConversionError(
                f"duration mismatch: source {source_duration:.2f}s, output {duration:.2f}s"
            )
    return bitrate


def publish(temp: Path, wav: Path) -> Path:
    desired = wav.with_suffix(".mp3")
    target = desired
    counter = 1
    while True:
        try:
            os.close(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            break
        except FileExistsError:
            target = desired.with_name(f"{desired.stem}_{counter}{desired.suffix}")
            counter += 1
    try:
        os.replace(temp, target)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def convert(wav: Path, quality: int) -> tuple[Path, int | None]:
    temp, bitrate = encode_to_temp(wav, quality)
    try:
        return publish(temp, wav), bitrate
    finally:
        temp.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Recursively convert WAV files to VBR MP3 next to the originals. "
            "Existing files are never overwritten (name_1.mp3, name_2.mp3, ...) and "
            "WAV files are never deleted. Dry run by default."
        )
    )
    parser.add_argument("path", nargs="?", type=Path, default=Path("."), help="Directory to scan (default: current directory)")
    parser.add_argument("--run", action="store_true", help="Convert files. Without it only the plan is printed")
    parser.add_argument(
        "-q",
        "--quality",
        type=int,
        choices=range(10),
        default=0,
        metavar="0-9",
        help="LAME VBR quality, 0 is best (default: 0)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root: Path = args.path.expanduser()

    if not root.is_dir():
        console.print(f"[red]Error: {root} is not a directory.[/red]")
        return 1
    if args.run:
        missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
        if missing:
            console.print(f"[red]Error: missing tool(s): {', '.join(missing)}[/red]")
            return 1
    else:
        console.print("[bold yellow]DRY RUN: no files will be created. Use --run to convert.[/bold yellow]")

    console.print(
        f"Encoding: MP3 VBR quality {args.quality} "
        f"(libmp3lame -q:a {args.quality}, typically ~{APPROX_VBR_KBPS[args.quality]} kb/s)"
    )

    wavs = find_wav_files(root)
    if not wavs:
        console.print("[yellow]No WAV files found.[/yellow]")
        return 0

    plan = plan_targets(wavs)
    converted = 0
    bitrates: list[int] = []
    failed: list[tuple[Path, str]] = []

    if not args.run:
        for wav, target in plan:
            console.print(f"  {wav} -> {target}", highlight=False, markup=False)
    else:
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
        task_id = progress.add_task("Converting WAV files".ljust(25), total=len(plan))
        try:
            with progress:
                for wav, _planned in plan:
                    try:
                        target, bitrate = convert(wav, args.quality)
                    except (ConversionError, OSError) as exc:
                        failed.append((wav, str(exc)))
                        progress.console.print(f"FAILED: {wav}: {exc}", style="red", highlight=False, markup=False)
                    else:
                        converted += 1
                        rate = f" [{bitrate} kb/s]" if bitrate else ""
                        if bitrate:
                            bitrates.append(bitrate)
                        progress.console.print(f"OK{rate}: {wav} -> {target}", highlight=False, markup=False)
                    progress.advance(task_id)
                progress.update(task_id, description="[bold green]Finished![/bold green]".ljust(25))
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
            return 130

    console.print("\n[bold]Summary[/bold]")
    console.print(f"  WAV files found: {len(wavs)}")
    if args.run:
        console.print(f"  Converted: {converted}")
        if bitrates:
            console.print(
                f"  Bitrate: avg {round(sum(bitrates) / len(bitrates))} kb/s "
                f"(min {min(bitrates)}, max {max(bitrates)})"
            )
        console.print(f"  Failed: {len(failed)}")
        console.print("  Original WAV files were left untouched.")
    else:
        console.print(f"  Planned conversions: {len(plan)}")
        console.print("[bold yellow]DRY RUN: nothing was changed. Use --run to convert.[/bold yellow]")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
