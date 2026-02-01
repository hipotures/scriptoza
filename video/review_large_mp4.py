#!/usr/bin/env python3
import os
import argparse
import subprocess
import math
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TaskProgressColumn, TimeElapsedColumn

def format_size(size_bytes):
    if size_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def get_file_size(path):
    try:
        return path.stat().st_size
    except OSError:
        return 0

def main():
    parser = argparse.ArgumentParser(description="Find and review top N largest mp4 files.")
    parser.add_argument("n", type=int, help="Number of largest files to show.")
    args = parser.parse_args()

    console = Console()
    
    mp4_files = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        expand=False,
        console=console
    ) as progress:
        task = progress.add_task("Searching for mp4 files...".ljust(25), total=None)
        
        for path in Path(".").rglob("*.mp4"):
            mp4_files.append({
                "path": path,
                "size": get_file_size(path)
            })
            progress.update(task, advance=1)
        
        # Once search is done, update total to show X/X instead of X/?
        total_found = len(mp4_files)
        progress.update(task, total=total_found, description="Sorting files...".ljust(25))
        mp4_files.sort(key=lambda x: x["size"], reverse=True)
        
    top_n = mp4_files[:args.n]
    
    if not top_n:
        console.print("[yellow]No mp4 files found.[/yellow]")
        return

    table = Table(title=f"Top {args.n} Largest MP4 Files", expand=False)
    table.add_column("Rank", justify="right", style="cyan", no_wrap=True)
    table.add_column("Relative Path", style="magenta")
    table.add_column("Size", justify="right", style="green")

    for i, item in enumerate(top_n, 1):
        table.add_row(
            str(i),
            str(item["path"]),
            format_size(item["size"])
        )

    console.print(table)

    if not Confirm.ask("Do you want to review these files?"):
        return

    for item in top_n:
        file_path = item["path"]
        if not file_path.exists():
            console.print(f"[yellow]File {file_path} no longer exists. Skipping.[/yellow]")
            continue

        console.print(f"\n[bold]Playing:[/bold] {file_path}")
        try:
            subprocess.run(["smplayer", str(file_path)], check=False)
        except FileNotFoundError:
            console.print("[red]Error: smplayer not found. Please install it or ensure it's in your PATH.[/red]")
            break

        if Confirm.ask(f"Do you want to delete [bold red]{file_path}[/bold red]?"):
            try:
                file_path.unlink()
                console.print(f"[green]Deleted:[/green] {file_path}")
            except OSError as e:
                console.print(f"[red]Error deleting {file_path}: {e}[/red]")
        else:
            console.print(f"[blue]Kept:[/blue] {file_path}")

if __name__ == "__main__":
    main()
