#!/usr/bin/env python3
import subprocess
import json
import os
import concurrent.futures
import sys
import argparse
from pathlib import Path
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

# Configuration
MAX_THREADS = 8
EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv', '.m4v', '.3gp', '.mts')

TAG_ALIASES_EXIF = {
    'date': ['SubSecCreateDate', 'CreateDate', 'MediaCreateDate', 'TrackCreateDate', 'DateTimeOriginal', 'ModifyDate', 'FileModifyDate'],
    'width': ['ImageWidth', 'SourceImageWidth', 'ExifImageWidth', 'VideoWidth'],
    'height': ['ImageHeight', 'SourceImageHeight', 'ExifImageHeight', 'VideoHeight'],
    'fps': ['VideoFrameRate', 'FrameRate', 'VideoAvgFrameRate'],
    'size_bytes': ['MediaDataSize', 'FileSize']
}

console = Console()
status_line = Text("", style="dim blue")

def clean_date(raw_date):
    if not raw_date: return None
    clean = str(raw_date).replace('UTC', '').strip().split('+')[0].split('.')[0]
    return clean.replace(':', '').replace('-', '').replace(' ', '_')

def format_fps(raw_fps):
    if raw_fps is None or str(raw_fps).lower() in ('n/a', ''): return "0fps"
    try: return f"{int(round(float(raw_fps)))}fps"
    except (ValueError, TypeError): return "0fps"

def get_exif_value(filename, tag):
    try:
        result = subprocess.run(['exiftool', '-json', filename], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)[0]
        return data.get(tag)
    except:
        return None

