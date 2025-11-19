#!/usr/bin/env python3
import subprocess
import json
import os
import concurrent.futures
import threading
import math

MAX_THREADS = 4  # You can change to 8 or another number

# For each field, define possible EXIF tag names in order of preference
TAG_ALIASES = {
    'date':        ['CreateDate', 'MediaCreateDate', 'TrackCreateDate', 'DateTimeOriginal', 'FileModifyDate'],
    'width':       ['SourceImageWidth', 'ImageWidth', 'VideoWidth'],
    'height':      ['SourceImageHeight', 'ImageHeight', 'VideoHeight'],
    'fps':         ['VideoFrameRate', 'VideoAvgFrameRate', 'VideoMaxFrameRate', 'FrameRate'],
    'size_bytes':  ['MediaDataSize', 'FileSize'],
}


def get_exif_tag(data, keys):
    """Returns the value of the first existing tag from the keys list, or None."""
    for key in keys:
        if key in data:
            return data[key]
    return None


def rename_video_file(filename):
    try:
        result = subprocess.run(
            ['exiftool', '-json', filename],
            capture_output=True, text=True, check=True
        )
        exif_data = json.loads(result.stdout)[0]

        # Get original base name without extension, used when date is missing
        original_base = os.path.splitext(os.path.basename(filename))[0]

        # Date from EXIF
        raw_date = get_exif_tag(exif_data, TAG_ALIASES['date'])
        # If missing or zero, treat as missing
        if not raw_date or raw_date.startswith('0000'):
            date_part = original_base
        else:
            # Clean format: 2024:07:12 21:24:28+02:00 -> 20240712_212428
            date_part = raw_date.split('+')[0].replace(':', '').replace(' ', '_')

        # Resolution
        w = get_exif_tag(exif_data, TAG_ALIASES['width']) or 'unknown'
        h = get_exif_tag(exif_data, TAG_ALIASES['height']) or 'unknown'
        wh = f"{w}x{h}"

        # FPS
        raw_fps = get_exif_tag(exif_data, TAG_ALIASES['fps'])
        if raw_fps is not None:
            try:
                fps_int = str(int(round(float(raw_fps)))) + 'fps'
            except Exception:
                fps_int = f"{raw_fps}fps"
        else:
            fps_int = 'unknownfps'

        # Size (bytes)
        raw_size = get_exif_tag(exif_data, TAG_ALIASES['size_bytes'])
        if raw_size is None:
            size_str = 'unknown'
        else:
            # If it's a string like "21 GB", leave as-is, otherwise it's a number
            size_str = str(raw_size)

        # Build resulting name
        base = f"{date_part}_{wh}_{fps_int}_{size_str}"
        _, ext = os.path.splitext(filename)
        new_name = f"{base}{ext.lower()}"

        # Avoid name collisions
        if new_name != os.path.basename(filename):
            folder = os.path.dirname(filename) or '.'
            full_new = os.path.join(folder, new_name)
            idx = 1
            while os.path.exists(full_new):
                new_name_idx = f"{base}_{idx}{ext.lower()}"
                full_new = os.path.join(folder, new_name_idx)
                idx += 1
            os.rename(filename, full_new)
            print(f"Thread {threading.current_thread().name}: {filename} → {os.path.basename(full_new)}")
        else:
            print(f"Thread {threading.current_thread().name}: {filename} already matches pattern.")

    except FileNotFoundError:
        print("Error: exiftool not found. Install exiftool on your system.")
    except subprocess.CalledProcessError as e:
        print(f"Thread {threading.current_thread().name}: exiftool returned error for {filename}: {e}")
    except json.JSONDecodeError:
        print(f"Thread {threading.current_thread().name}: JSON parsing error for {filename}")


if __name__ == "__main__":
    folder = "."
    files = [os.path.join(folder, f) for f in os.listdir(folder)
             if f.lower().endswith(('.mp4', '.mov', '.avi'))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as exec:
        exec.map(rename_video_file, files)
    print("Finished renaming files.")
