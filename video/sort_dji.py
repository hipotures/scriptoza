#!/usr/bin/env python3
import os
import subprocess
import shutil
import sys

def sort_dji_files(target_dir):
    """
    Identifies files with EXIF tag 'Model' set to 'DJI Pocket'
    and moves them to a 'dji' subdirectory within the target directory.
    Only scans the top level of target_dir.
    """
    if not os.path.isdir(target_dir):
        print(f"Skipping {target_dir}: not a directory.")
        return

    # Output directory 'dji' relative to the target directory
    dji_dir = os.path.join(target_dir, 'dji')

    try:
        # Support for:
        # - Model: DJI Pocket (Original/Pocket 2)
        # - Encoder: DJI OsmoPocket3 (Pocket 3)
        # Using ($Tag || "") to avoid Perl errors if a tag is missing
        cmd = [
            'exiftool',
            '-q', '-q',
            '-if', '($Model || "") =~ /Pocket/ or ($Encoder || "") =~ /Pocket/',
            '-filename',
            '-s3',
            target_dir
        ]

        print(f"Scanning {target_dir}...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        output = result.stdout.strip()
        if not output:
            print(f"  No DJI Pocket/Osmo files found in {target_dir}")
            return

        files_to_move = output.split('\n')

        # Create 'dji' directory if it doesn't exist
        if not os.path.exists(dji_dir):
            os.makedirs(dji_dir)
            print(f"  Created directory: {dji_dir}")

        moved_count = 0
        for filename in files_to_move:
            if not filename:
                continue
            
            src = os.path.join(target_dir, filename)
            dst = os.path.join(dji_dir, filename)

            if os.path.isdir(src):
                continue

            if os.path.exists(dst):
                print(f"  Skipping {filename}: already exists in destination.")
                continue

            try:
                shutil.move(src, dst)
                print(f"  Moved: {filename}")
                moved_count += 1
            except Exception as e:
                print(f"  Failed to move {filename}: {e}")

        print(f"  Finished {target_dir}. Moved {moved_count} file(s).")

    except FileNotFoundError:
        print("Error: 'exiftool' not found. Please install it.")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred in {target_dir}: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 sort_dji.py <directory1> [directory2 ...]")
        sys.exit(1)

    for path in sys.argv[1:]:
        sort_dji_files(path)