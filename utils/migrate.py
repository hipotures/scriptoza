#!/usr/bin/env python3
"""
migrate.py

Migrates files older than a specified age (default 12h) from the largest subdirectories in the source to the archive.
Features:
- Configurable number of directories to process (top N by size).
- Rich progress bars and detailed debug output.
- Robust safety checks (disk space, destination collisions).
- Graceful interruption (Ctrl-C).
"""

import os
import sys
import argparse
import time
import shutil
import signal
from dotenv import load_dotenv
from rich.console import Console, Group
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    MofNCompleteColumn,
    TimeElapsedColumn,
    FileSizeColumn,
    TotalFileSizeColumn
)
from rich.live import Live
from rich.text import Text
from rich.panel import Panel

# Load environment variables from .env
load_dotenv()

# Defaults
DEFAULT_SOURCE = os.getenv("MIGRATE_SOURCE")
DEFAULT_ARCHIVE = os.getenv("MIGRATE_ARCHIVE")
DEFAULT_AGE_HOURS = int(os.getenv("MIGRATE_AGE_HOURS", "12"))
MIN_FREE_SPACE_BUFFER = 100 * 1024 * 1024  # 100 MB buffer

console = Console()
status_line = Text("", style="dim blue")
stop_requested = False

def validate_args(args):
    """Checks if required paths are provided via CLI or Environment."""
    errors = []
    if not args.source:
        errors.append("Missing source path (SOURCE).")
    if not args.archive:
        errors.append("Missing archive path (ARCHIVE).")
    
    if errors:
        for err in errors:
            console.print(f"[red]Error: {err}[/red]")
        
        console.print("\n[bold yellow]Instructions:[/bold yellow]")
        console.print("Parameters must be provided via command line or in the [bold].env[/bold] file.")
        console.print("\n[bold cyan]Option 1: .env file[/bold cyan]")
        console.print("Create a .env file in the root directory and add:")
        console.print("  MIGRATE_SOURCE=\"/path/to/source\"")
        console.print("  MIGRATE_ARCHIVE=\"/path/to/archive\"")
        console.print("  MIGRATE_AGE_HOURS=\"12\"")
        console.print("\n[bold cyan]Option 2: Command line[/bold cyan]")
        console.print("  ./utils/migrate.py -s /path/to/source -a /path/to/archive -t 12")
        sys.exit(1)

def signal_handler(sig, frame):
    global stop_requested
    if not stop_requested:
        console.print("\n[yellow]!! Interruption (Ctrl-C) detected. Finishing current operation and exiting...[/yellow]")
        stop_requested = True
    else:
        console.print("\n[red]!! Forced stop.[/red]")
        sys.exit(130)

signal.signal(signal.SIGINT, signal_handler)

def format_bytes(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def get_dir_size(path):
    """Calculates total size of a directory recursively."""
    total = 0
    try:
        for root, dirs, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
            if stop_requested: break
    except OSError:
        pass
    return total

def find_candidates(source_dir):
    """Finds subdirectories in source_dir and sorts them by total size."""
    if not os.path.isdir(source_dir):
        return []
    
    try:
        entries = [e for e in os.listdir(source_dir) if os.path.isdir(os.path.join(source_dir, e))]
    except OSError as e:
        console.print(f"[red]Error reading source directory: {e}[/red]")
        return []

    if not entries:
        return []
        
    candidates = []
    # Use a spinner as calculating sizes can be slow
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console
    ) as progress:
        task = progress.add_task("Analyzing directory sizes... (this may take a while)", total=len(entries))
        
        for entry in entries:
            if stop_requested: break
            full = os.path.join(source_dir, entry)
            size = get_dir_size(full)
            candidates.append((entry, full, size))
            progress.advance(task)
            
    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates

