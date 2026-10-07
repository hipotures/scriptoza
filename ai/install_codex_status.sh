#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/codex-status"
extension_id="codex-status@scriptoza"
target_dir="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$extension_id"
shell_version="$(gnome-shell --version)"
if [[ "$shell_version" != "GNOME Shell 50."* ]]; then
    echo "Codex Status requires GNOME Shell 50." >&2
    exit 1
fi

install -d "$target_dir"
for filename in metadata.json extension.js collector.js navigation.js model.js reload.js stylesheet.css; do
    install -m 644 "$source_dir/$filename" "$target_dir/$filename"
done

gjs -c 'const settings = new imports.gi.Gio.Settings({schema_id: "org.gnome.shell"});
const enabled = settings.get_strv("enabled-extensions");
if (!enabled.includes("codex-status@scriptoza"))
    settings.set_strv("enabled-extensions", [...enabled, "codex-status@scriptoza"]);
imports.gi.Gio.Settings.sync();'

if gnome-extensions info "$extension_id" >/dev/null 2>&1; then
    gnome-extensions enable "$extension_id"
    gnome-extensions info "$extension_id"
    echo "Reload panel code through Looking Glass as described in ai/README.md, or log out and log back in."
else
    echo "Installed and enabled for the next GNOME session. Log out and log back in to load the extension."
fi
