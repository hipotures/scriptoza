# GNOME Extensions

Install both extensions with `bash gnome/install.sh`, or pass `rtorrent-status` or `agentai-status` to install one.

## rTorrent Status

`rtorrent-status/` is a GNOME Shell 50/51 extension written in JavaScript/GJS. It monitors a local or remote `rtorrent` instance over SCGI JSON-RPC and displays torrent states in the top panel using the same dot-and-menu layout as `agentai-status/`.

### Requirements

- GNOME Shell 50 or 51
- `rtorrent` with SCGI RPC enabled:
  - Modern `rtorrent` (0.9.7+ / 0.16.x) in `~/.config/rtorrent/rtorrent.rc`:
    ```ini
    network.rpc.use_xmlrpc.set = true
    network.rpc.use_jsonrpc.set = true
    network.scgi.open_port = "127.0.0.1:5000"
    ```
  - Legacy `rtorrent` (0.8.x, e.g. older Ubuntu) in `~/.rtorrent.rc`:
    ```ini
    scgi_port = 127.0.0.1:5000
    ```
  The widget automatically detects JSON-RPC, XML-RPC `d.multicall2`, and legacy XML-RPC `d.multicall`.

### Configuration

The widget reads `~/.config/scriptoza/rtorrent-status.json` (or `$XDG_CONFIG_HOME/scriptoza/rtorrent-status.json`) on each poll:

```json
{
  "name": "rtorrent",
  "host": "127.0.0.1",
  "port": 5000,
  "servers": [
    { "host": "127.0.0.1", "port": 5000 }
  ],
  "activeServer": 0,
  "pollSeconds": 3,
  "density": "large",
  "sortBy": "state",
  "sortDir": "asc",
  "anonymize": false
}
```

Change `name`, `servers`, `activeServer`, `pollSeconds`, `density`, `sortBy` (`state`, `added`, `name`, `progress`, `size`, `down`, `up`, `eta`), `sortDir` (`asc`, `desc`), or `anonymize` (`true`/`false`) in the config file. Server list (add/edit/switch/remove), size, sort, and anonymize can also be changed live from the settings panel opened by the gear icon in the footer. Changes take effect automatically on the next poll.

### Installation

```bash
bash gnome/install.sh rtorrent-status
```

Log out and log back in after installing for the first time. For an already loaded widget, update the installed files and reload the panel module in Looking Glass (`Alt+F2` -> `lg`):

```javascript
await (await import('file:///home/user/.local/share/gnome-shell/extensions/rtorrent-status@scriptoza/reload.js')).reload()
```

### Panel & Menu

The panel indicator is pinned on the far left of the right panel box (before `codex-status` and other tray icons) using uniform Cairo-drawn circles:

- One solid colored dot per active (non-paused) torrent.
- When all torrents are paused, a single gray ring with a center dot.
- When the queue is empty, an empty gray ring; when the server is unreachable, a blinking yellow ring.

Hovering over the panel indicator shows a tooltip with the configured `name`. Clicking opens the torrent list; hovering over a row for 600 ms displays peers (seeders/leechers), current transfer rates, total uploaded bytes, and ratio.

| State | Color | Meaning |
| --- | --- | --- |
| `error` | Blinking red | Non-tracker `d.message` (storage or hash error) |
| `hashing` | Yellow | Checking file hashes (`d.hashing > 0`) |
| `downloading` | Blue | Active incomplete torrent |
| `seeding` | Green | Active completed torrent |
| `paused` | Gray | Inactive / paused torrent |

The footer displays total download and upload rates, the last update timestamp, the widget version, and a gear icon (`⚙`) that toggles the inline settings panel (Server, Size, Sort, and Anonymize).

## Herdr Agent Status

For the GPU live-handoff failure and recovery of a running Codex conversation
inside a new Herdr pane, see the
[incident record](../docs/HERDR_GPU_HANDOFF_INCIDENT.md).

`agentai-status/` is a GNOME Shell 50/51 extension written in JavaScript/GJS. It
shows Codex, Claude Code, and Antigravity (`agy`) agents locally and on every enabled saved Herdr machine.
It subscribes to agent changes directly from Herdr and runs independently of
`codex-resume`; status monitoring never sends input, marks completions as seen, or
controls services.
It requires `herdr`, `gjs`, OpenSSH, and GNU coreutils `timeout` in the user's executable paths.
Remote push monitoring supports Linux and macOS Herdr servers with managed SSH
connections and cached executable metadata from a successful Herdr connection.

Install and enable it for your user:

```bash
bash gnome/install.sh agentai-status
```

Log out and log back in after installing or updating it. GNOME Shell 50/51 loads
extension code at session startup and does not support reloading it through
the old `ReloadExtension` D-Bus method. Existing enabled extensions are preserved.
The installer copies only this widget's files into
`~/.local/share/gnome-shell/extensions/codex-status@scriptoza/` (or under
`XDG_DATA_HOME` when set).

