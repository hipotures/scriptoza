#!/usr/bin/env python3

import argparse
import csv
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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


console = Console()

DAY_PATTERN = re.compile(r"^\d{8}$")

ASSIGNMENT_HEADERS = [
    "day",
    "stream_id",
    "device",
    "filename",
    "path",
    "source_csv",
    "photo_start_local",
    "adjusted_start_local",
    "photo_offset_seconds",
    "performance_number",
    "target_dir",
    "timeline_status",
    "performance_start_local",
    "performance_end_local",
    "seconds_to_start",
    "seconds_to_end",
    "seconds_to_nearest_boundary",
    "assignment_status",
    "assignment_reason",
]

UNASSIGNED_HEADERS = [
    "day",
    "stream_id",
    "device",
    "filename",
    "path",
    "source_csv",
    "photo_start_local",
    "adjusted_start_local",
    "photo_offset_seconds",
    "unassigned_reason",
    "previous_performance_number",
    "previous_performance_end_local",
    "next_performance_number",
    "next_performance_start_local",
]

SUMMARY_HEADERS = [
    "day",
    "performance_number",
    "target_dir",
    "timeline_status",
    "performance_start_local",
    "performance_end_local",
    "assigned_photos",
    "review_photos",
    "first_photo_local",
    "last_photo_local",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assign exported photo rows to performance intervals without generating mv commands."
    )
    parser.add_argument("day_dir", help="Path to a single day directory like /data/20260323")
    parser.add_argument(
        "--workspace-dir",
        help="Directory containing p-*.csv and performance_timeline.csv. Default: DAY/_workspace",
    )
    parser.add_argument(
        "--timeline-csv",
        help="Performance timeline CSV path. Default: DAY/_workspace/performance_timeline.csv",
    )
    parser.add_argument(
        "--streams",
        nargs="*",
        help='Specific photo stream IDs to process, for example "p-a7r5"',
    )
    parser.add_argument(
        "--list-streams",
        action="store_true",
        help="List available photo stream IDs and exit",
    )
    parser.add_argument(
        "--output-assignments",
        default="photo_assignments.csv",
        help="Output filename inside workspace or absolute path. Default: photo_assignments.csv",
    )
    parser.add_argument(
        "--output-review",
        default="photo_review.csv",
        help="Output filename inside workspace or absolute path. Default: photo_review.csv",
    )
    parser.add_argument(
        "--output-unassigned",
        default="photo_unassigned.csv",
        help="Output filename inside workspace or absolute path. Default: photo_unassigned.csv",
    )
    parser.add_argument(
        "--output-summary",
        default="photo_assignment_summary.csv",
        help="Output filename inside workspace or absolute path. Default: photo_assignment_summary.csv",
    )
    parser.add_argument(
        "--photo-offset-seconds",
        type=float,
        default=0.0,
        help="Constant offset added to photo timestamps before matching. Default: 0.0",
    )
    parser.add_argument(
        "--review-margin-seconds",
        type=float,
        default=15.0,
        help="Mark assigned photos near boundaries for review. Default: 15.0",
    )
    parser.add_argument(
        "--include-open-end",
        action="store_true",
        help="Allow matching photos to open_end timeline rows with no known end time",
    )
    return parser.parse_args()


def parse_local_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def format_datetime(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    return value.isoformat(timespec="milliseconds" if value.microsecond else "seconds")


def format_seconds(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.3f}"


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, headers: Sequence[str], rows: Iterable[Dict[str, str]]) -> int:
    row_list = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(headers))
        writer.writeheader()
        writer.writerows(row_list)
    return len(row_list)


def list_photo_streams(workspace_dir: Path) -> List[str]:
    streams: List[str] = []
    for path in sorted(workspace_dir.glob("p-*.csv")):
        if path.name == "photo_assignments.csv":
            continue
        streams.append(path.stem)
    return streams


def select_streams(available_streams: Sequence[str], explicit_streams: Optional[Sequence[str]]) -> List[str]:
    if explicit_streams:
        missing = [stream_id for stream_id in explicit_streams if stream_id not in available_streams]
        if missing:
            console.print(f"[red]Error: unknown photo streams: {', '.join(missing)}[/red]")
            raise SystemExit(1)
        return list(explicit_streams)
    return list(available_streams)


