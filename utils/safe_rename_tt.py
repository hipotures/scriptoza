import os
import re
import sys
import logging
import argparse
import tempfile
from datetime import datetime
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, SpinnerColumn

def setup_logging():
    log_filename = f"rename_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
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

def extract_datetime(filename):
    # Pattern 1: YYYY.MM.DD_HH-MM-SS lub YYYY-MM-DD_HH-MM-SS
    m1 = re.search(r'(\d{4})[\.-](\d{2})[\.-](\d{2})[_\s-](\d{2})[\.-](\d{2})[\.-](\d{2})', filename)
    if m1:
        return f"{m1.group(1)}{m1.group(2)}{m1.group(3)}_{m1.group(4)}{m1.group(5)}{m1.group(6)}"
    
    # Pattern 2: YYYY-MM-DD HH_MM (bez sekund)
    m2 = re.search(r'(\d{4})-(\d{2})-(\d{2})\s(\d{2})_(\d{2})', filename)
    if m2:
        return f"{m2.group(1)}{m2.group(2)}{m2.group(3)}_{m2.group(4)}{m2.group(5)}00"

    # Pattern 3: YYYYMMDD_HHMMSS
    m3 = re.search(r'(\d{8})_(\d{6})', filename)
    if m3:
        return f"{m3.group(1)}_{m3.group(2)}"
    
    # Pattern 4: YYYY.MM.DD lub YYYY-MM-DD (sama data)
    m4 = re.search(r'(\d{4})[\.-](\d{2})[\.-](\d{2})', filename)
    if m4:
        return f"{m4.group(1)}{m4.group(2)}{m4.group(3)}_000000"

    return None

