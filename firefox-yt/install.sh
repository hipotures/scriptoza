#!/usr/bin/env bash

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
HOST_PATH="$SCRIPT_DIR/native/yt_downloader.py"
TEMPLATE_PATH="$SCRIPT_DIR/native/yt_downloader.json"
HOME_DIR="$(getent passwd "$(id -u)" | awk -F: '{print $6}')"
if [ -z "$HOME_DIR" ]; then
    HOME_DIR="${HOME:?Unable to determine the current user home directory}"
fi

HOST_DIR="$HOME_DIR/.mozilla/native-messaging-hosts"
HOST_MANIFEST="$HOST_DIR/yt_downloader.json"
CONFIG_DIR="$HOME_DIR/.config/firefox-yt-downloader"
CONFIG_PATH="$CONFIG_DIR/config"

chmod +x "$HOST_PATH"
mkdir -p "$CONFIG_DIR"
if [ ! -e "$CONFIG_PATH" ]; then
    printf '%s\n' 'DOWNLOAD_DIR=/home/USER/Videos/downloaded' > "$CONFIG_PATH"
fi
mkdir -p "$HOST_DIR"
ESCAPED_HOST_PATH="$(printf '%s' "$HOST_PATH" | sed 's/[&|]/\\&/g')"
sed "s|__YT_DOWNLOADER_PATH__|$ESCAPED_HOST_PATH|g" "$TEMPLATE_PATH" > "$HOST_MANIFEST"

printf '%s\n' "Native messaging host installed at: $HOST_MANIFEST"
printf '%s\n' "Edit DOWNLOAD_DIR in: $CONFIG_PATH"
printf '%s\n' ""
printf '%s\n' "To load the extension temporarily in Firefox:"
printf '%s\n' "1. Open about:debugging#/runtime/this-firefox"
printf '%s\n' "2. Click Load Temporary Add-on..."
printf '%s\n' "3. Select this manifest: $SCRIPT_DIR/extension/manifest.json"