def get_files_to_move(src_dir, age_seconds):
    """Identifies files in the immediate directory older than age_seconds."""
    to_move = []
    now = time.time()
    
    try:
        with os.scandir(src_dir) as it:
            for entry in it:
                if entry.is_file():
                    try:
                        stat = entry.stat()
                        # Check size > 0 and age
                        if stat.st_size > 0 and (now - stat.st_mtime > age_seconds):
                            to_move.append({
                                'path': entry.path,
                                'name': entry.name,
                                'size': stat.st_size
                            })
                    except OSError:
                        pass
    except OSError as e:
        console.print(f"[red]Error reading directory {src_dir}: {e}[/red]")
        
    return to_move

def check_disk_space(dest_path, required_bytes):
    """Checks if the destination filesystem has enough free space."""
    try:
        # Check parent if dest doesn't exist yet
        check_path = dest_path if os.path.exists(dest_path) else os.path.dirname(dest_path)
        while not os.path.exists(check_path) and check_path != '/':
            check_path = os.path.dirname(check_path)
            
        usage = shutil.disk_usage(check_path)
        return usage.free > (required_bytes + MIN_FREE_SPACE_BUFFER)
    except OSError:
        # If we can't check, we assume OK but warn
        return True

def safe_move(src, dst):
    """Moves file from src to dst, handling collisions and errors."""
    if os.path.exists(dst):
        # Collision: append counter
        base, ext = os.path.splitext(dst)
        counter = 1
        new_dst = f"{base}_{counter}{ext}"
        while os.path.exists(new_dst):
            counter += 1
            new_dst = f"{base}_{counter}{ext}"
        dst = new_dst

    try:
        shutil.move(src, dst)
        return True, dst, None
    except Exception as e:
        return False, None, str(e)

def get_disk_stats(path):
    """Returns a string with disk usage: Used/Total GB and Percentage."""
    try:
        # Find the first existing parent directory to check disk usage
        check_path = os.path.abspath(path)
        while not os.path.exists(check_path) and check_path != os.path.dirname(check_path):
            check_path = os.path.dirname(check_path)
            
        usage = shutil.disk_usage(check_path)
        total_gb = usage.total / (1024**3)
        used_gb = usage.used / (1024**3)
        percent = (usage.used / usage.total) * 100
        return f"{used_gb:.3f}/{total_gb:.3f} GB ({percent:.1f}%)"
    except Exception:
        return "N/A"