For an already loaded widget, panel code can be updated without logging out:
install the updated files, press Alt+F2, enter `lg`, then paste this into the
Looking Glass evaluator (adjust the home directory or `XDG_DATA_HOME` if needed):

```javascript
await (await import('file:///home/user/.local/share/gnome-shell/extensions/codex-status@scriptoza/reload.js')).reload()
```

This reloads the panel module while retaining GNOME's extension registration.
Stylesheet changes require a new session.
The source directory is `agentai-status`; the installed extension ID remains
`codex-status@scriptoza`, so the existing registration and enable/disable commands
continue to identify this widget.

The panel shows one colored Cairo-drawn dot per non-idle agent, with no icon or counters,
pinned directly after `rtorrent-status` on the left side of the right panel box.
Agents sharing a state have separate dots. Idle agents are hidden from the panel
while any other state is present. If all agents are idle, the panel shows a single
gray ring with a center dot so the full list remains accessible without taking extra space;
when no agents are connected, it shows an empty gray ring.
Hovering over the panel indicator shows a `"herdr"` tooltip.
Click it to see the complete list, including idle agents, with each agent's
workspace and agent type, such as **homestack · Codex**. Remote workspaces
include the machine name, such as **gpu/research · Claude Code**. A smaller
second line shows the automatic terminal session title when available; a title
that only repeats the workspace is hidden. A trailing ` | workspace` is removed
from session titles. Hover over a row (for 600 ms) to see its full machine/workspace/tab/pane
location. Names are automatic and require no manual pane renaming. The top of the menu shows one
line per agent type that has usage data: its icon, then the remaining percentage and time
to reset of the 5-hour and weekly windows, such as `5h 99% · 3h12m  wk 36% · 2d`. A
separator sits above the rows as well as above the footer.
Each row contains a type icon, a workspace name colored by its status, and a matching
status icon on the right (its label is the accessible name), without a duplicate dot.
SVG files in `agentai-status/assets/icons/` identify Codex, Claude Code, and Antigravity.
Screen readers announce the agent type, name, and status.
The OpenAI icon switches between the supplied light and dark variants when the
GNOME menu's text color changes, including live theme changes. Herdr's theme
controls its terminal interface independently of the GNOME menu.
Agent rows support keyboard and pointer input: hovering or focusing a row
highlights the complete row,
and activating it checks the selected machine and pane with Herdr before
focusing that pane in the existing Herdr client. The extension then activates
the matching terminal window by its unique `[herdr-client:<ID>]` title marker.
It switches to that window's existing GNOME workspace without moving the
window. A missing or ambiguous client window, an unavailable client, or a
failed focus is reported as a notification and leaves the status list
unchanged. Navigation requires the Herdr snapshot to include its server boot
identity, so upgrade and restart the Herdr server and client before using row
activation. Older snapshots remain available for status polling, but their
rows report a navigation error until a boot identity is available.

| Herdr state | Appearance | Meaning |
| --- | --- | --- |
| `blocked` | Blinking red | Waiting for an answer or approval |
| `working` | Steady blue | Working |
| `done` | Green | Completed; Herdr has not marked the result as seen |
| `unknown` | Yellow | Herdr cannot classify the agent's state |
| `idle` | Gray | Ready for another instruction |

The table order is also the menu's state priority; disconnected entries, when
present, precede idle entries. Status priority in the panel's accessible summary
still places unseen completions before working agents. `done` means the turn
finished, not necessarily that the task succeeded. Reading status does not
change `done` to `idle`.

Within `done` and `idle`, agents most recently observed working or changing
state appear first. Other groups keep alphabetical order, so working agents
do not move as their activity continues. Equal or unknown activity times use
alphabetical order. The helper remembers activity across its existing polls
and uses Herdr's state-change sequence to notice work between polls; reading
a completion does not update its activity time. History starts when the widget
is enabled or reloaded, since Herdr supplies sequences rather than timestamps
comparable across machines. Observed times follow the arrival of authoritative state updates.

Status updates are event-driven. The worker keeps one `events.subscribe`
connection per server, listening for pane lifecycle, agent state, session title,
and workspace/tab name changes. Events are coalesced for 100 ms, then trigger
one authoritative `session.snapshot` read on the affected machine. Other machines
are not queried. A read already in flight is followed by another read if an event
arrives during it. Events invalidate cached state rather than replaying possibly
stale payloads over snapshots. Opening the menu does not issue extra requests.

Subscriptions are acknowledged before a reconciliation snapshot; changing the
pane inventory rebuilds subscriptions so newly started agents are included.
A closed connection or `events_lost` discards that machine's displayed agents,
reconnects, subscribes, and reconciles again. There is no periodic agent-status
polling. The enabled saved-machine list is checked at startup and every 60 seconds.
Remote profiles are reconciled independently, so one slow host cannot delay
updates from another host.

