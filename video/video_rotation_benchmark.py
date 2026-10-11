#!/usr/bin/env python3
"""Benchmark vision models that vote on the rotation of sampled video frames."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

import requests
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

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
ANGLES = (0, 90, 180, 270)
UNDETERMINED = -1
EXCLUDED = frozenset({UNDETERMINED})
SIDEWAYS = frozenset({90, 270})
MIN_VOTES = 2
FIRST_FRACTION = 0.15
LAST_FRACTION = 0.85
DEFAULT_FRAME_COUNTS = (5, 7, 9)
DEFAULT_BASE_URL = "http://192.168.100.107:8080"
DEFAULT_MIN_AGREEMENT = 0.6
META_KEYS = ("model", "width", "max_tokens", "prompt_sha256", "apply_tag", "thinking", "thinking_tokens", "angle")
META_DEFAULTS = {"apply_tag": False, "thinking": False, "thinking_tokens": 0, "angle": False}
ANGLE_WINDOW = 30
DEFAULT_TOLERANCE = 45
DEFAULT_THINKING_TOKENS = 2048
TIMEOUT = 180
THINKING_TIMEOUT = 600

PROMPTS = {
    "top": """
Look at this video frame. Find where the TOP of the scene is in the image
(sky, ceiling, heads of people, tops of buildings).

Answer with exactly one number:

0   = the top of the scene is at the top edge of the image (upright)
90  = the top of the scene is at the LEFT edge of the image
180 = the top of the scene is at the bottom edge of the image (upside down)
270 = the top of the scene is at the RIGHT edge of the image
-1  = impossible to tell

Even if there are no people, infer the top from the whole scene.

Output only the number.
""",
    "clockwise": """
Look at this video frame and determine its visual orientation.

Your task is to determine what CLOCKWISE rotation must be applied to the
raw image so that the scene appears naturally upright.

Return exactly ONE of these values:

0
90
180
270
-1

Meaning:

0   = the image is already upright
90  = rotate image 90 degrees clockwise
180 = rotate image 180 degrees
270 = rotate image 270 degrees clockwise
-1  = impossible to determine orientation from this image

Use visual clues such as:
- people should stand upright
- faces should be upright
- buildings should be vertical
- text should be readable normally
- ground should be below the sky
- furniture and objects should obey gravity

Even if there are no people, infer orientation from the whole scene.

Do NOT explain your answer.
Do NOT output words.
Output exactly one number.
""",
}
PROMPTS["bearing"] = """
Look at this video frame. Find where the TOP of the scene is in the image
(sky, ceiling, heads of people, tops of buildings, tops of signs).

Give the direction of the top of the scene as a compass bearing inside the
image, in degrees clockwise from straight up:

0   = the top of the scene points straight up (the image is upright)
90  = the top of the scene points to the right
180 = the top of the scene points straight down (the image is upside down)
270 = the top of the scene points to the left

Use values in between when the scene is tilted, for example 45 for up-right
or 315 for up-left.

Answer with one integer from 0 to 345, rounded to the nearest multiple of 15.
If it is impossible to tell, answer -1.

