#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/rtorrent-status"
extension_id="rtorrent-status@scriptoza"
target_dir="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$extension_id"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/scriptoza"
config_file="$config_dir/rtorrent-status.json"

shell_version="$(gnome-shell --version)"
if [[ "$shell_version" != "GNOME Shell 50."* && "$shell_version" != "GNOME Shell 51."* ]]; then
    echo "rTorrent Status requires GNOME Shell 50 or 51." >&2
    exit 1
fi

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

gjs -c 'const settings = new imports.gi.Gio.Settings({schema_id: "org.gnome.shell"});
const enabled = settings.get_strv("enabled-extensions");
if (!enabled.includes("rtorrent-status@scriptoza"))
    settings.set_strv("enabled-extensions", [...enabled, "rtorrent-status@scriptoza"]);
imports.gi.Gio.Settings.sync();'

if gnome-extensions info "$extension_id" >/dev/null 2>&1; then
    gnome-extensions enable "$extension_id"
    gnome-extensions info "$extension_id"
    echo "Reload panel code through Looking Glass as described in gnome/README.md, or log out and log back in."
else
    echo "Installed and enabled for the next GNOME session. Log out and log back in to load the extension."
fi
