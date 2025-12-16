#!/usr/bin/env python3
"""
Check for files with same basename but different extensions (.mp4, .flv)
"""

from pathlib import Path
from collections import defaultdict
import sys


def find_duplicate_stems(directory, extensions=['mp4', 'flv']):
    """Find files with same stem but different extensions in same directory"""

    # Group files by directory and stem
    # Structure: {directory: {stem: [file1, file2, ...]}}
    dir_files = defaultdict(lambda: defaultdict(list))

    for ext in extensions:
        for file in Path(directory).rglob(f"*.{ext}"):
            parent = file.parent
            stem = file.stem
            dir_files[parent][stem].append(file)

    # Find collisions (same stem, multiple extensions in same directory)
    collisions = []
    for parent, stems in dir_files.items():
        for stem, files in stems.items():
            if len(files) > 1:  # Collision detected
                collisions.append((parent, stem, files))

    return collisions


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_collisions.py <directory>")
        print("\nScans directory recursively for files with same basename but different extensions")
        print("Example: X.mp4 and X.flv in same directory")
        sys.exit(1)

    directory = Path(sys.argv[1])

    if not directory.exists():
        print(f"Error: Directory {directory} does not exist")
        sys.exit(1)

    print(f"Scanning {directory} for basename collisions (.mp4, .flv)...")
    print()

    collisions = find_duplicate_stems(directory)

    if not collisions:
        print("✓ No collisions found!")
        print("  All basenames are unique within each directory.")
    else:
        print(f"⚠ Found {len(collisions)} collision(s):\n")
        for parent, stem, files in sorted(collisions):
            rel_path = parent.relative_to(directory) if parent != directory else Path('.')
            print(f"Directory: {rel_path}")
            print(f"Basename: {stem}")
            for f in sorted(files):
                size = f.stat().st_size
                size_mb = size / (1024 * 1024)
                print(f"  - {f.name:60s} {size_mb:8.1f} MB")
            print()

        print(f"Total: {len(collisions)} collision(s) found")
        print("\nThese files would cause naming conflicts during compression:")
        print("  X.mp4 → output/X.mp4")
        print("  X.flv → output/X.mp4  ← COLLISION!")