Local events use `herdr remote-api-bridge`. Remote events use a persistent SSH
channel to the saved machine's session and cached Herdr executable. The worker
reuses Herdr's managed OpenSSH control socket, with strict host-key checking,
noninteractive authentication, and SSH keepalives. It never installs or restarts
Herdr. Missing/unsupported remote metadata or failed subscriptions make that
machine unavailable; there is no polling fallback. Remote snapshot reads use the same managed control socket directly and an
8-second timeout. Both snapshots and subscriptions set `ProxyCommand=/bin/false`:
only an existing Herdr SSH master can carry requests. If it is missing or closes,
requests fail locally without a network connection or hardware-key authentication.
The widget never establishes a new SSH transport; connect in Herdr first. Event subscription setup has
a 10-second deadline; an established event stream has no idle timeout.

If the local server is unavailable, machine discovery and all remote subscriptions
stop. The panel shows a slowly pulsing yellow hollow circle and the menu says
“Waiting for the Herdr server to start”. Local recovery is retried every 3 seconds.
Unavailable remote machines are omitted and retried after 60 seconds; their
failure does not block live updates from connected machines. Discovery failures
remain visible in the menu.

The helper performs discovery, SSH setup, snapshot parsing, event handling, and
activity tracking outside GNOME Shell. Shell receives normalized updates over a
persistent pipe. Pending writes coalesce to the latest state if Shell is slow.
Disabling the widget cancels reads, timers, and active command/SSH process groups.
EOF on the parent's pipe also stops the helper. A failed helper is reported
without repeated respawning; reload the widget to retry.

Unchanged snapshots retain the panel dots and interactive menu rows; only the
footer is updated. Changed identities, server boots, states, names, titles, or
errors rebuild the display so navigation uses the current target.

In an isolated GNOME Shell 51 test, unchanged updates with 32 and 64 agent rows
took approximately 0.05 and 0.07 ms after the initial render. Rebuilding those
rows took approximately 17 and 50 ms. These timings use generated snapshots;
they do not measure SSH latency or the user's desktop.

The menu footer shows the last successful snapshot update time in local time,
using a 24-hour clock without a date, and the widget version:
`Last update: 00:43:55 · v0.0.32`. Machine discovery and connection-error
notifications preserve the last successful update time. Refresh latency and JSON
parsing metrics are not displayed in the menu.

The menu density has three levels: large (default), medium and compact. They change the
list width, font sizes and row spacing. Click the gear at the right of the
footer to cycle through them; the choice is saved in `~/.config/ai-agent-status/config.json` (`XDG_CONFIG_HOME` is honored) as
`{"density": "large"}`. A missing, broken or unknown value falls back to large. The file is created on the
first click, not by the installer.

Usage limits are read locally by the status worker once a minute and add no network
requests. Claude Code data comes from `$XDG_RUNTIME_DIR/claude-statusline-input.json`, which
`~/.claude/statusline.sh` writes from the status line JSON (`rate_limits`). Codex data comes from the last
`rate_limits` event in the newest `~/.codex/sessions/*/*/*/rollout-*.jsonl`; windows are classified by
`window_minutes`. Both files change only while the agent is running, so a window whose reset time has
passed is hidden until fresh data arrives. Percentages are the amount remaining.

Run the standalone
GJS snapshot-collection benchmark for three rounds and their mean:

```bash
gjs -m gnome/codex_status_benchmark.js
```

On the development machine, six agents across local and remote servers required
approximately 45 KB of JSON per round. The first round took 4.18 seconds and
eight requests, including an unreachable SSH machine. The next two rounds
skipped that machine and took 323 and 328 ms (326 ms mean), with seven requests
each. JSON parsing averaged 0.63 ms in those rounds, approximately 0.2% of their
latency. The standalone three-round benchmark and its child processes used 0.49
seconds of CPU over 24.92 seconds and peaked at 32 MB RSS. These are measurements
of this machine/network, not guaranteed timings or GNOME Shell memory overhead.

Offline collector/model tests run with the repository's unittest suite when
`gjs` is installed. Rendering, blinking, and cleanup can also be verified in an
isolated headless GNOME Shell:

```bash
gnome-extensions pack gnome/agentai-status --extra-source=collector.js --extra-source=navigation.js --extra-source=density.js --extra-source=usage.js --extra-source=usage-format.js --extra-source=model.js --extra-source=reload.js --extra-source=status-process.js --extra-source=status-worker.js --extra-source=event-stream.js --extra-source=event-monitor.js --extra-source=assets --out-dir=/tmp --force
dbus-run-session -- gnome-shell-test-tool --extra-filter org.scriptoza.CodexStatusWindowTest --headless --extension /tmp/codex-status@scriptoza.shell-extension.zip gnome/codex_status_shell_test.js
```

The headless test launches a temporary GTK window pair to verify exact Herdr
window selection and workspace activation. The extra filter allows that test
application's window class; it is not needed by the installed extension. A
headless compositor has no focused client seat, so the test verifies that
`Main.activateWindow()` receives the uniquely matched window, switches to its
workspace, and leaves both windows in place. Observe the final compositor
focus in a non-headless GNOME session.
