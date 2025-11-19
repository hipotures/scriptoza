#!/bin/bash

# Make sure you are in the directory with files
for file in Screen_Recording_*.mp4; do
  # Check if file exists (for safety)
  [[ -e "$file" ]] || continue

  # Extract date from filename: Screen_Recording_YYYYMMDD_HHMMSS.mp4
  date_part=$(echo "$file" | grep -oP 'Screen_Recording_\K\d{8}')

  if [[ -n "$date_part" ]]; then
    # Create directory structure: SR/YYYYMMDD/
    mkdir -p "SR/$date_part"

    # Move file to appropriate directory
    mv "$file" "SR/$date_part/"
  fi
done
