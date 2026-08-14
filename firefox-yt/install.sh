#!/usr/bin/env bash

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
HOST_PATH="$SCRIPT_DIR/native/yt_downloader.py"
TEMPLATE_PATH="$SCRIPT_DIR/native/yt_downloader.json"
CONFIG_PATH="$SCRIPT_DIR/native/yt_downloader.conf"
CONFIG_TEMPLATE_PATH="$SCRIPT_DIR/native/yt_downloader.conf.example"
HOME_DIR="$(getent passwd "$(id -u)" | awk -F: '{print $6}')"
if [ -z "$HOME_DIR" ]; then
    HOME_DIR="${HOME:?Unable to determine the current user home directory}"
fi

HOST_DIR="$HOME_DIR/.mozilla/native-messaging-hosts"
HOST_MANIFEST="$HOST_DIR/yt_downloader.json"

chmod +x "$HOST_PATH"
if [ ! -e "$CONFIG_PATH" ]; then
    cp "$CONFIG_TEMPLATE_PATH" "$CONFIG_PATH"
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
