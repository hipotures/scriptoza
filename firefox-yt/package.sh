#!/usr/bin/env bash

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
OUTPUT_PATH="${1:-$SCRIPT_DIR/firefox-yt.xpi}"
case "$OUTPUT_PATH" in
    /*) ;;
    *) OUTPUT_PATH="$PWD/$OUTPUT_PATH" ;;
esac

if ! command -v zip >/dev/null 2>&1; then
    printf '%s\n' "zip is required to create the XPI package" >&2
    exit 1
fi

(cd "$SCRIPT_DIR/extension" && zip -q -j "$OUTPUT_PATH" manifest.json background.js)
printf '%s\n' "Created extension package: $OUTPUT_PATH"
