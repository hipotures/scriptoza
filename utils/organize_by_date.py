#!/usr/bin/env python3

import argparse
import errno
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    MofNCompleteColumn,
    TimeElapsedColumn,
)
from rich.prompt import Confirm


console = Console()
DATE_TIME_PATTERNS = (
    ("%Y%m%d", r"(\d{8})[_-]\d{6}"),
    ("%Y-%m-%d", r"(\d{4}-\d{2}-\d{2})"),
    ("%Y_%m_%d", r"(\d{4}_\d{2}_\d{2})"),
    ("%Y.%m.%d", r"(\d{4}\.\d{2}\.\d{2})"),
    ("%Y%m%d", r"(\d{8})"),
)


@dataclass
class Operation:
    source: Path
    destination: Optional[Path]
    date_folder: Optional[str]
    state: str


def normalize_date(value: str, fmt: str) -> Optional[str]:
    try:
        return datetime.strptime(value, fmt).strftime("%Y%m%d")
    except ValueError:
        return None


def extract_date_folder(filename: str) -> Optional[str]:
    import re

    for fmt, pattern in DATE_TIME_PATTERNS:
        for match in re.finditer(pattern, filename):
            normalized = normalize_date(match.group(1), fmt)
            if normalized:
                return normalized
    return None


def is_hidden_relative(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.name.startswith(".")
    return any(part.startswith(".") for part in relative.parts)


def collect_files(target: Path, recursive: bool) -> List[Path]:
    if target.is_file():
        return [target]
    if recursive:
        files = [path for path in target.rglob("*") if path.is_file() and not is_hidden_relative(path, target)]
    else:
        files = [path for path in target.iterdir() if path.is_file() and not path.name.startswith(".")]
    files.sort()
    return files


def build_operations(files: List[Path], root: Path) -> List[Operation]:
    operations: List[Operation] = []
    for source in files:
        date_folder = extract_date_folder(source.name)
        if not date_folder:
            operations.append(Operation(source=source, destination=None, date_folder=None, state="no_date"))
            continue

        destination = root / date_folder / source.name
        if source.resolve() == destination.resolve():
            operations.append(Operation(source=source, destination=destination, date_folder=date_folder, state="already_organized"))
            continue

        if destination.exists():
            operations.append(Operation(source=source, destination=destination, date_folder=date_folder, state="conflict"))
            continue

        operations.append(Operation(source=source, destination=destination, date_folder=date_folder, state="planned"))

    return operations


def copy_to_temp(source: Path, destination_dir: Path) -> Tuple[Optional[Path], Optional[str]]:
    temp_path: Optional[Path] = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{source.name}.tmp-", dir=destination_dir)
        os.close(fd)
        temp_path = Path(temp_name)
        shutil.copy2(source, temp_path)
        with temp_path.open("rb") as handle:
            os.fsync(handle.fileno())
        return temp_path, None
    except Exception as exc:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        return None, str(exc)


def publish_temp_no_overwrite(temp_path: Path, destination: Path) -> Tuple[str, Optional[str]]:
    try:
        os.link(temp_path, destination)
        return "published", None
    except FileExistsError:
        return "conflict", None
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EMLINK):
            return "error", str(exc)

    created = False
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        created = True
        with temp_path.open("rb") as src_handle, os.fdopen(fd, "wb") as dst_handle:
            shutil.copyfileobj(src_handle, dst_handle, length=1024 * 1024)
            dst_handle.flush()
            os.fsync(dst_handle.fileno())
        shutil.copystat(temp_path, destination, follow_symlinks=True)
        return "published", None
    except FileExistsError:
        return "conflict", None
    except Exception as exc:
        if created and destination.exists():
            try:
                destination.unlink()
            except OSError:
                pass
        return "error", str(exc)


