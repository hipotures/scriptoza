#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table


AUDIO_LEAD_IN_SECONDS = 3.0
AUDIO_TAIL_SECONDS = 3.0
VIDEO_CODEC = "libx264"
VIDEO_CRF = 18
VIDEO_PRESET = "slow"
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "192k"
OUTPUT_SUFFIX = "follow_audio"
OVERWRITE_OUTPUT = False
FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"

console = Console()


@dataclass(frozen=True)
class IdentityPoint:
    t: float
    x: float
    y: float


@dataclass(frozen=True)
class IdentityPath:
    source_path: Path
    source_width: int
    source_height: int
    points: tuple[IdentityPoint, ...]


@dataclass(frozen=True)
class RenderTiming:
    source_start: float
    source_end: float
    source_duration: float
    audio_duration: float
    final_duration: float
    speed_factor: float


@dataclass(frozen=True)
class RenderOptions:
    audio_lead_in_seconds: float = AUDIO_LEAD_IN_SECONDS
    audio_tail_seconds: float = AUDIO_TAIL_SECONDS
    video_codec: str = VIDEO_CODEC
    video_crf: int = VIDEO_CRF
    video_preset: str = VIDEO_PRESET
    audio_codec: str = AUDIO_CODEC
    audio_bitrate: str = AUDIO_BITRATE
    output_suffix: str = OUTPUT_SUFFIX
    overwrite_output: bool = OVERWRITE_OUTPUT
    ffmpeg_bin: str = FFMPEG_BIN
    ffprobe_bin: str = FFPROBE_BIN


def parse_resolution(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", value)
    if not match:
        raise ValueError("Resolution must use WIDTHxHEIGHT format, for example 1080x1920")

    width = int(match.group(1))
    height = int(match.group(2))
    if width <= 0 or height <= 0:
        raise ValueError("Resolution dimensions must be positive")
    if width % 2 or height % 2:
        raise ValueError("Resolution dimensions must be even numbers")
    return width, height


def load_identity_path(path: Path) -> IdentityPath:
    if not path.is_file():
        raise FileNotFoundError(f"Identity JSON does not exist: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Identity JSON must contain an object")
    if data.get("format") != "identity-path-v1":
        raise ValueError("Identity JSON format must be identity-path-v1")
    if data.get("time_unit") != "seconds":
        raise ValueError("Identity JSON time_unit must be seconds")
    if data.get("coordinate_space") != "source_pixels_top_left_origin":
        raise ValueError("Identity JSON coordinate_space must be source_pixels_top_left_origin")

    source = data.get("source")
    if not isinstance(source, dict):
        raise ValueError("Identity JSON source must be an object")

    source_uri = source.get("uri")
    if not isinstance(source_uri, str) or not source_uri:
        raise ValueError("Identity JSON source.uri must be a non-empty string")

    source_width = _positive_int(source.get("width"), "source.width")
    source_height = _positive_int(source.get("height"), "source.height")
    points = _load_points(data.get("points"))

    return IdentityPath(
        source_path=_uri_to_path(source_uri),
        source_width=source_width,
        source_height=source_height,
        points=points,
    )


def calculate_timing(
    identity: IdentityPath,
    audio_duration: float,
    *,
    audio_lead_in_seconds: float = AUDIO_LEAD_IN_SECONDS,
    audio_tail_seconds: float = AUDIO_TAIL_SECONDS,
) -> RenderTiming:
    if not math.isfinite(audio_duration) or audio_duration <= 0:
        raise ValueError("Audio duration must be a positive finite number")
    _validate_non_negative_seconds(audio_lead_in_seconds, "audio lead-in")
    _validate_non_negative_seconds(audio_tail_seconds, "audio tail")

    source_start = identity.points[0].t
    source_end = identity.points[-1].t
    source_duration = source_end - source_start
    if source_duration <= 0:
        raise ValueError("Identity path source duration must be greater than zero")

    final_duration = audio_lead_in_seconds + audio_duration + audio_tail_seconds
    if final_duration <= 0:
        raise ValueError("Final duration must be greater than zero")

    return RenderTiming(
        source_start=source_start,
        source_end=source_end,
        source_duration=source_duration,
        audio_duration=audio_duration,
        final_duration=final_duration,
        speed_factor=source_duration / final_duration,
    )


def build_crop_expression(
    *,
    points: tuple[IdentityPoint, ...],
    axis: str,
    crop_size: int,
    source_size_symbol: str,
) -> str:
    center_expression = _build_center_expression(points, axis)
    half_crop = crop_size / 2
    return f"clip(({center_expression})-{_fmt(half_crop)}\\,0\\,{source_size_symbol}-{crop_size})"


def build_filter_complex(
    *,
    identity: IdentityPath,
    target_width: int,
    target_height: int,
    timing: RenderTiming,
    audio_lead_in_seconds: float = AUDIO_LEAD_IN_SECONDS,
    audio_tail_seconds: float = AUDIO_TAIL_SECONDS,
) -> str:
    relative_points = tuple(
        IdentityPoint(t=point.t - timing.source_start, x=point.x, y=point.y)
        for point in identity.points
    )
    x_expression = build_crop_expression(
        points=relative_points,
        axis="x",
        crop_size=target_width,
        source_size_symbol="iw",
    )
    y_expression = build_crop_expression(
        points=relative_points,
        axis="y",
        crop_size=target_height,
        source_size_symbol="ih",
    )
    lead_ms = int(round(audio_lead_in_seconds * 1000))
    video_chain = (
        f"[0:v]trim=start={_fmt(timing.source_start)}:end={_fmt(timing.source_end)},"
        f"setpts=PTS-STARTPTS,"
        f"crop=w={target_width}:h={target_height}:x='{x_expression}':y='{y_expression}',"
        f"setpts=PTS/{_fmt(timing.speed_factor)}[v]"
    )
    audio_chain = (
        f"[1:a]asetpts=PTS-STARTPTS,"
        f"adelay={lead_ms}:all=1,"
        f"apad=pad_dur={_fmt(audio_tail_seconds)},"
        f"atrim=duration={_fmt(timing.final_duration)}[a]"
    )
    return f"{video_chain};{audio_chain}"


def build_ffmpeg_command(
    *,
    identity: IdentityPath,
    audio_path: Path,
    output_path: Path,
    target_width: int,
    target_height: int,
    timing: RenderTiming,
    options: RenderOptions = RenderOptions(),
) -> list[str]:
    return [
        options.ffmpeg_bin,
        "-hide_banner",
        "-v",
        "error",
        "-y" if options.overwrite_output else "-n",
        "-i",
        str(identity.source_path),
        "-i",
        str(audio_path),
        "-filter_complex",
        build_filter_complex(
            identity=identity,
            target_width=target_width,
            target_height=target_height,
            timing=timing,
            audio_lead_in_seconds=options.audio_lead_in_seconds,
            audio_tail_seconds=options.audio_tail_seconds,
        ),
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        options.video_codec,
        "-crf",
        str(options.video_crf),
        "-preset",
        options.video_preset,
        "-c:a",
        options.audio_codec,
        "-b:a",
        options.audio_bitrate,
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_path),
    ]


