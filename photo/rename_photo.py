#!/usr/bin/env python3

import subprocess
import json
import os
import concurrent.futures
import threading

MAX_THREADS = 24  # You can change to 8 or another number

def rename_photo_file(filename):
    try:
        result = subprocess.run(['exiftool', '-json', filename], capture_output=True, text=True, check=True)
        exif_data = json.loads(result.stdout)[0]

        # Try to get date with subseconds first, fallback to CreateDate
        subsec_create_date = exif_data.get('SubSecCreateDate') or exif_data.get('SubSecDateTimeOriginal')

        if subsec_create_date:
            # Format: "2025:01:04 17:34:58.625+01:00" -> "20250104_173458_625"
            subsec_create_date = subsec_create_date.split('+')[0]  # Remove timezone
            parts = subsec_create_date.split(' ')
            date_part = parts[0].replace(':', '')
            time_part = parts[1].split('.')
            time_without_ms = time_part[0].replace(':', '')
            milliseconds = time_part[1].ljust(3, '0') if len(time_part) > 1 else '000'
        elif 'CreateDate' in exif_data:
            # Fallback: use CreateDate without milliseconds
            create_date = exif_data['CreateDate']
            create_date = create_date.split('+')[0].replace(':', '').replace(' ', '_')
            date_part = create_date[:8]
            time_without_ms = create_date[9:] if len(create_date) > 8 else '000000'
            milliseconds = '000'
        else:
            print(f"Thread {threading.current_thread().name}: No CreateDate tag in file: {filename}")
            return

        filesize = os.path.getsize(filename)

        base_name = f"{date_part}_{time_without_ms}_{milliseconds}"
        _, extension = os.path.splitext(filename)
        new_name_with_extension = f"{base_name}{extension.lower()}"

        if new_name_with_extension != filename:
            folder = os.path.dirname(filename)
            if not folder:
                folder = "."
            full_new_name = os.path.join(folder, new_name_with_extension)

            counter = 1
            while os.path.exists(full_new_name):
                new_name_with_counter = f"{base_name}_{counter}{extension.lower()}"
                full_new_name = os.path.join(folder, new_name_with_counter)
                counter += 1

            os.rename(filename, full_new_name)
            print(f"Thread {threading.current_thread().name}: Renamed: {filename} -> {os.path.basename(full_new_name)}")
        else:
            print(f"Thread {threading.current_thread().name}: File name {filename} already matches pattern.")

    except FileNotFoundError:
        print("Error: exiftool not found. Make sure it's installed.")
    except subprocess.CalledProcessError as e:
        print(f"Thread {threading.current_thread().name}: Error executing exiftool for {filename}: {e}")
    except json.JSONDecodeError:
        print(f"Thread {threading.current_thread().name}: JSON parsing error for file: {filename}")
    except KeyError as e:
        print(f"Thread {threading.current_thread().name}: Missing required EXIF tag in file {filename}: {e}")

if __name__ == "__main__":
    folder = "."  # Current folder
    files = [os.path.join(folder, file) for file in os.listdir(folder)
             if file.lower().endswith(('.arw', '.jpg', '.jpeg'))]

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        executor.map(rename_photo_file, files)

    print("Finished renaming files.")
