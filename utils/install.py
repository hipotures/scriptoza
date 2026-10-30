#!/usr/bin/env python3
import argparse
import shutil
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

console = Console()

def main():
    parser = argparse.ArgumentParser(description="Install Scriptoza utilities (preview by default).")
    parser.add_argument("--run", action="store_true", help="Apply installation changes")
    args = parser.parse_args()
    if not args.run:
        console.print("[yellow]DRY RUN: no files will change. Use --run to install.[/yellow]")

    # Directories
    repo_dir = Path(__file__).parent.parent.resolve()
    bin_dir = Path.home() / ".local" / "bin"
    config_dir = Path.home() / ".config" / "scriptoza"
    systemd_user_dir = Path.home() / ".config" / "systemd" / "user"

    console.print(Panel.fit("[bold blue]🚀 Scriptoza Installer[/bold blue]", border_style="blue"))

    # Ensure directories exist
    if args.run:
        for directory in (bin_dir, config_dir, systemd_user_dir):
            directory.mkdir(parents=True, exist_ok=True)

    scripts = [
        ("utils/yubikey_touch_sound.py", "yubikey_touch_sound.py"),
        ("video/rename_video_univ.py", "rename-video-univ"),
        ("video/rename_video_by_tags.py", "rename-video-by-tags"),
        ("video/rename_video_by_tags.py", "rename-video"),
        ("video/check_4k.py", "check-4k"),
        ("video/follow_crop_to_audio.py", "follow-crop-to-audio"),
        ("video/sort_dji.py", "sort-dji"),
        ("video/sort_video_dated.py", "sort-video-dated"),
        ("video/video_rotation_detector.py", "video-rotation-detector"),
        ("video/separate_screen_recordings.py", "separate-screen-recordings"),
        ("photo/rename_photo.py", "rename-photo"),
        ("photo/convert_hif_to_jpg.py", "convert-hif-to-jpg"),
        ("ai/codex_resume.py", "codex-resume"),
        ("utils/organize_by_date.py", "organize-by-date"),
        ("utils/migrate.py", "migrate-tt"),
        ("utils/musescore_export_mp3_with_tags.py", "musescore-export-mp3-with-tags"),
        ("utils/wav_to_mp3.py", "wav-to-mp3"),
    ]

    configs = [
        ("video/rename_video.yaml", "rename_video.yaml"),
    ]

    services = [
        ("utils/yubikey-touch-sound.service", systemd_user_dir / "yubikey-touch-sound.service"),
        ("ai/codex-resume.service", systemd_user_dir / "codex-resume.service"),
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
        task = progress.add_task(
            "Installing items...",
            total=len(scripts) + len(configs) + len(services),
        )

        for src_rel, dest_name in scripts:
            src = repo_dir / src_rel
            dest = bin_dir / dest_name
            status = "[bold green]DONE[/bold green]" if args.run else "[yellow]WOULD COPY[/yellow]"
            
            if src.exists():
                try:
                    if args.run:
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
            status = "[bold green]DONE[/bold green]" if args.run else "[yellow]WOULD COPY[/yellow]"
            
            if src.exists():
                try:
                    if args.run:
                        shutil.copy2(src, dest)
                except Exception as e:
                    status = f"[bold red]ERR: {e}[/bold red]"
            else:
                status = "[bold yellow]MISSING[/bold yellow]"

            table.add_row("Config", src_rel, "➜", dest_name, status)
            progress.advance(task)

        for src_rel, dest in services:
            src = repo_dir / src_rel
            status = "[bold green]DONE[/bold green]" if args.run else "[yellow]WOULD COPY[/yellow]"

            if src.exists():
                try:
                    if args.run:
                        shutil.copy2(src, dest)
                except Exception as e:
                    status = f"[bold red]ERR: {e}[/bold red]"
            else:
                status = "[bold yellow]MISSING[/bold yellow]"

            table.add_row("Service", src_rel, "➜", str(dest), status)
            progress.advance(task)

    console.print(table)
    
    console.print("\nInstallation finished." if args.run else "\nDRY RUN complete. Use --run to install.")
    console.print(f"[dim]Scripts installed to: {bin_dir}[/dim]")
    console.print(f"[dim]Configs installed to: {config_dir}[/dim]")
    console.print(f"[dim]User services installed to: {systemd_user_dir}[/dim]")
    console.print("Enable YubiKey sounds: systemctl --user daemon-reload && systemctl --user enable --now yubikey-touch-sound.service")
    console.print("\n[yellow]Note:[/yellow] The 'by tags' script is available as both [bold cyan]rename-video-by-tags[/bold cyan] and [bold cyan]rename-video[/bold cyan].")

if __name__ == "__main__":
    main()
