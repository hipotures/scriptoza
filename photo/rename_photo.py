#!/usr/bin/env python3

import subprocess
import json
import os
import concurrent.futures
import threading
import sys
import argparse
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    MofNCompleteColumn,
    TimeElapsedColumn
)
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text
from rich.prompt import Confirm

from rich.table import Table

MAX_THREADS = 24
console = Console()
status_line = Text("", style="dim blue")

def rename_photo_file(filename, progress, task_id, stats, lock, debug=False):
    try:
        if debug:
            status_line.plain = f" → {os.path.basename(filename)}"
            
        result = subprocess.run(['exiftool', '-json', filename], capture_output=True, text=True, check=True)
        exif_data = json.loads(result.stdout)[0]

        # Try to get date with subseconds first, fallback to CreateDate
        subsec_create_date = exif_data.get('SubSecCreateDate') or exif_data.get('SubSecDateTimeOriginal')

        if subsec_create_date:
            # Format: "2025:01:04 17:34:58.625+01:00" -> "20250104_173458_625"
            subsec_create_date = subsec_create_date.split('+')[0]  # Remove timezone
            parts = subsec_create_date.split(' ')
            date_part = parts[0].replace(':', '')
            time_part = parts[1].split('.')
            time_without_ms = time_part[0].replace(':', '')
            milliseconds = time_part[1].ljust(3, '0') if len(time_part) > 1 else '000'
        elif 'CreateDate' in exif_data:
            # Fallback: use CreateDate without milliseconds
            create_date = exif_data['CreateDate']
            create_date = create_date.split('+')[0].replace(':', '').replace(' ', '_')
            date_part = create_date[:8]
            time_without_ms = create_date[9:] if len(create_date) > 8 else '000000'
            milliseconds = '000'
        else:
            # No CreateDate tag
            progress.advance(task_id)
            return

        model = exif_data.get('Model', '')
        filesize = os.path.getsize(filename)

        category = "Other"
        if "ILCE-7M3" in model:
            category = "ILCE-7M3"
        elif "ILCE-7RM5" in model:
            category = "ILCE-7RM5"

        if any(m in model for m in ['ILCE-7M3', 'ILCE-7RM5']):
            # Format: [data]_[czas]_[seq number:3]_[size w bajtach]
            raw_seq = exif_data.get('SequenceNumber', 0)
            try:
                # Force to integer if possible, otherwise default to 0
                seq_val = int(raw_seq)
            except (ValueError, TypeError):
                seq_val = 0
            
            seq_num = str(seq_val).zfill(3)
            base_name = f"{date_part}_{time_without_ms}_{seq_num}_{filesize}"
        else:
            base_name = f"{date_part}_{time_without_ms}_{milliseconds}"

        _, extension = os.path.splitext(filename)
        new_name = f"{base_name}{extension.lower()}"

        if new_name != os.path.basename(filename):
            folder = os.path.dirname(filename) or "."
            full_new_name = os.path.join(folder, new_name)

            counter = 1
            while os.path.exists(full_new_name):
                new_name_with_counter = f"{base_name}_{counter}{extension.lower()}"
                full_new_name = os.path.join(folder, new_name_with_counter)
                counter += 1

            try:
                os.rename(filename, full_new_name)
                with lock:
                    stats[category] += 1
            except Exception as e:
                if debug:
                    console.print(f"[red]Error renaming {filename}: {e}[/red]")
        
        progress.advance(task_id)

    except Exception as e:
        if debug:
            console.print(f"[red]Error processing {filename}: {e}[/red]")
        progress.advance(task_id)

def main():
    parser = argparse.ArgumentParser(description="Rename photos based on EXIF data.")
    parser.add_argument("path", nargs="?", default=".", help="Path to folder or file")
    parser.add_argument("--debug", action="store_true", help="Show currently processed file")
    args = parser.parse_args()

    from pathlib import Path
    target = Path(args.path).resolve()
    extensions = ('.arw', '.jpg', '.jpeg')

    if target.is_file():
        files = [str(target)]
    elif target.is_dir():
        # Smart recursion logic from video script
        positional_args = [a for a in sys.argv[1:] if not a.startswith('-')]
        subdirs = [d for d in target.iterdir() if d.is_dir()]
        recursive = False
        
        if subdirs and not positional_args:
            if Confirm.ask("No arguments provided. Scan current directory and subdirectories?", default=False):
                recursive = True
            else:
                # If user says no, we just scan the top level
                recursive = False

        if recursive:
            files = [str(p) for p in target.rglob("*") if p.is_file() and p.suffix.lower() in extensions]
        else:
            files = [str(p) for p in target.iterdir() if p.is_file() and p.suffix.lower() in extensions]
    else:
        console.print(f"[red]Error: {args.path} is not a directory or file.[/red]")
        sys.exit(1)

    if not files:
        console.print("[yellow]No photo files found.[/yellow]")
        return

    files.sort()

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        expand=False,
        auto_refresh=False
    )

    desc = "Renaming photos".ljust(25)
    task_id = progress.add_task(desc, total=len(files))

    stats = {"ILCE-7M3": 0, "ILCE-7RM5": 0, "Other": 0}
    stats_lock = threading.Lock()

    ui_elements = [progress]
    if args.debug:
        ui_elements.append(status_line)
    ui_group = Group(*ui_elements)

    with Live(ui_group, console=console, refresh_per_second=10):
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            futures = [executor.submit(rename_photo_file, f, progress, task_id, stats, stats_lock, args.debug) for f in files]
            concurrent.futures.wait(futures)
        
        if args.debug:
            status_line.plain = ""
        progress.update(task_id, description="[bold green]Finished![/bold green]".ljust(25))
        progress.refresh()

    # Summary table
    table = Table(title="Renaming Summary", expand=False)
    table.add_column("Model", style="cyan")
    table.add_column("Renamed Files", justify="right", style="green")

    total_renamed = 0
    for model, count in stats.items():
        table.add_row(model, str(count))
        total_renamed += count
    
    table.add_section()
    table.add_row("[bold]Total[/bold]", f"[bold]{total_renamed}[/bold]")
    
    console.print(table)

if __name__ == "__main__":
    main()
