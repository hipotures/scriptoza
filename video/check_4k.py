#!/usr/bin/env python3
"""
Check video resolution and create 4K/non-4K file lists
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def get_video_info(file_path):
    """Get video codec, bitrate, and resolution using ffprobe"""
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_name,bit_rate,width,height',
                '-of', 'json',
                str(file_path)
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        stream = data.get('streams', [{}])[0]

        width = stream.get('width', 0)
        height = stream.get('height', 0)
        codec = stream.get('codec_name', 'unknown')
        bitrate = stream.get('bit_rate', '0')

        # Convert bitrate to Mbps
        try:
            bitrate_mbps = float(bitrate) / 1_000_000
        except (ValueError, TypeError):
            bitrate_mbps = 0.0

        return {
            'width': width,
            'height': height,
            'codec': codec,
            'bitrate': bitrate_mbps
        }
    except Exception as e:
        print(f"Error processing {file_path.name}: {e}", file=sys.stderr)
        return None


def is_4k(width, height):
    """Check if resolution is 4K (3840x2160 or 2160x3840)"""
    return (width == 3840 and height == 2160) or (width == 2160 and height == 3840)


def main():
    parser = argparse.ArgumentParser(
        description='Check video files and classify by resolution (4K vs non-4K)'
    )
    parser.add_argument(
        'directory',
        type=Path,
        help='Directory to scan recursively for MP4 files'
    )
    parser.add_argument(
        '--output-4k',
        type=Path,
        default=Path('files_4k.txt'),
        help='Output file for 4K file list (default: files_4k.txt)'
    )
    parser.add_argument(
        '--output-non4k',
        type=Path,
        default=Path('files_non4k.txt'),
        help='Output file for non-4K file list (default: files_non4k.txt)'
    )

    args = parser.parse_args()

    if not args.directory.exists():
        print(f"Error: Directory does not exist: {args.directory}", file=sys.stderr)
        sys.exit(1)

    if not args.directory.is_dir():
        print(f"Error: Not a directory: {args.directory}", file=sys.stderr)
        sys.exit(1)

    # Find all MP4 files
    print(f"Scanning {args.directory} for MP4 files...")
    mp4_files = sorted(args.directory.rglob("*.mp4"))

    if not mp4_files:
        print("No MP4 files found.")
        sys.exit(0)

    print(f"Found {len(mp4_files)} MP4 files. Analyzing...")
    print()

    files_4k = []
    files_non4k = []

    for idx, mp4 in enumerate(mp4_files, 1):
        info = get_video_info(mp4)

        if info is None:
            print(f"[{idx}/{len(mp4_files)}] SKIP  {mp4.name}")
            continue

        resolution = f"{info['width']}x{info['height']}"
        is4k = is_4k(info['width'], info['height'])
        marker = "4K   " if is4k else "NON4K"

        print(f"[{idx}/{len(mp4_files)}] {marker} {mp4.name}")
        print(f"           Resolution: {resolution}, Bitrate: {info['bitrate']:.1f}Mbps, Codec: {info['codec']}")

        file_entry = f"{mp4}\t{resolution}\t{info['bitrate']:.1f}Mbps\t{info['codec']}\n"

        if is4k:
            files_4k.append(file_entry)
        else:
            files_non4k.append(file_entry)

    # Write results
    print()
    print(f"Writing results...")

    with open(args.output_4k, 'w') as f:
        f.write(f"# 4K files ({len(files_4k)} total)\n")
        f.write("# Format: path\tresolution\tbitrate\tcodec\n")
        f.writelines(files_4k)

    with open(args.output_non4k, 'w') as f:
        f.write(f"# Non-4K files ({len(files_non4k)} total)\n")
        f.write("# Format: path\tresolution\tbitrate\tcodec\n")
        f.writelines(files_non4k)

    print(f"4K files:     {len(files_4k):4d} → {args.output_4k}")
    print(f"Non-4K files: {len(files_non4k):4d} → {args.output_non4k}")
    print()
    print("Done!")


if __name__ == '__main__':
    main()