def probe_duration(path: Path, ffprobe_bin: str = FFPROBE_BIN) -> float:
    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "ffprobe failed"
        raise RuntimeError(f"Cannot read duration for {path}: {message}")
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"Cannot parse duration for {path}: {result.stdout.strip()}") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError(f"Invalid duration for {path}: {duration}")
    return duration


def build_progress_columns() -> tuple[object, ...]:
    return (
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("ETA"),
        TimeRemainingColumn(),
    )


def run_ffmpeg(command: list[str], final_duration: float) -> None:
    total_ms = max(1, int(round(final_duration * 1000)))
    with Progress(
        *build_progress_columns(),
        expand=False,
        console=console,
    ) as progress:
        task = progress.add_task("Rendering video...".ljust(25), total=total_ms)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if process.stdout is not None:
            for line in process.stdout:
                key, separator, value = line.strip().partition("=")
                if separator:
                    current_ms = _progress_value_to_ms(key, value)
                    if current_ms is not None:
                        progress.update(task, completed=min(current_ms, total_ms))

        stderr = process.stderr.read() if process.stderr is not None else ""
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(stderr.strip() or f"ffmpeg failed with exit code {return_code}")
        progress.update(task, completed=total_ms)


def default_output_path(
    source_path: Path,
    target_width: int,
    target_height: int,
    output_suffix: str = OUTPUT_SUFFIX,
) -> Path:
    return Path.cwd() / f"{source_path.stem}_{target_width}x{target_height}_{output_suffix}.mp4"