def main():
    parser = argparse.ArgumentParser(description='Safe file renamer for TT_out structure (relational mp4 + companions).')
    parser.add_argument('root_dir', help='Root directory (e.g., .../TT_out/)')
    parser.add_argument('--no-dry-run', action='store_true', help='Actually perform the rename operations.')
    args = parser.parse_args()

    dry_run = not args.no_dry_run
    log_file = setup_logging()

    if dry_run:
        logging.warning("RUNNING IN DRY-RUN MODE - No files will be changed.")
    else:
        logging.warning("RUNNING IN EXECUTION MODE - Files will be renamed.")

    root_path = os.path.abspath(args.root_dir)
    if not os.path.isdir(root_path):
        logging.error(f"Root directory does not exist: {root_path}")
        sys.exit(1)

    # Pre-scan subdirectories
    subdirs = sorted([d for d in os.listdir(root_path) if os.path.isdir(os.path.join(root_path, d))])
    
    # Discovery step to count total files for progress bar
    total_files_count = 0
    for subdir in subdirs:
        subdir_path = os.path.join(root_path, subdir)
        total_files_count += len([f for f in os.listdir(subdir_path) if os.path.isfile(os.path.join(subdir_path, f))])

    stats = {
        'total': total_files_count,
        'renamed': 0,
        'skipped_correct': 0,
        'skipped_error': 0,
        'no_date_found': 0,
        'processed': 0
    }

    if stats['total'] == 0:
        logging.warning("No files found to process.")
        sys.exit(0)

    with Progress(
        TextColumn("[bold blue]{task.completed}/{task.total}"),
        TextColumn("[bold magenta]({task.fields[new]} rename / {task.fields[skip]} skip)"),
        BarColumn(bar_width=None),
        TextColumn("[progress.percentage]{task.percentage:>3.1f}%"),
        TextColumn("•"),
        TimeRemainingColumn(),
        SpinnerColumn(),
        expand=True
    ) as progress:
        
        task = progress.add_task("Renaming", total=stats['total'], new=0, skip=0)

        try:
            for subdir in subdirs:
                clean_prefix = subdir.lstrip('.').lstrip('_').strip()
                if not clean_prefix:
                    clean_prefix = subdir

                subdir_path = os.path.join(root_path, subdir)
                all_files = sorted([f for f in os.listdir(subdir_path) if os.path.isfile(os.path.join(subdir_path, f))])
                
                # Relational mapping logic
                rename_map = {}
                mp4_files = [f for f in all_files if f.lower().endswith('.mp4')]
                for f in mp4_files:
                    dt_str = extract_datetime(f)
                    if dt_str:
                        old_base = os.path.splitext(f)[0]
                        new_base = f"{clean_prefix}_{dt_str}"
                        if old_base != new_base:
                            rename_map[old_base] = new_base

                for filename in all_files:
                    if filename.startswith('rename_session_') and filename.endswith('.log'):
                        stats['total'] -= 1 # adjust total
                        progress.update(task, total=stats['total'])
                        continue

                    full_path = os.path.join(subdir_path, filename)
                    
                    matched_old_base = None
                    for old_base in sorted(rename_map.keys(), key=len, reverse=True):
                        if filename.startswith(old_base):
                            matched_old_base = old_base
                            break
                    
                    if not matched_old_base:
                        dt_str = extract_datetime(filename)
                        if not dt_str:
                            logging.info(f"No date/companion: {filename}")
                            stats['no_date_found'] += 1
                            stats['processed'] += 1
                            progress.update(task, skip=stats['skipped_correct'] + stats['no_date_found'] + stats['skipped_error'])
                            progress.advance(task)
                            continue
                        
                        name_part, file_ext = os.path.splitext(filename)
                        if file_ext and (file_ext[1:].isdigit() or len(file_ext) > 5):
                            actual_ext = ""
                        else:
                            actual_ext = file_ext
                        new_filename = f"{clean_prefix}_{dt_str}{actual_ext}"
                    else:
                        new_base = rename_map[matched_old_base]
                        suffix = filename[len(matched_old_base):]
                        new_filename = f"{new_base}{suffix}"

                    new_full_path = os.path.join(subdir_path, new_filename)
                    
                    if filename == new_filename:
                        logging.info(f"Correct: {filename}")
                        stats['skipped_correct'] += 1
                        stats['processed'] += 1
                        progress.update(task, skip=stats['skipped_correct'] + stats['no_date_found'] + stats['skipped_error'])
                        progress.advance(task)
                        continue
                    
                    if os.path.exists(new_full_path):
                        logging.warning(f"CONFLICT: {new_filename} exists. Keeping: {filename}")
                        stats['skipped_error'] += 1
                        stats['processed'] += 1
                        progress.update(task, skip=stats['skipped_correct'] + stats['no_date_found'] + stats['skipped_error'])
                        progress.advance(task)
                        continue

                    if dry_run:
                        logging.info(f"[DRY-RUN] {filename} -> {new_filename}")
                        stats['renamed'] += 1
                    else:
                        try:
                            os.rename(full_path, new_full_path)
                            logging.info(f"RENAMED: {filename} -> {new_filename}")
                            stats['renamed'] += 1
                        except Exception as e:
                            progress.console.print(f"[bold red]ERROR renaming {filename}: {e}")
                            logging.error(f"FAILED {full_path}: {e}")
                            sys.exit(1)
                    
                    stats['processed'] += 1
                    progress.update(task, new=stats['renamed'])
                    progress.advance(task)

        except KeyboardInterrupt:
            progress.console.print("\n[bold yellow]Interrupt received. Stopping...[/bold yellow]")

    report = f"""
========================================
RENAME SESSION REPORT
========================================
Log file: {log_file}
Total files found:          {stats['total']}
Files processed:            {stats['processed']}
Files to be/renamed (new):  {stats['renamed']}
Files already correct:      {stats['skipped_correct']}
Files with no date found:   {stats['no_date_found']}
Errors/Conflicts (skip):    {stats['skipped_error']}
----------------------------------------
Sum check:
{stats['processed']} == {stats['renamed'] + stats['skipped_correct'] + stats['no_date_found'] + stats['skipped_error']}
========================================
"""
    logging.info(report)
    print(report)

if __name__ == "__main__":
    main()