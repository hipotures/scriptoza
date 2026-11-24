#!/usr/bin/env bash
# Install the GNOME Shell extensions: rtorrent-status and agentai-status.
# Usage: gnome/install.sh [rtorrent-status] [agentai-status]   (default: both)
set -euo pipefail

gnome_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
extensions_dir="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/scriptoza"

shell_version="$(gnome-shell --version)"
if [[ "$shell_version" != "GNOME Shell 50."* && "$shell_version" != "GNOME Shell 51."* ]]; then
    echo "These extensions require GNOME Shell 50 or 51." >&2
    exit 1
fi

components=("$@")
if [[ ${#components[@]} -eq 0 ]]; then
    components=(rtorrent-status agentai-status)
fi

enable_extension() {
    local extension_id="$1"
    EXTENSION_ID="$extension_id" gjs -c 'const id = imports.gi.GLib.getenv("EXTENSION_ID");
const settings = new imports.gi.Gio.Settings({schema_id: "org.gnome.shell"});
const enabled = settings.get_strv("enabled-extensions");
if (!enabled.includes(id))
    settings.set_strv("enabled-extensions", [...enabled, id]);
imports.gi.Gio.Settings.sync();'
    if gnome-extensions info "$extension_id" >/dev/null 2>&1; then
        gnome-extensions enable "$extension_id"
        gnome-extensions info "$extension_id"
        echo "Reload panel code through Looking Glass as described in gnome/README.md, or log out and log back in."
    else
        echo "Installed and enabled $extension_id for the next GNOME session. Log out and log back in to load it."
    fi
}

install_rtorrent_status() {
    local source_dir="$gnome_dir/rtorrent-status"
    local extension_id="rtorrent-status@scriptoza"
    local target_dir="$extensions_dir/$extension_id"
    local config_file="$config_dir/rtorrent-status.json"

    install -d "$target_dir"
    for filename in metadata.json extension.js config.js model.js scgi.js reload.js stylesheet.css; do
        install -m 644 "$source_dir/$filename" "$target_dir/$filename"
    done

    if [[ ! -f "$config_file" ]]; then
        install -d "$config_dir"
        cat >"$config_file" <<'EOF'
{
  "name": "rtorrent",
  "host": "127.0.0.1",
  "port": 5000,
  "pollSeconds": 3,
  "density": "large",
  "sortBy": "state",
  "sortDir": "asc",
  "anonymize": false
}
EOF
        chmod 644 "$config_file"
        echo "Created default config at $config_file"
    fi
    enable_extension "$extension_id"
}

install_agentai_status() {
    local source_dir="$gnome_dir/agentai-status"
    local extension_id="codex-status@scriptoza"
    local target_dir="$extensions_dir/$extension_id"

    install -d "$target_dir/assets/icons"
    install -m 644 "$source_dir"/assets/icons/*.svg "$target_dir/assets/icons/"
    for filename in metadata.json extension.js density.js usage.js usage-format.js collector.js navigation.js model.js reload.js status-process.js status-worker.js event-stream.js event-monitor.js stylesheet.css; do
        install -m 644 "$source_dir/$filename" "$target_dir/$filename"
    done
    enable_extension "$extension_id"
}

for component in "${components[@]}"; do
    case "$component" in
        rtorrent-status) install_rtorrent_status ;;
        agentai-status) install_agentai_status ;;
        *)
            echo "Unknown component: $component (expected rtorrent-status or agentai-status)" >&2
            exit 1
            ;;
    esac
done