def render_summary(
    *,
    identity: IdentityPath,
    audio_path: Path,
    output_path: Path,
    target_width: int,
    target_height: int,
    timing: RenderTiming,
    options: RenderOptions = RenderOptions(),
) -> None:
    console.print(Panel.fit("[bold cyan]Dynamic Follow Crop[/bold cyan]", border_style="cyan"))
    table = Table(title="Render settings", expand=False)
    table.add_column("Item", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")
    table.add_row("Source video", str(identity.source_path))
    table.add_row("Audio file", str(audio_path))
    table.add_row("Output file", str(output_path))
    table.add_row("Source resolution", f"{identity.source_width}x{identity.source_height}")
    table.add_row("Target crop", f"{target_width}x{target_height}")
    table.add_row("Source segment", f"{timing.source_start:.3f}s to {timing.source_end:.3f}s")
    table.add_row("Source duration", f"{timing.source_duration:.3f}s")
    table.add_row("Audio duration", f"{timing.audio_duration:.3f}s")
    table.add_row("Final duration", f"{timing.final_duration:.3f}s")
    table.add_row("Speed factor", f"{timing.speed_factor:.6f}x")
    table.add_row("Audio lead-in", f"{options.audio_lead_in_seconds:.3f}s")
    table.add_row("Audio tail", f"{options.audio_tail_seconds:.3f}s")
    table.add_row("Quality", f"{options.video_codec}, CRF {options.video_crf}, preset {options.video_preset}")
    table.add_row("Audio encoding", f"{options.audio_codec}, {options.audio_bitrate}")
    console.print(table)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a dynamic crop from an identity-path JSON and fit it to an external audio file."
    )
    parser.add_argument("identity_json", type=Path, help="Path to identity-path-v1 JSON")
    parser.add_argument("audio_file", type=Path, help="Path to the audio file")
    parser.add_argument("resolution", help="Target crop resolution, for example 1080x1920")
    parser.add_argument("output_file", nargs="?", type=Path, help="Output video path")
    parser.add_argument("--audio-lead-in", type=float, default=AUDIO_LEAD_IN_SECONDS, help="Seconds of silence before audio starts")
    parser.add_argument("--audio-tail", type=float, default=AUDIO_TAIL_SECONDS, help="Seconds of padding after audio ends")
    parser.add_argument("--video-codec", default=VIDEO_CODEC, help="FFmpeg video codec")
    parser.add_argument("--crf", type=int, default=VIDEO_CRF, help="Video CRF quality value")
    parser.add_argument("--preset", default=VIDEO_PRESET, help="Video encoder preset")
    parser.add_argument("--audio-codec", default=AUDIO_CODEC, help="FFmpeg audio codec")
    parser.add_argument("--audio-bitrate", default=AUDIO_BITRATE, help="Audio bitrate")
    parser.add_argument("--output-suffix", default=OUTPUT_SUFFIX, help="Suffix for the default output filename")
    parser.add_argument("--overwrite", action="store_true", default=OVERWRITE_OUTPUT, help="Overwrite existing output file")
    parser.add_argument("--ffmpeg-bin", default=FFMPEG_BIN, help="ffmpeg executable path or name")
    parser.add_argument("--ffprobe-bin", default=FFPROBE_BIN, help="ffprobe executable path or name")
    return parser


def options_from_args(args: argparse.Namespace) -> RenderOptions:
    _validate_non_negative_seconds(args.audio_lead_in, "audio lead-in")
    _validate_non_negative_seconds(args.audio_tail, "audio tail")
    if args.crf < 0:
        raise ValueError("CRF must be zero or greater")
    return RenderOptions(
        audio_lead_in_seconds=args.audio_lead_in,
        audio_tail_seconds=args.audio_tail,
        video_codec=args.video_codec,
        video_crf=args.crf,
        video_preset=args.preset,
        audio_codec=args.audio_codec,
        audio_bitrate=args.audio_bitrate,
        output_suffix=args.output_suffix,
        overwrite_output=args.overwrite,
        ffmpeg_bin=args.ffmpeg_bin,
        ffprobe_bin=args.ffprobe_bin,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        options = options_from_args(args)
        ensure_tool_available(options.ffmpeg_bin)
        ensure_tool_available(options.ffprobe_bin)
        identity_json = args.identity_json.expanduser()
        audio_path = args.audio_file.expanduser()
        target_width, target_height = parse_resolution(args.resolution)
        identity = load_identity_path(identity_json)
        validate_inputs(identity_json, identity, audio_path, target_width, target_height)
        output_path = (
            args.output_file.expanduser()
            if args.output_file is not None
            else default_output_path(identity.source_path, target_width, target_height, options.output_suffix)
        )
        validate_output_path(output_path, options.overwrite_output)
        timing = calculate_timing(
            identity,
            probe_duration(audio_path, options.ffprobe_bin),
            audio_lead_in_seconds=options.audio_lead_in_seconds,
            audio_tail_seconds=options.audio_tail_seconds,
        )
        command = build_ffmpeg_command(
            identity=identity,
            audio_path=audio_path,
            output_path=output_path,
            target_width=target_width,
            target_height=target_height,
            timing=timing,
            options=options,
        )
        render_summary(
            identity=identity,
            audio_path=audio_path,
            output_path=output_path,
            target_width=target_width,
            target_height=target_height,
            timing=timing,
            options=options,
        )
        run_ffmpeg(command, timing.final_duration)
        console.print(f"[bold green]Done:[/bold green] {output_path}")
        return 0
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/yellow]")
        return 130
    except Exception as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return 1


