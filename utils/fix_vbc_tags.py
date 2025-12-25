import os
import sys
import logging
import argparse
import tempfile
import subprocess
import json
from pathlib import Path
from datetime import datetime
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, SpinnerColumn

def setup_logging():
    log_filename = f"fix_vbc_tags_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_filepath = os.path.join(tempfile.gettempdir(), log_filename)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    fh = logging.FileHandler(log_filepath, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return log_filepath

def get_file_dates(filepath):
    try:
        stat = os.stat(filepath)
        mtime = datetime.fromtimestamp(stat.st_mtime)
        try:
            ctime = datetime.fromtimestamp(stat.st_birthtime)
        except AttributeError:
            ctime = datetime.fromtimestamp(stat.st_ctime)
        
        latest = max(mtime, ctime)
        offset = datetime.now().astimezone().strftime('%z')
        offset_formatted = f"{offset[:3]}:{offset[3:]}"
        return latest.strftime('%Y:%m:%d %H:%M:%S') + offset_formatted
    except Exception:
        return datetime.now().strftime('%Y:%m:%d %H:%M:%S') + "+01:00"

def get_existing_tags(filepath, config_path):
    try:
        # Dodajemy -m tutaj rowniez
        cmd = ["exiftool", "-m"]
        if config_path:
            cmd.extend(["-config", str(config_path)])
        cmd.extend(["-XMP:VBCEncoder", "-j", filepath])
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        if data and "VBCEncoder" in data[0]:
            return data[0]["VBCEncoder"]
    except Exception:
        pass
    return None

def main():
    parser = argparse.ArgumentParser(description='Fix/Add missing VBC tags to MP4 files.')
    parser.add_argument('root_dir', help='Directory to scan recursively')
    parser.add_argument('--no-dry-run', action='store_true', help='Actually write tags to files.')
    args = parser.parse_args()

    dry_run = not args.no_dry_run
    log_file = setup_logging()

    if dry_run:
        logging.warning("RUNNING IN DRY-RUN MODE - No metadata will be modified.")
    else:
        logging.warning("RUNNING IN EXECUTION MODE - Writing metadata tags.")

    root_path = os.path.abspath(args.root_dir)
    if not os.path.isdir(root_path):
        logging.error(f"Directory does not exist: {root_path}")
        sys.exit(1)

    script_dir = Path(__file__).resolve().parent
    config_path = script_dir.parent / "conf" / "exiftool.conf"
    if not config_path.exists():
        logging.error(f"ExifTool config not found at: {config_path}")
        sys.exit(1)

    stats = {
        'total': 0,
        'tagged': 0,
        'skipped_has_tags': 0,
        'skipped_empty': 0,
        'skipped_error': 0
    }

    # Discovery
    mp4_files = []
    for root, dirs, files in os.walk(root_path):
        for filename in files:
            if filename.lower().endswith('.mp4'):
                mp4_files.append(os.path.join(root, filename))
    
    stats['total'] = len(mp4_files)
    if stats['total'] == 0:
        logging.warning("No MP4 files found.")
        sys.exit(0)

    with Progress(
        TextColumn("[bold blue]{task.completed}/{task.total}"),
        TextColumn("[bold magenta]({task.fields[new]} new / {task.fields[skip]} skip)"),
        BarColumn(bar_width=None),
        TextColumn("[progress.percentage]{task.percentage:>3.1f}%"),
        TextColumn("•"),
        TimeRemainingColumn(),
        SpinnerColumn(),
        expand=True
    ) as progress:
        
        task = progress.add_task("Processing", total=stats['total'], new=0, skip=0)
        
        for filepath in sorted(mp4_files):
            filename = os.path.basename(filepath)
            
            # 1. Check size
            try:
                if os.path.getsize(filepath) == 0:
                    logging.info(f"Skipping empty: {filename}")
                    stats['skipped_empty'] += 1
                    progress.update(task, skip=stats['skipped_has_tags'] + stats['skipped_empty'])
                    progress.advance(task)
                    continue
            except Exception as e:
                logging.error(f"Size error {filename}: {e}")
                stats['skipped_error'] += 1
                progress.advance(task)
                continue

            # 2. Check existing tags
            existing = get_existing_tags(filepath, config_path)
            if existing:
                logging.info(f"Skipping (has tags): {filename}")
                stats['skipped_has_tags'] += 1
                progress.update(task, skip=stats['skipped_has_tags'] + stats['skipped_empty'])
                progress.advance(task)
                continue

            # 3. Tagging
            finished_at = get_file_dates(filepath)
            tags = {
                "XMP:VBCEncoder": "NVENC AV1 (GPU)",
                "XMP:VBCFinishedAt": finished_at,
                "XMP:VBCOriginalName": filename,
                "XMP:VBCOriginalSize": -1
            }

            if dry_run:
                logging.info(f"[DRY-RUN] Tagging: {filename}")
                stats['tagged'] += 1
            else:
                try:
                    # Dodajemy -m, -unsafe oraz capture_output dla lepszego debugowania
                    cmd = ["exiftool", "-config", str(config_path), "-m", "-unsafe", "-overwrite_original"]
                    for k, v in tags.items():
                        cmd.append(f"-{k}={v}")
                    cmd.append(filepath)
                    
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                    logging.info(f"TAGGED: {filename}")
                    stats['tagged'] += 1
                except subprocess.CalledProcessError as e:
                    error_msg = e.stderr.strip() if e.stderr else str(e)
                    progress.console.print(f"[bold red]ERROR tagging {filename}: {error_msg}")
                    logging.error(f"FAILED {filepath}: {error_msg}")
                    stats['skipped_error'] += 1
                    # Decyzja: czy przerywac (sys.exit) czy kontynuowac? 
                    # Twoja wczesniejsza instrukcja dla rename byla "przerwac natychmiast".
                    sys.exit(1)
                except Exception as e:
                    progress.console.print(f"[bold red]ERROR: {str(e)}")
                    logging.error(f"UNEXPECTED FAILED {filepath}: {str(e)}")
                    sys.exit(1)
            
            progress.update(task, new=stats['tagged'])
            progress.advance(task)

    report = f"""
========================================
VBC TAG FIX REPORT
========================================
Log file: {log_file}
Config:   {config_path}
Total MP4 files found:      {stats['total']}
Files newly tagged:         {stats['tagged']}
Files already tagged:       {stats['skipped_has_tags']}
Empty files skipped:        {stats['skipped_empty']}
Errors:                     {stats['skipped_error']}
----------------------------------------
Sum check:
{stats['total']} == {stats['tagged'] + stats['skipped_has_tags'] + stats['skipped_empty'] + stats['skipped_error']}
========================================
"""
    logging.info(report)
    print(report)

if __name__ == "__main__":
    main()
