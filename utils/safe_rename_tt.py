import os
import re
import sys
import logging
import argparse
from datetime import datetime

def setup_logging():
    log_filename = f"rename_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return log_filename

def extract_datetime(filename):
    # Pattern 1: YYYY.MM.DD_HH-MM-SS (z kropkami i myślnikami)
    m1 = re.search(r'(\d{4})[\.-](\d{2})[\.-](\d{2})[_\s](\d{2})[\.-](\d{2})[\.-](\d{2})', filename)
    if m1:
        return f"{m1.group(1)}{m1.group(2)}{m1.group(3)}_{m1.group(4)}{m1.group(5)}{m1.group(6)}"
    
    # Pattern 2: YYYY-MM-DD HH_MM (bez sekund, np. z Twojego przykładu z emoji)
    m2 = re.search(r'(\d{4})-(\d{2})-(\d{2})\s(\d{2})_(\d{2})', filename)
    if m2:
        return f"{m2.group(1)}{m2.group(2)}{m2.group(3)}_{m2.group(4)}{m2.group(5)}00"

    # Pattern 3: YYYYMMDD_HHMMSS (już prawie poprawny)
    m3 = re.search(r'(\d{8})_(\d{6})', filename)
    if m3:
        return f"{m3.group(1)}_{m3.group(2)}"
    
    # Pattern 4: YYYY.MM.DD (sama data)
    m4 = re.search(r'(\d{4})[\.-](\d{2})[\.-](\d{2})', filename)
    if m4:
        return f"{m4.group(1)}{m4.group(2)}{m4.group(3)}_000000"

    return None

def main():
    parser = argparse.ArgumentParser(description='Safe file renamer for TT_out structure.')
    parser.add_argument('root_dir', help='Root directory (e.g., .../TT_out/)')
    parser.add_argument('--no-dry-run', action='store_true', help='Actually perform the rename operations.')
    args = parser.parse_args()

    dry_run = not args.no_dry_run
    log_file = setup_logging()

    if dry_run:
        logging.info("RUNNING IN DRY-RUN MODE - No files will be changed.")
    else:
        logging.info("RUNNING IN EXECUTION MODE - Files will be renamed.")

    root_path = os.path.abspath(args.root_dir)
    if not os.path.isdir(root_path):
        logging.error(f"Root directory does not exist: {root_path}")
        sys.exit(1)

    stats = {
        'total': 0,
        'renamed': 0,
        'skipped_correct': 0,
        'skipped_error': 0,
        'no_date_found': 0
    }

    try:
        # List subdirectories (1 level deep)
        subdirs = [d for d in os.listdir(root_path) if os.path.isdir(os.path.join(root_path, d))]
        
        for subdir in sorted(subdirs):
            subdir_path = os.path.join(root_path, subdir)
            files = [f for f in os.listdir(subdir_path) if os.path.isfile(os.path.join(subdir_path, f))]
            
            for filename in sorted(files):
                stats['total'] += 1
                file_ext = os.path.splitext(filename)[1]
                full_path = os.path.join(subdir_path, filename)
                
                dt_str = extract_datetime(filename)
                if not dt_str:
                    logging.warning(f"Could not find date in filename: {full_path}")
                    stats['no_date_found'] += 1
                    continue
                
                new_filename = f"{subdir}_{dt_str}{file_ext}"
                new_full_path = os.path.join(subdir_path, new_filename)
                
                if filename == new_filename:
                    logging.info(f"Skipping (already correct): {filename}")
                    stats['skipped_correct'] += 1
                    continue
                
                if os.path.exists(new_full_path):
                    logging.warning(f"CONFLICT: Destination file already exists: {new_full_path}. Keeping original name for: {full_path}")
                    stats['skipped_error'] += 1
                    continue

                if dry_run:
                    logging.info(f"[DRY-RUN] Would rename: {filename} -> {new_filename}")
                    stats['renamed'] += 1
                else:
                    try:
                        os.rename(full_path, new_full_path)
                        logging.info(f"RENAMED: {filename} -> {new_filename}")
                        stats['renamed'] += 1
                    except Exception as e:
                        logging.error(f"FATAL ERROR: Failed to rename {full_path} to {new_full_path}: {str(e)}")
                        sys.exit(1)

    except Exception as e:
        logging.error(f"An unexpected error occurred: {str(e)}")
        sys.exit(1)

    # Final Report
    report = f"""
========================================
RENAME SESSION REPORT
========================================
Log file: {log_file}
Total files processed:      {stats['total']}
Files to be/renamed:        {stats['renamed']}
Files already correct:      {stats['skipped_correct']}
Files with no date found:   {stats['no_date_found']}
Errors/Conflicts:           {stats['skipped_error']}
----------------------------------------
Sum check (Total == Renamed + Correct + NoDate + Error):
{stats['total']} == {stats['renamed'] + stats['skipped_correct'] + stats['no_date_found'] + stats['skipped_error']}
========================================
"""
    logging.info(report)
    
    if stats['total'] != (stats['renamed'] + stats['skipped_correct'] + stats['no_date_found'] + stats['skipped_error']):
        logging.error("CRITICAL: Statistics mismatch!")
        sys.exit(1)

if __name__ == "__main__":
    main()
