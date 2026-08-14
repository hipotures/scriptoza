#!/usr/bin/env bash

set -eu

HOME_DIR="$(getent passwd "$(id -u)" | awk -F: '{print $6}')"
if [ -z "$HOME_DIR" ]; then
    HOME_DIR="${HOME:?Unable to determine the current user home directory}"
fi

HOST_MANIFEST="$HOME_DIR/.mozilla/native-messaging-hosts/yt_downloader.json"
rm -f "$HOST_MANIFEST"
printf '%s\n' "Removed native messaging host manifest: $HOST_MANIFEST"