Output only the number.
"""
DEFAULT_PROMPT = "top"

CONSOLE = Console()
ERROR_CONSOLE = Console(stderr=True)


class FrameError(RuntimeError):
    pass


class ServerUnreachable(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    cache_dir: Path
    url: str
    model: str
    prompt: str
    width: int
    max_tokens: int
    timeout: float
    apply_tag: bool
    thinking: bool
    thinking_tokens: int
    angle: bool = False


@dataclass(frozen=True)
class Verdict:
    counts: dict[int, int]
    undetermined: int
    invalid: int
    total: int
    winner: int | None
    agreement: float
    readable: int = 0


@dataclass
class Run:
    path: Path
    meta: dict
    frames: dict[tuple[str, float], dict]
    wall_seconds: float
    videos: dict[str, dict] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.meta.get("label", self.path.stem)


def frame_fractions(count: int) -> list[float]:
    if count < 1:
        raise ValueError("frame count must be at least 1")
    if count == 1:
        return [round((FIRST_FRACTION + LAST_FRACTION) / 2, 4)]
    step = (LAST_FRACTION - FIRST_FRACTION) / (count - 1)
    return [round(FIRST_FRACTION + step * index, 4) for index in range(count)]


def all_fractions(counts: Sequence[int]) -> list[float]:
    return sorted({fraction for count in counts for fraction in frame_fractions(count)})


def strip_thinking(content: str) -> str | None:
    if "</think>" in content:
        return content.rsplit("</think>", 1)[1]
    if "<think>" in content:
        return None
    return content


def parse_answer(content: str) -> int | None:
    text = str(content).strip()
    if text in {"-1", "0", "90", "180", "270"}:
        return int(text)
    matches = re.findall(r"(?<![\d.])(?:-1|270|180|90|0)(?!\d)", text)
    return int(matches[-1]) if matches else None


def parse_angle(content: str) -> int | None:
    text = str(content).strip()
    matches = re.findall(r"(?<![\d.])-?\d{1,3}(?![\d.])", text)
    if not matches:
        return None
    value = int(text) if re.fullmatch(r"-?\d{1,3}", text) else int(matches[-1])
    if value == UNDETERMINED:
        return value
    if 0 <= value <= 360:
        return value % 360
    return None


def bearing_to_correction(bearing: int | None) -> int | None:
    if bearing is None or bearing == UNDETERMINED:
        return bearing
    return (360 - bearing) % 360


def circular_distance(first: int, second: int) -> int:
    difference = abs(first - second) % 360
    return min(difference, 360 - difference)


def circular_mean(angles: Sequence[int]) -> int:
    x = sum(math.cos(math.radians(angle)) for angle in angles)
    y = sum(math.sin(math.radians(angle)) for angle in angles)
    return round(math.degrees(math.atan2(y, x))) % 360


def angle_tally(answers: Sequence[int | None], window: int = ANGLE_WINDOW) -> Verdict:
    valid = [answer for answer in answers if answer is not None and 0 <= answer < 360]
    clusters: list[list[int]] = []
    for center in sorted(set(valid)):
        members = [answer for answer in valid if circular_distance(answer, center) <= window]
        if not clusters or len(members) > len(clusters[0]):
            clusters = [members]
        elif len(members) == len(clusters[0]):
            clusters.append(members)
    winner, agreement, counts = None, 0.0, {}
    if clusters and len(clusters[0]) >= MIN_VOTES:
        first = circular_mean(clusters[0])
        if all(circular_distance(circular_mean(cluster), first) <= window for cluster in clusters):
            winner, agreement = first, len(clusters[0]) / len(valid)
            counts = {first: len(clusters[0])}
    return Verdict(
        counts=counts,
        undetermined=sum(1 for answer in answers if answer == UNDETERMINED),
        invalid=sum(1 for answer in answers if answer is None),
        total=len(answers),
        winner=winner,
        agreement=agreement,
        readable=len(valid),
    )


def tally(answers: Sequence[int | None]) -> Verdict:
    counts = Counter(answer for answer in answers if answer in ANGLES)
    winner, agreement = None, 0.0
    ranked = counts.most_common()
    if ranked:
        angle, votes = ranked[0]
        if votes >= MIN_VOTES and (len(ranked) == 1 or ranked[1][1] < votes):
            winner, agreement = angle, votes / sum(counts.values())
    return Verdict(
        counts=dict(counts),
        undetermined=sum(1 for answer in answers if answer == UNDETERMINED),
        invalid=sum(1 for answer in answers if answer is None),
        total=len(answers),
        winner=winner,
        agreement=agreement,
        readable=sum(counts.values()),
    )


def decide(verdict: Verdict, min_agreement: float) -> int | None:
    if verdict.winner is not None and verdict.agreement >= min_agreement:
        return verdict.winner
    return None


def parse_label(text: str) -> frozenset[int]:
    value = text.strip().lower()
    if value == "s":
        return SIDEWAYS
    if value in {"-1", "0", "90", "180", "270"}:
        return frozenset({int(value)})
    raise ValueError(f"invalid label {text!r}")


def label_text(label: frozenset[int]) -> str:
    return "s" if label == SIDEWAYS else str(next(iter(label)))


def load_labels(path: Path) -> dict[str, frozenset[int]]:
    labels: dict[str, frozenset[int]] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.rsplit(None, 1)
        if len(parts) < 2:
            continue
        try:
            labels[parts[0]] = parse_label(parts[1])
        except ValueError as error:
            raise ValueError(f"{path}:{number}: {error}") from error
    return labels


def judge(label: frozenset[int], predicted: int | None) -> str:
    if predicted is None:
        return "unsure"
    return "correct" if predicted in label else "wrong"


def judge_angle(label: frozenset[int], predicted: int | None, tolerance: int) -> str:
    if predicted is None:
        return "unsure"
    close = any(circular_distance(predicted, angle) <= tolerance for angle in label)
    return "correct" if close else "wrong"


def probe_video(path: Path) -> tuple[float, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream_side_data=rotation:format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        raise FrameError("cannot read video duration") from None
    if duration <= 0:
        raise FrameError("video has no duration")

    rotation = 0
    for stream in data.get("streams", []):
        for side_data in stream.get("side_data_list", []):
            if "rotation" in side_data:
                rotation = (-round(float(side_data["rotation"]))) % 360
    return duration, rotation


def extract_frame(path: Path, seconds: float, width: int, apply_tag: bool = False) -> bytes:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        *([] if apply_tag else ["-noautorotate"]), "-noaccurate_seek",
        "-ss", f"{seconds:.3f}", "-i", str(path),
        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "2",
        "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True, timeout=300)
    if result.returncode != 0 or not result.stdout:
        message = result.stderr.decode(errors="replace").strip()
        raise FrameError(message or "no frame decoded")
    return result.stdout


def cached_frame(settings: Settings, path: Path, fraction: float, seconds: float) -> bytes:
    cached = settings.cache_dir / f"{path.stem}_{fraction:.4f}.jpg"
    if cached.is_file():
        return cached.read_bytes()
    jpeg = extract_frame(path, seconds, settings.width, settings.apply_tag)
    partial = cached.with_name(cached.name + ".part")
    partial.write_bytes(jpeg)
    partial.replace(cached)
    return jpeg


def ask(session: requests.Session, settings: Settings, jpeg: bytes) -> tuple[str, str | None, int | None]:
    image = base64.b64encode(jpeg).decode("ascii")
    budget = settings.max_tokens + (settings.thinking_tokens if settings.thinking else 0)
    payload = {
        "model": settings.model,
        "temperature": 0,
        "max_tokens": budget,
        "chat_template_kwargs": {"enable_thinking": settings.thinking},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": settings.prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
                ],
            }
        ],
    }
    response = session.post(f"{settings.url}/v1/chat/completions", json=payload, timeout=settings.timeout)
    response.raise_for_status()
    data = response.json()
    choice = data["choices"][0]
    tokens = (data.get("usage") or {}).get("completion_tokens")
    return str(choice["message"].get("content") or ""), choice.get("finish_reason"), tokens


def query_frame(
    session: requests.Session,
    settings: Settings,
    path: Path,
    fraction: float,
    seconds: float,
) -> dict:
    record = {
        "type": "frame",
        "file": path.name,
        "fraction": fraction,
        "answer": None,
        "raw": None,
        "seconds": None,
        "error": None,
        "finish_reason": None,
        "completion_tokens": None,
    }
    started = time.monotonic()
    try:
        jpeg = cached_frame(settings, path, fraction, seconds)
    except (FrameError, subprocess.TimeoutExpired) as error:
        record["error"] = f"frame: {error}"
        return record
    record["extract_seconds"] = round(time.monotonic() - started, 3)

    started = time.monotonic()
    try:
        content, finish_reason, tokens = ask(session, settings, jpeg)
    except requests.Timeout:
        record["error"] = "timeout"
    except requests.ConnectionError as error:
        raise ServerUnreachable(str(error)) from error
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as error:
        record["error"] = f"{type(error).__name__}: {error}"
    else:
        record["raw"] = content
        record["finish_reason"] = finish_reason
        record["completion_tokens"] = tokens
        final = strip_thinking(content) if settings.thinking else content
        if final is None or (settings.thinking and finish_reason == "length"):
            record["truncated"] = True
        elif settings.angle:
            record["bearing"] = parse_angle(final)
            record["answer"] = bearing_to_correction(record["bearing"])
        else:
            record["answer"] = parse_answer(final)
    record["seconds"] = round(time.monotonic() - started, 3)
    return record


def load_run(path: Path) -> Run:
    meta: dict = {}
    frames: dict[tuple[str, float], dict] = {}
    videos: dict[str, dict] = {}
    wall_seconds = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record["type"] == "meta":
            meta = record
        elif record["type"] == "frame":
            frames[(record["file"], record["fraction"])] = record
        elif record["type"] == "video":
            videos[record["file"]] = record
        elif record["type"] == "run":
            wall_seconds += record["wall_seconds"]
    return Run(path=path, meta=meta, frames=frames, wall_seconds=wall_seconds, videos=videos)


def append_records(path: Path, records: Sequence[dict]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def video_verdict(run: Run, name: str, count: int) -> Verdict:
    answers = []
    for fraction in frame_fractions(count):
        record = run.frames.get((name, fraction))
        answers.append(record["answer"] if record else None)
    return angle_tally(answers) if run.meta.get("angle") else tally(answers)


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def format_number(value: float | None, template: str) -> str:
    return "-" if value is None else template.format(value)


def effective_label(run: Run, name: str, label: frozenset[int] | None) -> frozenset[int] | None:
    if label is None or label == EXCLUDED or not run.meta.get("apply_tag"):
        return label
    rotation = run.videos.get(name, {}).get("container_rotation")
    if rotation is None:
        return None
    return frozenset((angle - rotation) % 360 for angle in label)


def video_cell(
    run: Run,
    name: str,
    label: frozenset[int],
    count: int,
    min_agreement: float,
    tolerance: int,
) -> tuple[str, Verdict, int | None]:
    verdict = video_verdict(run, name, count)
    predicted = decide(verdict, min_agreement)
    if label == EXCLUDED:
        return "excluded", verdict, predicted
    if run.meta.get("angle"):
        return judge_angle(label, predicted, tolerance), verdict, predicted
    return judge(label, predicted), verdict, predicted


def summarize(
    run: Run,
    labels: dict[str, frozenset[int]],
    count: int,
    min_agreement: float,
    tolerance: int = DEFAULT_TOLERANCE,
) -> dict:
    stats = Counter()
    agreement_correct: list[float] = []
    agreement_wrong: list[float] = []
    errors: list[int] = []
    readable: list[int] = []
    cells: dict[str, tuple[str, Verdict, int | None]] = {}
    names = sorted({name for name, _ in run.frames})
    for name in names:
        label = effective_label(run, name, labels.get(name))
        if label is None:
            stats["unlabeled"] += 1
            continue
        outcome, verdict, predicted = video_cell(run, name, label, count, min_agreement, tolerance)
        cells[name] = (outcome, verdict, predicted)
        if outcome == "excluded":
            stats["excluded"] += 1
            continue
        stats["angle"] += 1
        stats[outcome] += 1
        readable.append(verdict.readable)
        if outcome == "correct":
            agreement_correct.append(verdict.agreement)
        elif outcome == "wrong":
            agreement_wrong.append(verdict.agreement)
        if run.meta.get("angle") and predicted is not None:
            errors.append(min(circular_distance(predicted, angle) for angle in label))

    wanted = set(frame_fractions(count))
    used = [r for r in run.frames.values() if r["fraction"] in wanted]
    latencies = [r["seconds"] for r in used if r["seconds"] is not None]
    scored = {name for name, cell in cells.items() if cell[0] != "excluded"}
    counted = [r for r in used if r["file"] in scored]
    stats["undetermined"] = sum(1 for r in counted if r["answer"] == UNDETERMINED)
    stats["invalid"] = sum(1 for r in counted if r["answer"] is None)
    return {
        "stats": stats,
        "agreement_correct": mean(agreement_correct),
        "agreement_wrong": mean(agreement_wrong),
        "latency": mean(latencies),
        "mean_error": mean(errors),
        "readable": mean(readable),
        "cells": cells,
    }


def render_summary(
    runs: Sequence[Run],
    labels: dict[str, frozenset[int]],
    counts: Sequence[int],
    min_agreement: float,
    details: bool,
    tolerance: int = DEFAULT_TOLERANCE,
) -> None:
    title = f"Rotation benchmark (min agreement {min_agreement:.0%}"
    title += f", angle runs: correct within {tolerance} degrees)" if any(r.meta.get("angle") for r in runs) else ")"
    table = Table(title=title)
    for column in ("Run", "Frames", "OK", "Wrong", "Unsure", "Acc", "Err deg", "Readable",
                   "Agr ok", "Agr bad", "Undet", "Invalid", "s/frame", "s/video"):
        table.add_column(column, justify="left" if column == "Run" else "right")

    detail_columns: list[tuple[str, dict]] = []
    for run in runs:
        for count in counts:
            result = summarize(run, labels, count, min_agreement, tolerance)
            stats = result["stats"]
            accuracy = stats["correct"] / stats["angle"] if stats["angle"] else None
            latency = result["latency"]
            table.add_row(
                run_title(run),
                str(count),
                str(stats["correct"]),
                str(stats["wrong"]),
                str(stats["unsure"]),
                format_number(accuracy, "{:.0%}"),
                format_number(result["mean_error"], "{:.0f}"),
                format_number(result["readable"], "{:.1f}"),
                format_number(result["agreement_correct"], "{:.2f}"),
                format_number(result["agreement_wrong"], "{:.2f}"),
                str(stats["undetermined"]),
                str(stats["invalid"]),
                format_number(latency, "{:.2f}"),
                format_number(latency * count if latency is not None else None, "{:.1f}"),
            )
            detail_columns.append((f"{run_title(run)} {count}", result["cells"]))
    CONSOLE.print(table)

    for run in runs:
        names = {name for name, _ in run.frames}
        excluded = sum(1 for name in names if labels.get(name) == EXCLUDED)
        CONSOLE.print(
            f"{run.label}: model={run.meta.get('model')} width={run.meta.get('width')} "
            f"frames={'tag applied' if run.meta.get('apply_tag') else 'raw'} "
            f"videos={len(names)} (label -1, not scored: {excluded}) wall={run.wall_seconds:.0f}s"
            f"{thinking_info(run)}",
            markup=False,
        )

    if details:
        tags = {name: record["container_rotation"] for run in runs for name, record in run.videos.items()}
        render_details(labels, detail_columns, tags)


def live_line(
    run: Run,
    name: str,
    labels: dict[str, frozenset[int]] | None,
    counts: Sequence[int],
    min_agreement: float,
    tolerance: int,
) -> str:
    raw = labels.get(name) if labels else None
    label = effective_label(run, name, raw)
    head = name
    if raw is not None:
        head += f"  label {label_text(raw)}"
        tag = run.videos.get(name, {}).get("container_rotation")
        if run.meta.get("apply_tag") and tag is not None:
            head += f" tag {tag} need {need_text(raw, tag)}"
    styles = {"correct": "green", "wrong": "red", "unsure": "yellow", "excluded": "dim"}
    parts = []
    for count in counts:
        if label is None:
            verdict = video_verdict(run, name, count)
            predicted, style = decide(verdict, min_agreement), "white"
        else:
            outcome, verdict, predicted = video_cell(run, name, label, count, min_agreement, tolerance)
            style = styles[outcome]
        shown = "?" if predicted is None else str(predicted)
        top_votes = max(verdict.counts.values(), default=0)
        parts.append(f"[{style}]{count}: {shown} {top_votes}/{verdict.readable}[/]")
    return head + "   " + "   ".join(parts)


def thinking_info(run: Run) -> str:
    if not run.meta.get("thinking"):
        return ""
    frames = list(run.frames.values())
    cut = sum(1 for record in frames if record.get("truncated"))
    tokens = [record["completion_tokens"] for record in frames if record.get("completion_tokens") is not None]
    average = f"{sum(tokens) / len(tokens):.0f}" if tokens else "-"
    limit = run.meta.get("thinking_tokens")
    return f" thinking: limit={limit} mean output tokens={average} cut off={cut}/{len(frames)}"


def run_title(run: Run) -> str:
    suffixes = [name for name, key in (("tag", "apply_tag"), ("angle", "angle"), ("think", "thinking")) if run.meta.get(key)]
    return f"{run.label} [{','.join(suffixes)}]" if suffixes else run.label


def need_text(label: frozenset[int], tag: int) -> str:
    if label == EXCLUDED:
        return "-"
    return "/".join(str(angle) for angle in sorted((angle - tag) % 360 for angle in label))


def render_details(
    labels: dict[str, frozenset[int]],
    columns: Sequence[tuple[str, dict]],
    tags: dict[str, int],
) -> None:
    table = Table(title="Per-video verdicts (winner votes / readable frames; agreement ignores unreadable frames)")
    table.add_column("Video")
    table.add_column("Label", justify="right")
    if tags:
        table.add_column("Tag", justify="right")
        table.add_column("Need", justify="right")
    for title, _ in columns:
        table.add_column(title, justify="right")
    styles = {"correct": "green", "wrong": "red", "unsure": "yellow", "excluded": "dim"}
    names = sorted({name for _, cells in columns for name in cells})
    for name in names:
        row = [name, label_text(labels[name])]
        if tags:
            tag = tags.get(name)
            row.extend(["-", "-"] if tag is None else [str(tag), need_text(labels[name], tag)])
        for _, cells in columns:
            if name not in cells:
                row.append("-")
                continue
            outcome, verdict, predicted = cells[name]
            shown = "?" if predicted is None else str(predicted)
            top_votes = max(verdict.counts.values(), default=0)
            row.append(f"[{styles[outcome]}]{shown} {top_votes}/{verdict.readable}[/]")
        table.add_row(*row)
    CONSOLE.print(table)


def resolve_labels(path: Path | None, fallback: Path) -> dict[str, frozenset[int]] | None:
    candidate = path or fallback
    if candidate.is_file():
        return load_labels(candidate)
    if path is not None:
        raise FileNotFoundError(f"labels file not found: {path}")
    return None


def find_videos(directory: Path) -> list[Path]:
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def check_resume(existing: Run, expected: dict) -> None:
    mismatched = [
        f"{key}: {existing.meta.get(key, META_DEFAULTS.get(key))!r} != {expected.get(key, META_DEFAULTS.get(key))!r}"
        for key in META_KEYS
        if existing.meta.get(key, META_DEFAULTS.get(key)) != expected.get(key, META_DEFAULTS.get(key))
    ]
    if mismatched:
        raise ValueError(
            f"{existing.path} was produced with different settings ({'; '.join(mismatched)}); "
            "use --overwrite or another --label"
        )


def command_run(args: argparse.Namespace) -> int:
    directory: Path = args.directory.resolve()
    if not directory.is_dir():
        ERROR_CONSOLE.print(f"Not a directory: {directory}", markup=False)
        return 2
    if Path(args.label).name != args.label or not args.label:
        ERROR_CONSOLE.print("--label must be a plain name", markup=False)
        return 2
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            ERROR_CONSOLE.print(f"{tool} not found in PATH", markup=False)
            return 2
    videos = find_videos(directory)
    if not videos:
        ERROR_CONSOLE.print(f"No video files in {directory}", markup=False)
        return 2

    prompt_name = args.prompt or ("bearing" if args.angle else DEFAULT_PROMPT)
    prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else PROMPTS[prompt_name]
    labels = resolve_labels(args.labels, directory / "labels.txt")
    output = (args.output or directory / "results").resolve()
    cache_dir = output / "frames" / f"w{args.width}{'-tag' if args.apply_tag else ''}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        cache_dir=cache_dir,
        url=args.base_url.rstrip("/"),
        model=args.model or args.label,
        prompt=prompt,
        width=args.width,
        max_tokens=args.max_tokens,
        timeout=args.timeout if args.timeout is not None else (THINKING_TIMEOUT if args.thinking else TIMEOUT),
        apply_tag=args.apply_tag,
        thinking=args.thinking,
        thinking_tokens=args.thinking_tokens,
        angle=args.angle,
    )
    expected_meta = {
        "model": settings.model,
        "width": settings.width,
        "max_tokens": settings.max_tokens,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "apply_tag": settings.apply_tag,
        "thinking": settings.thinking,
        "thinking_tokens": settings.thinking_tokens if settings.thinking else 0,
        "angle": settings.angle,
    }

    results_path = output / f"{args.label}.jsonl"
    if args.overwrite and results_path.exists():
        results_path.unlink()
    if results_path.exists():
        existing = load_run(results_path)
        try:
            check_resume(existing, expected_meta)
        except ValueError as error:
            ERROR_CONSOLE.print(str(error), markup=False)
            return 2
    else:
        existing = None
        append_records(results_path, [{
            "type": "meta",
            "label": args.label,
            "base_url": settings.url,
            "created": datetime.now().isoformat(timespec="seconds"),
            "prompt_style": "file" if args.prompt_file else prompt_name,
            **expected_meta,
        }])

    session = requests.Session()
    try:
        session.get(f"{settings.url}/v1/models", timeout=10)
    except requests.RequestException as error:
        ERROR_CONSOLE.print(f"Cannot reach the server at {settings.url}: {error}", markup=False)
        return 2

    done = {key for key, record in (existing.frames if existing else {}).items() if record["error"] is None}
    fractions = all_fractions(args.frames)
    known = existing.videos if existing else {}
    pending: list[tuple[Path, float, float]] = []
    new_records: list[dict] = []
    for path in videos:
        missing = [fraction for fraction in fractions if (path.name, fraction) not in done]
        try:
            duration, rotation = probe_video(path)
        except FrameError as error:
            new_records.extend(
                {"type": "frame", "file": path.name, "fraction": fraction, "answer": None,
                 "raw": None, "seconds": None, "error": f"frame: {error}"}
                for fraction in missing
            )
            continue
        if known.get(path.name, {}).get("container_rotation") != rotation:
            new_records.append({
                "type": "video", "file": path.name,
                "container_rotation": rotation, "duration": round(duration, 3),
            })
        pending.extend((path, fraction, duration * fraction) for fraction in missing)
    append_records(results_path, new_records)
    live = Run(
        results_path,
        {"apply_tag": settings.apply_tag, "angle": settings.angle},
        dict(existing.frames) if existing else {},
        0.0,
        {**known, **{record["file"]: record for record in new_records if record["type"] == "video"}},
    )
    remaining = Counter(path.name for path, _, _ in pending)

    ERROR_CONSOLE.print(
        f"{args.label}: {len(videos)} videos, {len(fractions)} frames each, "
        f"{len(pending)} queries to run, workers={args.workers}",
        markup=False,
    )

    wall_started = time.monotonic()
    fatal: str | None = None
    executor = ThreadPoolExecutor(max_workers=args.workers)
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=ERROR_CONSOLE,
            expand=False,
        ) as progress:
            task = progress.add_task("Querying model".ljust(25), total=len(pending))
            futures = [
                executor.submit(query_frame, session, settings, path, fraction, seconds)
                for path, fraction, seconds in pending
            ]
            for future in as_completed(futures):
                try:
                    record = future.result()
                except ServerUnreachable as error:
                    fatal = str(error)
                    break
                append_records(results_path, [record])
                progress.advance(task)
                live.frames[(record["file"], record["fraction"])] = record
                remaining[record["file"]] -= 1
                if remaining[record["file"]] == 0:
                    progress.console.print(
                        live_line(live, record["file"], labels, args.frames, args.min_agreement, args.tolerance)
                    )
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        session.close()

    append_records(results_path, [{
        "type": "run",
        "wall_seconds": round(time.monotonic() - wall_started, 1),
        "workers": args.workers,
        "finished": datetime.now().isoformat(timespec="seconds"),
    }])
    if fatal is not None:
        ERROR_CONSOLE.print(
            f"Server became unreachable ({fatal}). Partial results kept in {results_path}; "
            "re-run the same command to resume.",
            markup=False,
        )
        return 2

    ERROR_CONSOLE.print(f"Results: {results_path}", markup=False)
    if labels is None:
        ERROR_CONSOLE.print("No labels file found; skipping the summary.", markup=False)
        return 0
    render_summary([load_run(results_path)], labels, args.frames, args.min_agreement, args.details, args.tolerance)
    return 0


def command_report(args: argparse.Namespace) -> int:
    paths = [path.resolve() for path in args.results]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        ERROR_CONSOLE.print(f"Not found: {', '.join(map(str, missing))}", markup=False)
        return 2
    try:
        labels = resolve_labels(args.labels, paths[0].parent.parent / "labels.txt")
    except (OSError, ValueError) as error:
        ERROR_CONSOLE.print(str(error), markup=False)
        return 2
    if labels is None:
        ERROR_CONSOLE.print("Labels file not found; pass --labels.", markup=False)
        return 2
    runs = [load_run(path) for path in paths]
    render_summary(runs, labels, args.frames, args.min_agreement, args.details, args.tolerance)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--labels", type=Path, help="labels file (default: labels.txt next to the videos)")
    common.add_argument(
        "--frames", type=int, nargs="+", default=list(DEFAULT_FRAME_COUNTS),
        help="frame counts to evaluate (default: 5 7 9)",
    )
    common.add_argument(
        "--min-agreement", type=float, default=DEFAULT_MIN_AGREEMENT,
        help="share of frames that must agree for a confident verdict (default: 0.6)",
    )
    common.add_argument("--details", action="store_true", help="also print per-video verdicts")
    common.add_argument(
        "--tolerance", type=int, default=DEFAULT_TOLERANCE,
        help=f"degrees an angle run may be off and still count as correct (default: {DEFAULT_TOLERANCE})",
    )

    run = subparsers.add_parser("run", parents=[common], help="query a model server and store the answers")
    run.add_argument("directory", type=Path, help="folder with the test videos")
    run.add_argument("--label", required=True, help="name of this run, used for the results file")
    run.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"server root (default: {DEFAULT_BASE_URL})")
    run.add_argument("--model", help="model name sent to the server (default: the label)")
    run.add_argument("--width", type=int, default=512, help="frame width sent to the model (default: 512)")
    run.add_argument("--max-tokens", type=int, default=32)
    run.add_argument("--timeout", type=float, help=f"seconds per request (default: {TIMEOUT}, or {THINKING_TIMEOUT} with --thinking)")
    run.add_argument("--thinking", action="store_true", help="let the model think before answering")
    run.add_argument(
        "--thinking-tokens", type=int, default=DEFAULT_THINKING_TOKENS,
        help=f"extra tokens allowed for thinking (default: {DEFAULT_THINKING_TOKENS}); answers cut off by this limit count as invalid",
    )
    run.add_argument("--workers", type=int, default=1, help="parallel requests (match llama-server --parallel)")
    run.add_argument(
        "--prompt", choices=sorted(PROMPTS),
        help="built-in prompt: top = where the top of the scene is, clockwise = which rotation fixes it, "
             "bearing = compass direction of the top for --angle (default: top, or bearing with --angle)",
    )
    run.add_argument(
        "--angle", action="store_true",
        help="ask for a continuous angle in 15 degree steps instead of one of 0/90/180/270; "
             "answers within --tolerance degrees of the label count as correct",
    )
    run.add_argument("--prompt-file", type=Path, help="use this prompt file instead of a built-in one")
    run.add_argument("--output", type=Path, help="results folder (default: DIRECTORY/results)")
    run.add_argument(
        "--apply-tag", action="store_true",
        help="send frames with the file's rotation tag applied, as mpv shows them; labels are then judged as label minus tag",
    )
    run.add_argument("--overwrite", action="store_true", help="discard an existing results file for this label")
    run.set_defaults(handler=command_run)

    report = subparsers.add_parser("report", parents=[common], help="compare stored runs")
    report.add_argument("results", type=Path, nargs="+", help="results .jsonl files")
    report.set_defaults(handler=command_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "workers", 1) < 1:
        ERROR_CONSOLE.print("--workers must be at least 1", markup=False)
        return 2
    try:
        return args.handler(args)
    except (OSError, ValueError) as error:
        ERROR_CONSOLE.print(str(error), markup=False)
        return 2


if __name__ == "__main__":
    sys.exit(main())
