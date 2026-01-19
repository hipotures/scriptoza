#!/bin/bash

# Scriptoza Installer - Wersja KOPIUJĄCA
# Kopiuje skrypty i konfigurację do katalogów użytkownika.

set -e

BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/scriptoza"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🚀 Kopiowanie Scriptoza do systemu..."

# 1. Przygotowanie katalogów
mkdir -p "$BIN_DIR"
mkdir -p "$CONFIG_DIR"

# 2. Kopiowanie konfiguracji (.yaml)
echo "📂 Kopiowanie konfiguracji do $CONFIG_DIR..."
find "$REPO_DIR" -name "*.yaml" -not -path "*/.*" | while read -r config_file; do
    cp -v "$config_file" "$CONFIG_DIR/"
done

# 3. Kopiowanie skryptów (.py, .sh)
echo "📜 Kopiowanie skryptów do $BIN_DIR..."
find "$REPO_DIR/video" "$REPO_DIR/photo" "$REPO_DIR/utils" -maxdepth 1 \( -name "*.py" -o -name "*.sh" \) | while read -r script_file; do
    filename=$(basename "$script_file")
    
    # Kopiujemy plik i nadajemy uprawnienia wykonywania
    cp -v "$script_file" "$BIN_DIR/"
    chmod +x "$BIN_DIR/$filename"
done

echo ""
echo "✅ Gotowe! Skrypty zostały skopiowane do $BIN_DIR"
echo "Możesz je teraz wywoływać z dowolnego miejsca, np. wpisując: rename_video_by_tags.py"
echo "Upewnij się, że $BIN_DIR jest w Twoim PATH."