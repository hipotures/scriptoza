#!/usr/bin/env bash
# Install the Noctalia (niri) plugins: rtorrent-status, agentai-status and agent-accounts.
# Usage: niri/install.sh [rtorrent-status] [agentai-status] [agent-accounts]   (default: all)
# Set NOCTALIA_BAR to target a bar other than "default".
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
plugins_dir="${XDG_DATA_HOME:-$HOME/.local/share}/scriptoza/noctalia-plugins"
source_name="scriptoza"
bar_name="${NOCTALIA_BAR:-default}"

if ! command -v noctalia >/dev/null 2>&1; then
    echo "noctalia is not installed." >&2
    exit 1
fi
if ! noctalia msg plugins list >/dev/null 2>&1; then
    echo "Noctalia is not running; start it in your niri session and run this installer again." >&2
    exit 1
fi

components=("$@")
if [[ ${#components[@]} -eq 0 ]]; then
    components=(rtorrent-status agentai-status agent-accounts)
fi

install_rtorrent_status() {
    local source_dir="$repo_dir/niri/rtorrent-status"
    local target_dir="$plugins_dir/rtorrent-status"
    rm -rf "$target_dir"
    install -d "$target_dir"
    install -m 644 "$source_dir"/plugin.toml "$source_dir"/*.luau "$source_dir"/rtorrent_rpc.py "$target_dir/"
}

install_agentai_status() {
    local source_dir="$repo_dir/niri/agentai-status"
    local worker_source="$repo_dir/gnome/agentai-status"
    local target_dir="$plugins_dir/agentai-status"
    rm -rf "$target_dir"
    install -d "$target_dir/worker/assets/icons"
    install -m 644 "$source_dir"/plugin.toml "$source_dir"/*.luau "$target_dir/"
    for filename in status-worker.js event-monitor.js event-stream.js collector.js model.js usage.js; do
        install -m 644 "$worker_source/$filename" "$target_dir/worker/$filename"
    done
    install -m 644 "$worker_source"/assets/icons/*.svg "$target_dir/worker/assets/icons/"
}

install_agent_accounts() {
    local source_dir="$repo_dir/niri/agent-accounts"
    local target_dir="$plugins_dir/agent-accounts"
    rm -rf "$target_dir"
    install -d "$target_dir"
    install -m 644 "$source_dir"/plugin.toml "$source_dir"/*.luau "$target_dir/"
}

for component in "${components[@]}"; do
    case "$component" in
        rtorrent-status) install_rtorrent_status ;;
        agentai-status) install_agentai_status ;;
        agent-accounts) install_agent_accounts ;;
        *)
            echo "Unknown component: $component (expected rtorrent-status, agentai-status or agent-accounts)" >&2
            exit 1
            ;;
    esac
done

registered="$(noctalia msg plugins source list | awk -v name="$source_name" '$1 == name {print $3}')"
if [[ -n "$registered" && "$registered" != "$plugins_dir" ]]; then
    noctalia msg plugins source remove "$source_name"
    registered=""
fi
if [[ -z "$registered" ]]; then
    noctalia msg plugins source add "$source_name" path "$plugins_dir"
fi

widgets=()
# Captured first: with pipefail, "list | grep -q" fails when grep closes the pipe early.
installed="$(noctalia msg plugins list)"
for component in "${components[@]}"; do
    # Reinstalling replaces the files, which hot reload does not always pick up; reload explicitly.
    if grep -q "^scriptoza/$component .* enabled" <<<"$installed"; then
        noctalia msg plugins disable "scriptoza/$component"
        sleep 1
    fi
    noctalia msg plugins enable "scriptoza/$component"
    widgets+=("scriptoza/$component:bar")
done

# Pin the widgets to the start of the bar's end section, as in the GNOME panel.
current="$(noctalia msg config-get "bar.$bar_name.end")"
updated="$(python3 -I - "$current" "${widgets[@]}" <<'EOF'
import ast
import json
import sys

current = ast.literal_eval(sys.argv[1].strip() or "[]")
order = ["scriptoza/rtorrent-status:bar", "scriptoza/agentai-status:bar", "scriptoza/agent-accounts:bar"]
wanted = set(sys.argv[2:]) | {item for item in current if item in order}
pinned = [item for item in order if item in wanted]
print(json.dumps(pinned + [item for item in current if item not in pinned]))
EOF
)"
noctalia msg config-set "bar.$bar_name.end" "$updated"

echo "Installed into $plugins_dir and added to bar '$bar_name': ${widgets[*]}"
