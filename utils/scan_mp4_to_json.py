#!/usr/bin/env python3
"""
Scan directory for MP4 files and export to JSON.

Usage:
    python scan_mp4_to_json.py /path/to/videos output.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict


def scan_directory(root_dir: Path) -> List[Dict]:
    """
    Recursively scan directory for .mp4 files.

    Returns list of dicts with: path, filename, size_bytes
    """
    files = []

    for file_path in root_dir.rglob("*.mp4"):
        if not file_path.is_file():
            continue

        try:
            size = file_path.stat().st_size

            files.append({
                "path": str(file_path.absolute()),
                "filename": file_path.name,
                "size_bytes": size
            })
        except (OSError, PermissionError) as e:
            print(f"Warning: Cannot access {file_path}: {e}", file=sys.stderr)
            continue

    return files


def main():
    if len(sys.argv) != 3:
        print("Usage: python scan_mp4_to_json.py <input_dir> <output_json>")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    output_file = Path(sys.argv[2])

    if not input_dir.exists():
        print(f"Error: Directory {input_dir} does not exist.")
        sys.exit(1)

    if not input_dir.is_dir():
        print(f"Error: {input_dir} is not a directory.")
        sys.exit(1)

    # Scan
    print(f"Scanning {input_dir} for .mp4 files...")
    start_time = datetime.now()

    files = scan_directory(input_dir)

    scan_duration = (datetime.now() - start_time).total_seconds()

    # Calculate totals
    total_count = len(files)
    total_size = sum(f["size_bytes"] for f in files)

    # Build output
    output = {
        "scan_metadata": {
            "input_directory": str(input_dir.absolute()),
            "scan_time": datetime.now().isoformat(),
            "scan_duration_seconds": round(scan_duration, 2),
            "total_files": total_count,
            "total_size_bytes": total_size
        },
        "files": files
    }

    # Write JSON
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"✓ Found {total_count} .mp4 files")
    print(f"✓ Total size: {total_size / (1024**3):.2f} GB")
    print(f"✓ Scan duration: {scan_duration:.2f}s")
    print(f"✓ Output saved to: {output_file}")


if __name__ == "__main__":
    main()