def main():
    parser = argparse.ArgumentParser(description="Migrate old files from largest directories safely.")
    parser.add_argument("-c", "--count", type=int, default=1, help="Number of directories to migrate (default 1)")
    parser.add_argument("-s", "--source", default=DEFAULT_SOURCE, help="Source directory (defaults to .env MIGRATE_SOURCE)")
    parser.add_argument("-a", "--archive", default=DEFAULT_ARCHIVE, help="Archive directory (defaults to .env MIGRATE_ARCHIVE)")
    parser.add_argument("-t", "--time", type=int, default=DEFAULT_AGE_HOURS, help=f"File age in hours (default {DEFAULT_AGE_HOURS})")
    parser.add_argument("--debug", action="store_true", help="Show details of processed files")
    
    args = parser.parse_args()
    validate_args(args)

    age_seconds = args.time * 3600
    
    src_stats = get_disk_stats(args.source) if args.source else "N/A"
    dst_stats = get_disk_stats(args.archive) if args.archive else "N/A"

    console.print(Panel(f"[bold blue]Migrating the {args.count} largest directories[/bold blue]\n" 
                        f"Source:  {args.source} [dim]({src_stats})[/dim]\n" 
                        f"Archive: {args.archive} [dim]({dst_stats})[/dim]\n" 
                        f"File age: > {args.time}h", border_style="blue"))

    if not os.path.exists(args.source):
        console.print(f"[red]Error: Source directory '{args.source}' does not exist.[/red]")
        sys.exit(1)
        
    # 1. Find Candidates
    candidates = find_candidates(args.source)
    if not candidates:
        console.print("[yellow]No subdirectories found in source.[/yellow]")
        sys.exit(0)
        
    targets = candidates[:args.count]
    
    stats = {
        'dirs_processed': 0,
        'files_moved': 0,
        'bytes_moved': 0,
        'errors': 0,
        'skipped_space': 0
    }
    
    # 2. Process Loop
    total_targets = len(targets)
    for idx, (dir_name, dir_path, dir_size) in enumerate(targets, 1):
        if stop_requested: break
        
        console.print(f"\n[bold cyan]#{idx}/{total_targets} Directory: {dir_name}[/bold cyan] (Total size: {format_bytes(dir_size)})\n[dim]({dir_path})[/dim]")
        
        # Prepare Scan
        files_to_move = get_files_to_move(dir_path, age_seconds)
        
        if not files_to_move:
            console.print(f"  [dim]No files older than {args.time}h found.[/dim]")
            stats['dirs_processed'] += 1
            continue
            
        total_move_size = sum(f['size'] for f in files_to_move)
        console.print(f"  Found {len(files_to_move)} files to move ({format_bytes(total_move_size)})")
        
        # Prepare Archive Dir
        target_archive_dir = os.path.join(args.archive, dir_name)
        try:
            os.makedirs(target_archive_dir, exist_ok=True)
        except OSError as e:
            console.print(f"[red]  Error creating destination directory: {e}[/red]")
            stats['errors'] += 1
            continue
            
        # Check Disk Space (Batch Check)
        if not check_disk_space(target_archive_dir, total_move_size):
            console.print(f"[red]  !! NO SPACE on destination disk (required {format_bytes(total_move_size)} + buffer). Skipping directory.[/red]")
            stats['skipped_space'] += 1
            continue

        # Setup Progress
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            FileSizeColumn(),
            TextColumn("/"),
            TotalFileSizeColumn(),
            TimeElapsedColumn(),
            console=console
        )
        
        # We track bytes as the progress unit
        task_id = progress.add_task(f"Migrating {dir_name}", total=total_move_size)
        
        ui_elements = [progress]
        if args.debug:
            status_line.plain = ""
            ui_elements.append(status_line)
            
        group = Group(*ui_elements)
        
        # Live execution
        with Live(group, console=console, refresh_per_second=10):
            for f in files_to_move:
                if stop_requested: break
                
                fname = f['name']
                fpath = f['path']
                fsize = f['size']
                
                if args.debug:
                    status_line.plain = f" → {fname} ({format_bytes(fsize)})"
                
                # Double check space per file for safety
                if not check_disk_space(target_archive_dir, fsize):
                    if args.debug:
                        status_line.plain = f" [red]NO SPACE for {fname}[/red]"
                    else:
                        console.print(f"[red]  !! No space for {fname}[/red]")
                    stats['errors'] += 1
                    stats['skipped_space'] += 1
                    break # Stop processing this directory

                dst_path = os.path.join(target_archive_dir, fname)
                success, final_dst, err = safe_move(fpath, dst_path)
                
                if success:
                    stats['files_moved'] += 1
                    stats['bytes_moved'] += fsize
                    progress.advance(task_id, advance=fsize)
                else:
                    console.print(f"[red]  Error moving {fname}: {err}[/red]")
                    stats['errors'] += 1
        
        stats['dirs_processed'] += 1
        if stop_requested: break

    # Summary
    console.print("\n[bold green]=== Migration Summary ===[/bold green]")
    console.print(f"Directories processed: {stats['dirs_processed']}")
    console.print(f"Files moved:           {stats['files_moved']}")
    console.print(f"Data moved:            {format_bytes(stats['bytes_moved'])}")
    
    if stats['errors'] > 0:
        console.print(f"[red]Errors:                 {stats['errors']}[/red]")
    if stats['skipped_space'] > 0:
        console.print(f"[red]Skipped (no space):    {stats['skipped_space']} (directories/files)[/red]")
    
    if stop_requested:
        console.print("[yellow]Operation was interrupted by user.[/yellow]")

if __name__ == "__main__":
    main()