#!/usr/bin/env python3
"""Convert WAV files found under a directory to high-quality VBR MP3 files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
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
SOURCE_TAG = "wav2mp3_source"
MD5_TAG = "wav2mp3_source_md5"
APPROX_VBR_KBPS = (245, 225, 190, 175, 165, 130, 115, 100, 85, 65)


class ConversionError(Exception):
    pass


def find_files(root: Path, suffix: str) -> list[Path]:
    found: list[Path] = []
    for directory, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() == suffix and path.is_file() and not path.is_symlink():
                found.append(path)
    return sorted(found)


def find_wav_files(root: Path) -> list[Path]:
    return find_files(root, ".wav")


def next_available_path(path: Path, reserved: set[Path]) -> Path:
    candidate = path
    counter = 1
    while candidate in reserved or os.path.lexists(candidate):
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        counter += 1
    return candidate


def source_signature(wav: Path) -> str:
    return f"{wav.name}|{wav.stat().st_size}"


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provenance_args(wav: Path, quality: int) -> list[str]:
    tags = {
        SOURCE_TAG: source_signature(wav),
        MD5_TAG: md5_file(wav),
        "wav2mp3_settings": f"libmp3lame VBR -q:a {quality}, ~{APPROX_VBR_KBPS[quality]} kb/s typical",
        "wav2mp3_date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "encoded_by": "wav_to_mp3.py (Scriptoza)",
    }
    args: list[str] = []
    for key, value in tags.items():
        args.extend(["-metadata", f"{key}={value}"])
    return args


def read_provenance_tags(mp3: Path) -> dict[str, str]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", f"format_tags={SOURCE_TAG},{MD5_TAG}",
            "-of", "json", str(mp3),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    try:
        tags = json.loads(result.stdout).get("format", {}).get("tags", {})
    except json.JSONDecodeError:
        return {}
    return {key.lower(): value for key, value in tags.items()}


def build_converted_index(mp3s: list[Path], progress: Progress | None = None) -> dict[str, tuple[int | None, Path]]:
    index: dict[str, tuple[int | None, Path]] = {}
    task_id = progress.add_task("Reading MP3 tags".ljust(25), total=len(mp3s)) if progress else None
    for mp3 in mp3s:
        tags = read_provenance_tags(mp3)
        md5 = tags.get(MD5_TAG)
        if md5:
            try:
                size: int | None = int(tags.get(SOURCE_TAG, "").rsplit("|", 1)[1])
            except (IndexError, ValueError):
                size = None
            index.setdefault(md5, (size, mp3))
        if progress and task_id is not None:
            progress.advance(task_id)
    return index


def split_already_converted(
    wavs: list[Path],
    index: dict[str, tuple[int | None, Path]],
    progress: Progress | None = None,
) -> tuple[list[Path], list[tuple[Path, Path]]]:
    sizes = {size for size, _mp3 in index.values()}
    todo: list[Path] = []
    done: list[tuple[Path, Path]] = []
    task_id = progress.add_task("Checking WAV files".ljust(25), total=len(wavs)) if progress else None
    for wav in wavs:
        match = None
        if index and (None in sizes or wav.stat().st_size in sizes):
            match = index.get(md5_file(wav))
        if match:
            done.append((wav, match[1]))
        else:
            todo.append(wav)
        if progress and task_id is not None:
            progress.advance(task_id)
    return todo, done


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
                *provenance_args(wav, quality),
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


def make_progress(*, transient: bool = True) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        expand=False,
        transient=transient,
    )


def print_settings(root: Path, quality: int, count: int) -> None:
    rows = (
        ("Source", f"{root.resolve()} (recursive)"),
        ("WAV files found", str(count)),
        ("Encoder", f"libmp3lame, -q:a {quality}"),
        ("Bitrate mode", f"VBR, quality {quality} (0 = best), typically ~{APPROX_VBR_KBPS[quality]} kb/s"),
        ("Sample rate / channels", "kept from the source"),
        ("Tags", "ID3v2.3, metadata copied from the WAV plus wav2mp3_* provenance tags (source, MD5, settings, date)"),
        ("Output", "same directory, existing files never overwritten (_1, _2, ...)"),
        ("Verification", f"ffprobe: MP3 stream, duration within {DURATION_TOLERANCE_SECONDS:g}s of the source"),
        ("Re-runs", "WAVs whose MD5 matches an MP3 made by this script are skipped (renames do not matter)"),
        ("Originals", "WAV files are kept"),
    )
    console.print("\n[bold]Settings[/bold]")
    for label, value in rows:
        console.print(f"  {label + ':':<24}{value}", highlight=False, markup=False)
    console.print()


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
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        console.print(f"[red]Error: missing tool(s): {', '.join(missing)}[/red]")
        return 1
    if not args.run:
        console.print("[bold yellow]DRY RUN: no files will be created. Use --run to convert.[/bold yellow]")

    wavs = find_wav_files(root)
    if not wavs:
        console.print("[yellow]No WAV files found.[/yellow]")
        return 0

    print_settings(root, args.quality, len(wavs))

    with make_progress() as scan_progress:
        index = build_converted_index(find_files(root, ".mp3"), scan_progress)
        todo, already_done = split_already_converted(wavs, index, scan_progress)
    for wav, mp3 in already_done:
        console.print(f"SKIPPED (already converted): {wav} -> {mp3.name}", highlight=False, markup=False)
    plan = plan_targets(todo)
    if not plan:
        console.print("[yellow]Nothing to convert.[/yellow]")
    converted = 0
    bitrates: list[int] = []
    failed: list[tuple[Path, str]] = []

    if not args.run:
        for wav, target in plan:
            console.print(f"  {wav} -> {target}", highlight=False, markup=False)
    else:
        progress = make_progress(transient=False)
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
    console.print(f"  Skipped (already converted): {len(already_done)}")
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