def load_photo_rows(workspace_dir: Path, stream_ids: Sequence[str]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for stream_id in stream_ids:
        path = workspace_dir / f"{stream_id}.csv"
        stream_rows = read_csv_rows(path)
        for row in stream_rows:
            row["_source_csv"] = str(path)
            rows.append(row)
    rows.sort(key=lambda row: (row.get("start_local", ""), row.get("stream_id", ""), row.get("filename", "")))
    return rows


def build_timeline_rows(
    rows: Sequence[Dict[str, str]],
    include_open_end: bool,
) -> List[Dict[str, object]]:
    timeline_rows: List[Dict[str, object]] = []
    for row in rows:
        start_local = parse_local_datetime(row.get("start_local", ""))
        end_local = parse_local_datetime(row.get("end_local", ""))
        if start_local is None:
            continue
        status = row.get("status", "")
        if status == "complete" and end_local is not None:
            timeline_rows.append(
                {
                    "row": row,
                    "start": start_local,
                    "end": end_local,
                }
            )
            continue
        if include_open_end and status == "open_end":
            timeline_rows.append(
                {
                    "row": row,
                    "start": start_local,
                    "end": None,
                }
            )
    timeline_rows.sort(key=lambda item: item["start"])
    return timeline_rows


def find_assignment(
    photo_dt: datetime,
    timeline_rows: Sequence[Dict[str, object]],
) -> Optional[Dict[str, object]]:
    for item in timeline_rows:
        start = item["start"]
        end = item["end"]
        if end is None:
            if photo_dt >= start:
                return item
            continue
        if start <= photo_dt < end:
            return item
    return None


def find_neighbors(
    photo_dt: datetime,
    timeline_rows: Sequence[Dict[str, object]],
) -> Tuple[Optional[Dict[str, object]], Optional[Dict[str, object]]]:
    previous_item: Optional[Dict[str, object]] = None
    next_item: Optional[Dict[str, object]] = None
    for item in timeline_rows:
        start = item["start"]
        end = item["end"]
        if end is not None and end <= photo_dt:
            previous_item = item
            continue
        if end is None and start <= photo_dt:
            previous_item = item
            continue
        if start > photo_dt:
            next_item = item
            break
    return previous_item, next_item


def build_assignment_row(
    photo_row: Dict[str, str],
    adjusted_dt: datetime,
    photo_offset_seconds: float,
    review_margin_seconds: float,
    timeline_item: Dict[str, object],
) -> Tuple[Dict[str, str], bool]:
    timeline_row = timeline_item["row"]
    start = timeline_item["start"]
    end = timeline_item["end"]
    seconds_to_start = (adjusted_dt - start).total_seconds()
    seconds_to_end = (end - adjusted_dt).total_seconds() if end is not None else None
    nearest_boundary = min(seconds_to_start, seconds_to_end) if seconds_to_end is not None else seconds_to_start

    if end is None:
        assignment_status = "provisional_open_end"
        assignment_reason = "matched_open_end_interval"
        needs_review = True
    elif nearest_boundary <= review_margin_seconds:
        assignment_status = "review"
        assignment_reason = "near_interval_boundary"
        needs_review = True
    else:
        assignment_status = "assigned"
        assignment_reason = "matched_complete_interval"
        needs_review = False

    row = {
        "day": photo_row.get("day", ""),
        "stream_id": photo_row.get("stream_id", ""),
        "device": photo_row.get("device", ""),
        "filename": photo_row.get("filename", ""),
        "path": photo_row.get("path", ""),
        "source_csv": photo_row.get("_source_csv", ""),
        "photo_start_local": photo_row.get("start_local", ""),
        "adjusted_start_local": format_datetime(adjusted_dt),
        "photo_offset_seconds": format_seconds(photo_offset_seconds),
        "performance_number": timeline_row.get("performance_number", ""),
        "target_dir": timeline_row.get("target_dir", ""),
        "timeline_status": timeline_row.get("status", ""),
        "performance_start_local": timeline_row.get("start_local", ""),
        "performance_end_local": timeline_row.get("end_local", ""),
        "seconds_to_start": format_seconds(seconds_to_start),
        "seconds_to_end": format_seconds(seconds_to_end),
        "seconds_to_nearest_boundary": format_seconds(nearest_boundary),
        "assignment_status": assignment_status,
        "assignment_reason": assignment_reason,
    }
    return row, needs_review


def classify_unassigned_reason(
    adjusted_dt: datetime,
    timeline_rows: Sequence[Dict[str, object]],
) -> Tuple[str, Optional[Dict[str, object]], Optional[Dict[str, object]]]:
    previous_item, next_item = find_neighbors(adjusted_dt, timeline_rows)
    if not timeline_rows:
        return "no_timeline_rows", previous_item, next_item
    first_start = timeline_rows[0]["start"]
    if adjusted_dt < first_start:
        return "before_first_performance", previous_item, next_item
    last_item = timeline_rows[-1]
    last_end = last_item["end"]
    if last_end is not None and adjusted_dt >= last_end:
        return "after_last_complete_performance", previous_item, next_item
    return "between_performances", previous_item, next_item


def build_unassigned_row(
    photo_row: Dict[str, str],
    adjusted_dt: datetime,
    photo_offset_seconds: float,
    reason: str,
    previous_item: Optional[Dict[str, object]],
    next_item: Optional[Dict[str, object]],
) -> Dict[str, str]:
    previous_row = previous_item["row"] if previous_item else {}
    next_row = next_item["row"] if next_item else {}
    previous_end = previous_item["end"] if previous_item else None
    next_start = next_item["start"] if next_item else None
    return {
        "day": photo_row.get("day", ""),
        "stream_id": photo_row.get("stream_id", ""),
        "device": photo_row.get("device", ""),
        "filename": photo_row.get("filename", ""),
        "path": photo_row.get("path", ""),
        "source_csv": photo_row.get("_source_csv", ""),
        "photo_start_local": photo_row.get("start_local", ""),
        "adjusted_start_local": format_datetime(adjusted_dt),
        "photo_offset_seconds": format_seconds(photo_offset_seconds),
        "unassigned_reason": reason,
        "previous_performance_number": previous_row.get("performance_number", ""),
        "previous_performance_end_local": format_datetime(previous_end),
        "next_performance_number": next_row.get("performance_number", ""),
        "next_performance_start_local": format_datetime(next_start),
    }


def build_summary_rows(
    timeline_rows: Sequence[Dict[str, object]],
    assignment_rows: Sequence[Dict[str, str]],
) -> List[Dict[str, str]]:
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for row in assignment_rows:
        grouped.setdefault(row["performance_number"], []).append(row)

    output_rows: List[Dict[str, str]] = []
    for item in timeline_rows:
        timeline_row = item["row"]
        performance_number = timeline_row.get("performance_number", "")
        rows = grouped.get(performance_number, [])
        review_count = sum(1 for row in rows if row["assignment_status"] != "assigned")
        first_photo = rows[0]["adjusted_start_local"] if rows else ""
        last_photo = rows[-1]["adjusted_start_local"] if rows else ""
        output_rows.append(
            {
                "day": timeline_row.get("day", ""),
                "performance_number": performance_number,
                "target_dir": timeline_row.get("target_dir", ""),
                "timeline_status": timeline_row.get("status", ""),
                "performance_start_local": timeline_row.get("start_local", ""),
                "performance_end_local": timeline_row.get("end_local", ""),
                "assigned_photos": str(len(rows)),
                "review_photos": str(review_count),
                "first_photo_local": first_photo,
                "last_photo_local": last_photo,
            }
        )
    return output_rows


def build_console_summary(
    assignment_rows: Sequence[Dict[str, str]],
    review_rows: Sequence[Dict[str, str]],
    unassigned_rows: Sequence[Dict[str, str]],
    summary_rows: Sequence[Dict[str, str]],
) -> Table:
    table = Table(title="Photo Assignment Summary", expand=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")
    table.add_row("Assigned rows", str(len(assignment_rows)))
    table.add_row("Review rows", str(len(review_rows)))
    table.add_row("Unassigned rows", str(len(unassigned_rows)))
    table.add_row("Timeline rows", str(len(summary_rows)))
    if summary_rows:
        non_empty = [row for row in summary_rows if int(row["assigned_photos"]) > 0]
        table.add_row("Performances with photos", str(len(non_empty)))
    return table


def main() -> int:
    args = parse_args()
    day_dir = Path(args.day_dir).resolve()
    if not day_dir.exists() or not day_dir.is_dir():
        console.print(f"[red]Error: {args.day_dir} is not a directory.[/red]")
        return 1
    if not DAY_PATTERN.match(day_dir.name):
        console.print(f"[red]Error: expected a day directory like 20260323, got {day_dir.name}.[/red]")
        return 1

    workspace_dir = Path(args.workspace_dir).resolve() if args.workspace_dir else day_dir / "_workspace"
    timeline_csv = Path(args.timeline_csv).resolve() if args.timeline_csv else workspace_dir / "performance_timeline.csv"
    output_assignments = Path(args.output_assignments)
    output_review = Path(args.output_review)
    output_unassigned = Path(args.output_unassigned)
    output_summary = Path(args.output_summary)
    if not output_assignments.is_absolute():
        output_assignments = workspace_dir / output_assignments
    if not output_review.is_absolute():
        output_review = workspace_dir / output_review
    if not output_unassigned.is_absolute():
        output_unassigned = workspace_dir / output_unassigned
    if not output_summary.is_absolute():
        output_summary = workspace_dir / output_summary

    if not timeline_csv.exists():
        console.print(f"[red]Error: performance timeline CSV not found: {timeline_csv}[/red]")
        return 1

    available_streams = list_photo_streams(workspace_dir)
    if args.list_streams:
        if available_streams:
            for stream_id in available_streams:
                console.print(stream_id)
            return 0
        console.print("[yellow]No photo stream CSV files found.[/yellow]")
        return 0
    if not available_streams:
        console.print(f"[red]Error: no p-*.csv files found in {workspace_dir}.[/red]")
        return 1

    selected_streams = select_streams(available_streams, args.streams)
    photo_rows = load_photo_rows(workspace_dir, selected_streams)
    if not photo_rows:
        console.print("[red]Error: no photo rows found after stream selection.[/red]")
        return 1

    timeline_rows_raw = read_csv_rows(timeline_csv)
    timeline_rows = build_timeline_rows(timeline_rows_raw, args.include_open_end)
    if not timeline_rows:
        console.print("[red]Error: no usable timeline rows found for assignment.[/red]")
        return 1

    assignment_rows: List[Dict[str, str]] = []
    review_rows: List[Dict[str, str]] = []
    unassigned_rows: List[Dict[str, str]] = []
    stream_counts: Dict[str, int] = {stream_id: 0 for stream_id in selected_streams}
    stream_total_rows: Dict[str, int] = {stream_id: 0 for stream_id in selected_streams}
    for row in photo_rows:
        stream_total_rows[row["stream_id"]] = stream_total_rows.get(row["stream_id"], 0) + 1

    offset_delta = timedelta(seconds=args.photo_offset_seconds)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        expand=False,
    ) as progress:
        streams_task = progress.add_task("Streams".ljust(25), total=len(selected_streams))
        photos_task = progress.add_task("Photos".ljust(25), total=len(photo_rows))
        for stream_id in selected_streams:
            for photo_row in [row for row in photo_rows if row["stream_id"] == stream_id]:
                photo_dt = parse_local_datetime(photo_row.get("start_local", ""))
                if photo_dt is None:
                    progress.advance(photos_task)
                    continue
                adjusted_dt = photo_dt + offset_delta
                matched = find_assignment(adjusted_dt, timeline_rows)
                if matched is not None:
                    assignment_row, needs_review = build_assignment_row(
                        photo_row,
                        adjusted_dt,
                        args.photo_offset_seconds,
                        args.review_margin_seconds,
                        matched,
                    )
                    assignment_rows.append(assignment_row)
                    if needs_review:
                        review_rows.append(assignment_row)
                else:
                    reason, previous_item, next_item = classify_unassigned_reason(adjusted_dt, timeline_rows)
                    unassigned_rows.append(
                        build_unassigned_row(
                            photo_row,
                            adjusted_dt,
                            args.photo_offset_seconds,
                            reason,
                            previous_item,
                            next_item,
                        )
                    )
                stream_counts[stream_id] += 1
                progress.advance(photos_task)
            progress.advance(streams_task)

    assignment_rows.sort(key=lambda row: (row["adjusted_start_local"], row["stream_id"], row["filename"]))
    review_rows.sort(key=lambda row: (row["adjusted_start_local"], row["stream_id"], row["filename"]))
    unassigned_rows.sort(key=lambda row: (row["adjusted_start_local"], row["stream_id"], row["filename"]))
    summary_rows = build_summary_rows(timeline_rows, assignment_rows)

    assignments_written = write_csv(output_assignments, ASSIGNMENT_HEADERS, assignment_rows)
    review_written = write_csv(output_review, ASSIGNMENT_HEADERS, review_rows)
    unassigned_written = write_csv(output_unassigned, UNASSIGNED_HEADERS, unassigned_rows)
    summary_written = write_csv(output_summary, SUMMARY_HEADERS, summary_rows)

    console.print(build_console_summary(assignment_rows, review_rows, unassigned_rows, summary_rows))
    console.print(f"[green]Wrote {assignments_written} assignment rows to {output_assignments}[/green]")
    console.print(f"[green]Wrote {review_written} review rows to {output_review}[/green]")
    console.print(f"[green]Wrote {unassigned_written} unassigned rows to {output_unassigned}[/green]")
    console.print(f"[green]Wrote {summary_written} summary rows to {output_summary}[/green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