def safe_move_no_overwrite(source: Path, destination: Path) -> Tuple[str, Optional[str]]:
    if destination.exists():
        return "conflict", None

    try:
        os.link(source, destination)
        try:
            source.unlink()
            return "moved", None
        except Exception as unlink_exc:
            try:
                destination.unlink()
            except Exception as rollback_exc:
                return "error", f"{unlink_exc}; rollback failed: {rollback_exc}"
            return "error", str(unlink_exc)
    except FileExistsError:
        return "conflict", None
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EMLINK):
            return "error", str(exc)

    temp_path, temp_error = copy_to_temp(source, destination.parent)
    if temp_error:
        return "error", temp_error
    if temp_path is None:
        return "error", "temporary copy creation failed"

    try:
        publish_status, publish_error = publish_temp_no_overwrite(temp_path, destination)
        if publish_status == "conflict":
            return "conflict", None
        if publish_status == "error":
            return "error", publish_error

        try:
            source.unlink()
            return "moved", None
        except Exception as unlink_exc:
            try:
                destination.unlink()
            except Exception as rollback_exc:
                return "error", f"{unlink_exc}; rollback failed: {rollback_exc}"
            return "error", str(unlink_exc)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def format_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def determine_recursive(target: Path, args: argparse.Namespace) -> bool:
    if target.is_file():
        return False
    if args.recursive:
        return True
    if args.no_recursive:
        return False

    try:
        has_subdirs = any(path.is_dir() and not path.name.startswith(".") for path in target.iterdir())
    except OSError as exc:
        console.print(f"[red]Error accessing directory: {exc}[/red]")
        sys.exit(1)

    if not has_subdirs:
        return False

    return Confirm.ask("Scan selected directory and subdirectories?", default=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Organize files into YYYYMMDD folders based on date patterns found in filenames.")
    parser.add_argument("path", nargs="?", default=".", help="Path to file or directory")
    parser.add_argument("--dry-run", action="store_true", help="Show planned moves without changing files")
    parser.add_argument("-r", "--recursive", action="store_true", help="Scan directories recursively")
    parser.add_argument("--no-recursive", action="store_true", help="Scan only the selected directory")
    args = parser.parse_args()

    if args.recursive and args.no_recursive:
        console.print("[red]Error: use either --recursive or --no-recursive.[/red]")
        return 1

    target = Path(args.path).resolve()
    if not target.exists():
        console.print(f"[red]Error: {args.path} does not exist.[/red]")
        return 1
    if not target.is_file() and not target.is_dir():
        console.print(f"[red]Error: {args.path} is not a regular file or directory.[/red]")
        return 1

    recursive = determine_recursive(target, args)
    root = target.parent if target.is_file() else target
    files = collect_files(target, recursive)

    if not files:
        console.print("[yellow]No eligible files found.[/yellow]")
        return 0

    operations = build_operations(files, root)
    planned_moves = sum(1 for operation in operations if operation.state == "planned")

    if not args.dry_run and planned_moves > 0:
        noun = "file" if planned_moves == 1 else "files"
        if not Confirm.ask(f"Move {planned_moves} {noun} into date folders?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return 0

    stats = {
        "scanned": 0,
        "matched_date": 0,
        "moved": 0,
        "dry_run_moves": 0,
        "skipped_no_date": 0,
        "skipped_already_organized": 0,
        "conflicts": 0,
        "move_errors": 0,
    }
    conflict_rows: List[Tuple[str, str]] = []
    error_rows: List[Tuple[str, str, str]] = []

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        expand=False,
        auto_refresh=False,
    )

    task_id = progress.add_task("Organizing files".ljust(25), total=len(operations))

    with progress:
        for operation in operations:
            stats["scanned"] += 1
            if operation.date_folder:
                stats["matched_date"] += 1

            if operation.state == "no_date":
                stats["skipped_no_date"] += 1
            elif operation.state == "already_organized":
                stats["skipped_already_organized"] += 1
            elif operation.state == "conflict":
                stats["conflicts"] += 1
                conflict_rows.append(
                    (
                        format_path(operation.source, root),
                        format_path(operation.destination, root),
                    )
                )
            elif operation.state == "planned":
                if args.dry_run:
                    stats["dry_run_moves"] += 1
                else:
                    try:
                        operation.destination.parent.mkdir(parents=True, exist_ok=True)
                    except Exception as exc:
                        stats["move_errors"] += 1
                        error_rows.append(
                            (
                                format_path(operation.source, root),
                                format_path(operation.destination, root),
                                str(exc),
                            )
                        )
                    else:
                        move_status, move_error = safe_move_no_overwrite(operation.source, operation.destination)
                        if move_status == "moved":
                            stats["moved"] += 1
                        elif move_status == "conflict":
                            stats["conflicts"] += 1
                            conflict_rows.append(
                                (
                                    format_path(operation.source, root),
                                    format_path(operation.destination, root),
                                )
                            )
                        else:
                            stats["move_errors"] += 1
                            error_rows.append(
                                (
                                    format_path(operation.source, root),
                                    format_path(operation.destination, root),
                                    move_error or "unknown move error",
                                )
                            )

            progress.advance(task_id)

        progress.update(task_id, description="[bold green]Finished![/bold green]".ljust(25))
        progress.refresh()

    console.print("\n[bold]Summary[/bold]")
    console.print(f"  Scanned: {stats['scanned']}")
    console.print(f"  Matched date: {stats['matched_date']}")
    console.print(f"  Moved: {stats['moved']}")
    console.print(f"  Dry-run moves: {stats['dry_run_moves']}")
    console.print(f"  Skipped (no valid date): {stats['skipped_no_date']}")
    console.print(f"  Skipped (already organized): {stats['skipped_already_organized']}")
    console.print(f"  Conflicts (destination exists): {stats['conflicts']}")
    console.print(f"  Move errors: {stats['move_errors']}")

    if conflict_rows:
        console.print("\n[bold yellow]Conflicts[/bold yellow]")
        for source, destination in conflict_rows:
            console.print(f"  {source} -> {destination}")

    if error_rows:
        console.print("\n[bold red]Move Errors[/bold red]")
        for source, destination, error in error_rows:
            console.print(f"  {source} -> {destination}: {error}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
