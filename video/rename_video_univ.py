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

# Konfiguracja
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

def get_metadata_mediainfo(nazwa_pliku):
    try:
        wynik = subprocess.run(['mediainfo', '--Output=JSON', nazwa_pliku], capture_output=True, text=True, check=True)
        dane = json.loads(wynik.stdout)
        tracks = dane.get('media', {}).get('track', [])
        general = next((t for t in tracks if t.get('@type') == 'General'), {})
        video = next((t for t in tracks if t.get('@type') == 'Video'), {})
        raw_date = general.get('File_Modified_Date_Local') or general.get('Encoded_Date')
        return {
            'date': clean_date(raw_date),
            'width': video.get('Width', '0'),
            'height': video.get('Height', '0'),
            'fps': format_fps(video.get('FrameRate')),
            'size': general.get('FileSize') or str(os.path.getsize(nazwa_pliku))
        }
    except: return None

def get_metadata_exif(nazwa_pliku):
    try:
        wynik = subprocess.run(['exiftool', '-json', nazwa_pliku], capture_output=True, text=True, check=True)
        dane_exif = json.loads(wynik.stdout)[0]
        def get_tag(keys):
            for k in keys:
                val = dane_exif.get(k)
                if val is not None and str(val).lower() not in ('n/a', '', 'none', '0000:00:00 00:00:00'): return val
            return None
        return {
            'date': clean_date(get_tag(TAG_ALIASES_EXIF['date'])),
            'width': get_tag(TAG_ALIASES_EXIF['width']) or '0',
            'height': get_tag(TAG_ALIASES_EXIF['height']) or '0',
            'fps': format_fps(get_tag(TAG_ALIASES_EXIF['fps'])),
            'size': str(get_tag(['MediaDataSize'])) or str(os.path.getsize(nazwa_pliku))
        }
    except: return None

def bezpieczna_zmiana_nazwy(src, dst):
    if os.path.exists(dst):
        return False, "Cel już istnieje"
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

def zmien_nazwe_pliku(nazwa_pliku, mode, debug, progress, task_id, root_path):
    stara_nazwa_base = os.path.basename(nazwa_pliku)
    if debug:
        rel_path = os.path.relpath(nazwa_pliku, root_path)
        status_line.plain = f" → {rel_path}"

    meta = get_metadata_mediainfo(nazwa_pliku) if mode == 'mediainfo' else get_metadata_exif(nazwa_pliku)
    
    if meta:
        date_part = meta['date'] or os.path.splitext(stara_nazwa_base)[0]
        res = f"{meta['width']}x{meta['height']}"
        ext = os.path.splitext(nazwa_pliku)[1].lower()
        base_new_name = f"{date_part}_{res}_{meta['fps']}_{meta['size']}"
        nowa_nazwa = f"{base_new_name}{ext}"

        if nowa_nazwa != stara_nazwa_base:
            folder = os.path.dirname(nazwa_pliku) or '.'
            pelna_nowa_sciezka = os.path.join(folder, nowa_nazwa)
            licznik = 1
            while os.path.exists(pelna_nowa_sciezka):
                nowa_nazwa = f"{base_new_name}_{licznik}{ext}"
                pelna_nowa_sciezka = os.path.join(folder, nowa_nazwa)
                licznik += 1
            ok, err = bezpieczna_zmiana_nazwy(nazwa_pliku, pelna_nowa_sciezka)
            if not ok and debug:
                status_line.plain = f" [red]BŁĄD:[/red] {stara_nazwa_base} -> {err}"
    
    progress.advance(task_id)

def main():
    try:
        parser = argparse.ArgumentParser(description="Uniwersalny skrypt do zmiany nazw wideo.")
        parser.add_argument("path", nargs="?", default=".", help="Ścieżka do folderu lub pliku")
        parser.add_argument("--debug", action="store_true", help="Pokaż aktualnie przetwarzany plik pod paskiem")
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--exif", action="store_const", dest="mode", const="exif", help="Użyj ExifTool")
        group.add_argument("--mediainfo", action="store_const", dest="mode", const="mediainfo", help="Użyj MediaInfo (domyślne)")
        parser.set_defaults(mode="mediainfo")
        
        args = parser.parse_args()
        target = Path(args.path).resolve()

        if target.is_file():
            zmien_nazwe_pliku(str(target), args.mode, False, type('Mock', (object,), {'update': lambda *a, **k: None, 'advance': lambda *a, **k: None})(), None, target.parent)
            console.print(f"[green]Przetworzono:[/green] {target}")
            return

        positional_args = [a for a in sys.argv[1:] if not a.startswith('-')]
        subdirs = [d for d in target.iterdir() if d.is_dir()]
        recursive = False
        
        if subdirs and not positional_args:
            if Confirm.ask("Nie podano argumentów. Czy skanować bieżący katalog i podkatalogi?", default=False):
                recursive = True
            else:
                console.print("[yellow]Anulowano.[/yellow]")
                return

        if recursive:
            pliki = [str(p) for p in target.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS]
        else:
            pliki = [str(p) for p in target.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS]

        if not pliki:
            console.print("[yellow]Brak plików wideo w wybranym trybie.[/yellow]")
            return
        
        pliki.sort()

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

        desc = f"Zmiana nazw ({args.mode})".ljust(25)
        task_id = progress.add_task(desc, total=len(pliki))
        
        ui_elements = [progress]
        if args.debug: ui_elements.append(status_line)
        ui_group = Group(*ui_elements)

        with Live(ui_group, console=console, refresh_per_second=10):
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
                futures = [executor.submit(zmien_nazwe_pliku, p, args.mode, args.debug, progress, task_id, target) for p in pliki]
                concurrent.futures.wait(futures)
            
            if args.debug: status_line.plain = ""
            progress.update(task_id, description="[bold green]Zakończono![/bold green]".ljust(25))
            progress.refresh()

    except KeyboardInterrupt:
        console.print("\n[yellow]Przerwano przez użytkownika (Ctrl-C).[/yellow]")
        sys.exit(130)

if __name__ == "__main__":
    main()