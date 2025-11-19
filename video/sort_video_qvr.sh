#!/bin/bash

# Make sure you are in the directory with files
for file in QVR_*.mp4; do
  # Check if file exists (for safety)
  [[ -e "$file" ]] || continue

  # Extract date from filename: QVR_YYYYMMDD_HHMMSS.mp4
  date_part=$(echo "$file" | grep -oP 'QVR_\K\d{8}')

  if [[ -n "$date_part" ]]; then
    # Create directory structure: QVR/YYYYMMDD/
    mkdir -p "QVR/$date_part"

    # Move file to appropriate directory
    mv "$file" "QVR/$date_part/"
  fi
done
