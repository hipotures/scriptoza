#!/usr/bin/env python3
"""
sort_video_dated.py

Sorts files starting with YYYYMMDD_HHMMSS into subdirectories named YYYYMMDD.
Safe and handles collisions.
"""

import os
import re
import shutil
import argparse
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    MofNCompleteColumn,
    TimeElapsedColumn
)

console = Console()

def sort_files(target_dir, dry_run=False):
    # Regex to match YYYYMMDD at the beginning of the filename
    # Example: 20200705_080602_...
    pattern = re.compile(r'^(\d{8})_\d{6}_.*')
    
    try:
        items = os.listdir(target_dir)
    except OSError as e:
        console.print(f"[red]Error accessing directory: {e}[/red]")
        return

    files = [f for f in items if os.path.isfile(os.path.join(target_dir, f)) and pattern.match(f)]
    
    if not files:
        console.print("[yellow]No matching files found (YYYYMMDD_HHMMSS_*).[/yellow]")
        return

    files.sort()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        expand=False
    ) as progress:
        desc = "Sorting files".ljust(25)
        task = progress.add_task(desc, total=len(files))
        
        for filename in files:
            match = pattern.match(filename)
            if match:
                date_part = match.group(1)
                dest_dir = os.path.join(target_dir, date_part)
                
                if dry_run:
                    console.print(f"[blue]Dry-run:[/blue] {filename} -> {date_part}/")
                else:
                    os.makedirs(dest_dir, exist_ok=True)
                    
                    src_path = os.path.join(target_dir, filename)
                    dest_path = os.path.join(dest_dir, filename)
                    
                    # Handle name collisions
                    if os.path.exists(dest_path):
                        base, ext = os.path.splitext(filename)
                        counter = 1
                        while os.path.exists(os.path.join(dest_dir, f"{base}_{counter}{ext}")):
                            counter += 1
                        dest_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
                    
                    try:
                        shutil.move(src_path, dest_path)
                    except Exception as e:
                        console.print(f"[red]Error moving {filename}: {e}[/red]")
            
            progress.advance(task)

def main():
    parser = argparse.ArgumentParser(description="Sort files starting with YYYYMMDD into YYYYMMDD folders.")
    parser.add_argument("path", nargs="?", default=".", help="Directory to sort (default: current)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without moving files")
    
    args = parser.parse_args()
    sort_files(args.path, args.dry_run)

if __name__ == "__main__":
    main()
