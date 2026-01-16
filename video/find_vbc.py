#!/usr/bin/env python3
import os
import subprocess
import sys
import argparse

def find_vbc_files(directory, with_vbc=True, recursive=True):
    """
    Finds .mp4 and .mov files with or without VBC tags using exiftool.
    """
    if not os.path.isdir(directory):
        print(f"Error: {directory} is not a directory.")
        return

    # Base exiftool command
    # -p '$FilePath' prints the full absolute path
    # -q -q for quiet mode
    # -ext extension filter
    cmd = [
        'exiftool',
        '-q', '-q',
        '-p', '$FilePath',
        '-ext', 'mp4',
        '-ext', 'mov'
    ]

    if recursive:
        cmd.append('-r')

    # Condition: check if VBCEncoder tag is defined
    if with_vbc:
        condition = 'defined $VBCEncoder'
    else:
        condition = 'not defined $VBCEncoder'

    cmd.extend(['-if', condition, directory])

    try:
        # We use run and capture output
        # Note: exiftool returns 1 if no files match the condition, 
        # so we don't use check=True here.
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        output = result.stdout.strip()
        if output:
            print(output)
            
    except FileNotFoundError:
        print("Error: 'exiftool' not found. Please install it.")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find video files with or without VBC tags.")
    parser.add_argument("directory", help="Directory to scan")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--with-vbc", action="store_true", help="Find files that HAVE VBC tags")
    group.add_argument("--without-vbc", action="store_true", help="Find files that DO NOT have VBC tags")
    parser.add_argument("--no-recursive", action="store_false", dest="recursive", help="Do not scan subdirectories")
    
    args = parser.parse_args()

    find_vbc_files(args.directory, with_vbc=args.with_vbc, recursive=args.recursive)