def get_metadata_mediainfo(filename, use_vbc_size=False):
    try:
        result = subprocess.run(['mediainfo', '--Output=JSON', filename], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        tracks = data.get('media', {}).get('track', [])
        general = next((t for t in tracks if t.get('@type') == 'General'), {})
        video = next((t for t in tracks if t.get('@type') == 'Video'), {})
        raw_date = general.get('File_Modified_Date_Local') or general.get('Encoded_Date')
        
        file_size = general.get('FileSize') or str(os.path.getsize(filename))
        if use_vbc_size:
            # Try to find VBCOriginalSize in General or Video tracks
            custom = general.get('VBCOriginalSize')
            if not custom:
                # Fallback: MediaInfo often doesn't show VBCOriginalSize. Try ExifTool specifically for this tag.
                try:
                    et_result = subprocess.run(['exiftool', '-json', '-VBCOriginalSize', filename], capture_output=True, text=True, check=True)
                    et_data = json.loads(et_result.stdout)[0]
                    custom = et_data.get('VBCOriginalSize')
                except Exception:
                    pass
            
            if custom: file_size = str(custom)

        return {
            'date': clean_date(raw_date),
            'width': video.get('Width', '0'),
            'height': video.get('Height', '0'),
            'fps': format_fps(video.get('FrameRate')),
            'size': file_size
        }
    except: return None

def get_metadata_exif(filename, use_vbc_size=False):
    try:
        result = subprocess.run(['exiftool', '-json', filename], capture_output=True, text=True, check=True)
        exif_data = json.loads(result.stdout)[0]
        def get_tag(keys):
            for k in keys:
                val = exif_data.get(k)
                if val is not None and str(val).lower() not in ('n/a', '', 'none', '0000:00:00 00:00:00'): return val
            return None
        
        size_val = None
        if use_vbc_size:
            size_val = exif_data.get('VBCOriginalSize')
            
        if not size_val:
            size_val = str(get_tag(['MediaDataSize'])) or str(os.path.getsize(filename))
        else:
            size_val = str(size_val)

        return {
            'date': clean_date(get_tag(TAG_ALIASES_EXIF['date'])),
            'width': get_tag(TAG_ALIASES_EXIF['width']) or '0',
            'height': get_tag(TAG_ALIASES_EXIF['height']) or '0',
            'fps': format_fps(get_tag(TAG_ALIASES_EXIF['fps'])),
            'size': size_val
        }
    except: return None

def safe_rename(src, dst):
    if os.path.exists(dst):
        return False, "Destination already exists"
    try:
        os.link(src, dst)
        os.unlink(src)
        return True, None
    except OSError:
        try:
            os.rename(src, dst)
            return True, None
        except Exception as e_inner:
            return False, str(e_inner)

def rename_file(filename, mode, debug, progress, task_id, root_path, use_vbc_size=False):
    old_name_base = os.path.basename(filename)
    if debug:
        rel_path = os.path.relpath(filename, root_path)
        status_line.plain = f" → {rel_path}"

    meta = get_metadata_mediainfo(filename, use_vbc_size) if mode == 'mediainfo' else get_metadata_exif(filename, use_vbc_size)
    
    if meta:
        date_part = meta['date'] or os.path.splitext(old_name_base)[0]
        res = f"{meta['width']}x{meta['height']}"
        ext = os.path.splitext(filename)[1].lower()
        base_new_name = f"{date_part}_{res}_{meta['fps']}_{meta['size']}"
        new_name = f"{base_new_name}{ext}"

        if new_name != old_name_base:
            folder = os.path.dirname(filename) or '.'
            full_new_path = os.path.join(folder, new_name)
            
            counter = 1
            while os.path.exists(full_new_path):
                new_name = f"{base_new_name}_{counter}{ext}"
                full_new_path = os.path.join(folder, new_name)
                counter += 1
            
            ok, err = safe_rename(filename, full_new_path)
            if not ok and debug:
                status_line.plain = f" [red]ERROR:[/red] {old_name_base} -> {err}"
    
    progress.advance(task_id)

def main():
    try:
        parser = argparse.ArgumentParser(description="Universal video renaming script.")
        parser.add_argument("path", nargs="?", default=".", help="Path to folder or file")
        parser.add_argument("--debug", action="store_true", help="Show currently processed file under the progress bar")
        parser.add_argument("--use-vbc-size", action="store_true", help="Use VBCOriginalSize tag for file size if available")
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--exif", action="store_const", dest="mode", const="exif", help="Use ExifTool")
        group.add_argument("--mediainfo", action="store_const", dest="mode", const="mediainfo", help="Use MediaInfo (default)")
        parser.set_defaults(mode="mediainfo")
        
        args = parser.parse_args()
        target = Path(args.path).resolve()

        if target.is_file():
            rename_file(str(target), args.mode, False, type('Mock', (object,), {'update': lambda *a, **k: None, 'advance': lambda *a, **k: None})(), None, target.parent, args.use_vbc_size)
            console.print(f"[green]Processed:[/green] {target}")
            return

        positional_args = [a for a in sys.argv[1:] if not a.startswith('-')]
        subdirs = [d for d in target.iterdir() if d.is_dir()]
        recursive = False
        
        if subdirs and not positional_args:
            if Confirm.ask("No arguments provided. Scan current directory and subdirectories?", default=False):
                recursive = True
            else:
                console.print("[yellow]Cancelled.[/yellow]")
                return

        if recursive:
            files = [str(p) for p in target.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS]
        else:
            files = [str(p) for p in target.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS]

        if not files:
            console.print("[yellow]No video files found in selected mode.[/yellow]")
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

        desc = f"Renaming ({args.mode})".ljust(25)
        task_id = progress.add_task(desc, total=len(files))
        
        ui_elements = [progress]
        if args.debug: ui_elements.append(status_line)
        ui_group = Group(*ui_elements)

        with Live(ui_group, console=console, refresh_per_second=10):
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
                futures = [executor.submit(rename_file, p, args.mode, args.debug, progress, task_id, target, args.use_vbc_size) for p in files]
                concurrent.futures.wait(futures)
            
            if args.debug: status_line.plain = ""
            progress.update(task_id, description="[bold green]Finished![/bold green]".ljust(25))
            progress.refresh()

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user (Ctrl-C).[/yellow]")
        sys.exit(130)

if __name__ == "__main__":
    main()
