#!/bin/bash

# Scriptoza Installer - Wersja Precyzyjna
set -e

BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/scriptoza"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🚀 Instalacja wybranych skryptów..."

mkdir -p "$BIN_DIR"
mkdir -p "$CONFIG_DIR"

# Funkcja pomocnicza do bezpiecznego kopiowania
install_script() {
    local src="$1"
    local dest_name="$2"
    if [ -f "$src" ]; then
        cp -v "$src" "$BIN_DIR/$dest_name"
        chmod 755 "$BIN_DIR/$dest_name"
    else
        echo "⚠️ Nie znaleziono: $src"
    fi
}

# 1. Kopiowanie skryptów z nazwami o które prosiłeś
# Dodaję rename-video-by-tags i zostawiam rename-video jako skrót
install_script "$REPO_DIR/video/rename_video_by_tags.py" "rename-video-by-tags"
install_script "$REPO_DIR/video/rename_video_by_tags.py" "rename-video"
install_script "$REPO_DIR/video/check_4k.py"            "check-4k"
install_script "$REPO_DIR/video/sort_dji.py"            "sort-dji"
install_script "$REPO_DIR/photo/rename_photo.py"        "rename-photo"

# 2. Kopiowanie konfiguracji
cp -v "$REPO_DIR/video/rename_video.yaml" "$CONFIG_DIR/"

echo "✅ Instalacja zakończona."
echo "Skrypt 'by tags' jest dostępny jako: rename-video-by-tags"
