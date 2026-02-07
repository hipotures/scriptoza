#!/usr/bin/env python3
import os
import shutil
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

console = Console()

def main():
    # Directories
    repo_dir = Path(__file__).parent.parent.resolve()
    bin_dir = Path.home() / ".local" / "bin"
    config_dir = Path.home() / ".config" / "scriptoza"

    console.print(Panel.fit("[bold blue]🚀 Scriptoza Installer[/bold blue]", border_style="blue"))

    # Ensure directories exist
    bin_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)

    scripts = [
        ("video/rename_video_univ.py", "rename-video-univ"),
        ("video/rename_video_by_tags.py", "rename-video-by-tags"),
        ("video/rename_video_by_tags.py", "rename-video"),
        ("video/check_4k.py", "check-4k"),
        ("video/sort_dji.py", "sort-dji"),
        ("video/sort_video_dated.py", "sort-video-dated"),
        ("photo/rename_photo.py", "rename-photo"),
        ("utils/migrate.py", "migrate-tt"),
    ]

    configs = [
        ("video/rename_video.yaml", "rename_video.yaml"),
    ]

    table = Table(show_header=True, header_style="bold magenta", box=None)
    table.add_column("Type", style="dim", width=8)
    table.add_column("Source", style="cyan")
    table.add_column("➜", justify="center", width=3)
    table.add_column("Destination Name", style="green")
    table.add_column("Status", justify="right")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task("Installing items...", total=len(scripts) + len(configs))

        for src_rel, dest_name in scripts:
            src = repo_dir / src_rel
            dest = bin_dir / dest_name
            status = "[bold green]DONE[/bold green]"
            
            if src.exists():
                try:
                    shutil.copy2(src, dest)
                    dest.chmod(0o755)
                except Exception as e:
                    status = f"[bold red]ERR: {e}[/bold red]"
            else:
                status = "[bold yellow]MISSING[/bold yellow]"
            
            table.add_row("Script", src_rel, "➜", dest_name, status)
            progress.advance(task)

        for src_rel, dest_name in configs:
            src = repo_dir / src_rel
            dest = config_dir / dest_name
            status = "[bold green]DONE[/bold green]"
            
            if src.exists():
                try:
                    shutil.copy2(src, dest)
                except Exception as e:
                    status = f"[bold red]ERR: {e}[/bold red]"
            else:
                status = "[bold yellow]MISSING[/bold yellow]"

            table.add_row("Config", src_rel, "➜", dest_name, status)
            progress.advance(task)

    console.print(table)
    
    console.print(f"
[bold green]✅ Installation finished successfully![/bold green]")
    console.print(f"[dim]Scripts installed to: {bin_dir}[/dim]")
    console.print(f"[dim]Configs installed to: {config_dir}[/dim]")
    console.print("
[yellow]Note:[/yellow] The 'by tags' script is available as both [bold cyan]rename-video-by-tags[/bold cyan] and [bold cyan]rename-video[/bold cyan].")

if __name__ == "__main__":
    main()