def ensure_tool_available(name: str) -> None:
    if shutil.which(name) is None:
        raise FileNotFoundError(f"{name} was not found in PATH")


def validate_inputs(
    identity_json: Path,
    identity: IdentityPath,
    audio_path: Path,
    target_width: int,
    target_height: int,
) -> None:
    if not identity_json.is_file():
        raise FileNotFoundError(f"Identity JSON does not exist: {identity_json}")
    if not identity.source_path.is_file():
        raise FileNotFoundError(f"Source video does not exist: {identity.source_path}")
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {audio_path}")
    if target_width > identity.source_width or target_height > identity.source_height:
        raise ValueError(
            f"Target crop {target_width}x{target_height} is larger than source "
            f"{identity.source_width}x{identity.source_height}"
        )


def validate_output_path(path: Path, overwrite_output: bool = OVERWRITE_OUTPUT) -> None:
    if path.exists() and not overwrite_output:
        raise FileExistsError(f"Output file already exists: {path}")
    if not path.parent.exists():
        raise FileNotFoundError(f"Output directory does not exist: {path.parent}")


def _load_points(value: object) -> tuple[IdentityPoint, ...]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("Identity JSON points must contain at least two points")

    points: list[IdentityPoint] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"Point {index} must be an object")
        points.append(
            IdentityPoint(
                t=_finite_float(item.get("t"), f"points[{index}].t"),
                x=_finite_float(item.get("x"), f"points[{index}].x"),
                y=_finite_float(item.get("y"), f"points[{index}].y"),
            )
        )

    points.sort(key=lambda point: point.t)
    for previous, current in zip(points, points[1:]):
        if current.t <= previous.t:
            raise ValueError("Identity JSON point times must be unique")
    return tuple(points)


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Identity JSON {name} must be a positive integer")
    return value


def _finite_float(value: object, name: str) -> float:
    if not isinstance(value, int | float):
        raise ValueError(f"Identity JSON {name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Identity JSON {name} must be finite")
    return result


def _validate_non_negative_seconds(value: float, name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a non-negative finite number")


def _uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        if parsed.netloc not in ("", "localhost"):
            raise ValueError(f"Unsupported file URI host: {parsed.netloc}")
        return Path(unquote(parsed.path))
    if parsed.scheme:
        raise ValueError(f"Unsupported source URI scheme: {parsed.scheme}")
    return Path(uri).expanduser()


def _build_center_expression(points: tuple[IdentityPoint, ...], axis: str) -> str:
    if axis not in ("x", "y"):
        raise ValueError("Axis must be x or y")
    if len(points) < 2:
        raise ValueError("At least two points are required")

    expression = _fmt(getattr(points[-1], axis))
    for index in range(len(points) - 2, -1, -1):
        start = points[index]
        end = points[index + 1]
        duration = end.t - start.t
        if duration <= 0:
            raise ValueError("Point times must be strictly increasing")
        start_value = getattr(start, axis)
        end_value = getattr(end, axis)
        segment = (
            f"{_fmt(start_value)}+({_fmt(end_value)}-{_fmt(start_value)})"
            f"*(t-{_fmt(start.t)})/{_fmt(duration)}"
        )
        expression = f"if(lte(t\\,{_fmt(end.t)})\\,{segment}\\,{expression})"
    return expression


def _progress_value_to_ms(key: str, value: str) -> int | None:
    if key in ("out_time_us", "out_time_ms"):
        try:
            return int(int(value) / 1000)
        except ValueError:
            return None
    if key == "out_time":
        return _timestamp_to_ms(value)
    return None


def _timestamp_to_ms(value: str) -> int | None:
    match = re.fullmatch(r"(\d+):(\d+):(\d+(?:\.\d+)?)", value)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return int(round(((hours * 60 + minutes) * 60 + seconds) * 1000))


def _fmt(value: float) -> str:
    return f"{value:.6f}"


if __name__ == "__main__":
    sys.exit(main())
