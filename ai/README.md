# AI Utilities

## GNOME Herdr Agent Status

For the GPU live-handoff failure and recovery of a running Codex conversation
inside a new Herdr pane, see the
[incident record](../docs/HERDR_GPU_HANDOFF_INCIDENT.md).

`agentai-status/` is a GNOME Shell 50/51 extension written in JavaScript/GJS. It
shows Codex and Claude Code agents locally and on every enabled saved Herdr machine.
It subscribes to agent changes directly from Herdr and runs independently of
`codex-resume`; status monitoring never sends input, marks completions as seen, or
controls services.
It requires `herdr`, `gjs`, OpenSSH, and GNU coreutils `timeout` in the user's executable paths.
Remote push monitoring supports Linux and macOS Herdr servers with managed SSH
connections and cached executable metadata from a successful Herdr connection.

Install and enable it for your user:

```bash
bash ai/install_codex_status.sh
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

The panel shows one colored dot per non-idle agent, with no icon or counters.
Agents sharing a state have separate dots. Idle agents are hidden from the panel
while any other state is present. If all agents are idle, every idle agent has
its own gray dot so the full list remains accessible.
Click it to see the complete list, including idle agents, with each agent's
workspace and agent type, such as **homestack · Codex**. Remote workspaces
include the machine name, such as **gpu/research · Claude Code**. A smaller
second line shows the automatic terminal session title when available; a title
that only repeats the workspace is hidden. A trailing ` | workspace` is removed
from session titles. Hover over a row to see its full machine/workspace/tab/pane
location. Names are automatic and require no manual pane renaming. The heading displays "N local agents,
M remote agents", with a separator above the rows as well as above the footer.
Counts use machine identities and include idle agents and both supported types.
Each row contains a type icon, a workspace name colored by its status, and a matching
text status on the right, without a duplicate dot.
SVG files in `agentai-status/assets/icons/` identify Codex and Claude Code.
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
machine unavailable; there is no polling fallback. Snapshot reads use the existing
`herdr --machine` CLI path and an 8-second timeout. Event subscription setup has
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

The menu footer shows the update time, total snapshot refresh latency, time spent
parsing snapshots in the helper, and the widget version (currently `v0.0.12`).
The total latency includes waiting for the refreshed server's reply; it is not a
measure of time spent blocking GNOME Shell. Run the standalone
GJS snapshot-collection benchmark for three rounds and their mean:

```bash
gjs -m ai/codex_status_benchmark.js
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
gnome-extensions pack ai/agentai-status --extra-source=collector.js --extra-source=navigation.js --extra-source=model.js --extra-source=reload.js --extra-source=status-process.js --extra-source=status-worker.js --extra-source=event-stream.js --extra-source=event-monitor.js --extra-source=assets --out-dir=/tmp --force
dbus-run-session -- gnome-shell-test-tool --extra-filter org.scriptoza.CodexStatusWindowTest --headless --extension /tmp/codex-status@scriptoza.shell-extension.zip ai/codex_status_shell_test.js
```

The headless test launches a temporary GTK window pair to verify exact Herdr
window selection and workspace activation. The extra filter allows that test
application's window class; it is not needed by the installed extension. A
headless compositor has no focused client seat, so the test verifies that
`Main.activateWindow()` receives the uniquely matched window, switches to its
workspace, and leaves both windows in place. Observe the final compositor
focus in a non-headless GNOME session.

## Codex Resume

`codex_resume.py` monitors Codex panes and responds to two visible states:

- a capacity error, followed by the configured message and Enter;
- the complete “Giving this request a little extra thought” menu, dismissed by
  pressing “Dismiss and keep waiting” without Enter while preserving the current
  model (option `1` in the two-option menu or `2` when a faster-model retry is offered).

The runtime uses Python's standard library and the `herdr` executable in
`PATH`. It connects to the current user's Herdr server and every enabled saved
machine through `herdr --machine`, so it can run from any terminal or as a systemd
user service. Remote Herdr servers must already be running and accessible through
the user's configured SSH authentication.

Install the command and the optional user service from the repository root:

```bash
python3 utils/install.py
```

The installer copies `codex-resume` to `~/.local/bin` and the service unit to
`~/.config/systemd/user/codex-resume.service`. It does not enable or start the
service automatically.

Run a monitor manually with the default message or with an additional named pane:

```bash
codex-resume resume
codex-resume resume --panes codex-gpu --message Kontynuuj
```

Automatic discovery includes every live pane whose agent record has
`agent == "codex"`, both locally and on every enabled saved Herdr machine.
Machine profiles are refreshed on each poll. Use `--panes` or `--tabs` for
additional comma-separated pane/tab labels or IDs, resolved on each server.
An explicit selector that is not present yet is kept pending
and retried on later polls; this also lets a selector survive a pane closing
and reopening. Panes that are not recognized as agents can be
selected explicitly. Exact IDs take precedence over labels; labels include all
matching panes or tabs, and overlapping selections are deduplicated by machine
and pane ID. Remote reads and input always use the same machine profile as
discovery; matching pane IDs on different machines remain independent.

Each scan first queries the local Herdr server. If it is unavailable, the monitor
skips all discovery, remote SSH connections, pane reads, and input until the next
scan, including on startup. With a working local server, remote discovery runs
concurrently. An unreachable remote server does not stop monitoring the others.
Its previous detection state is retained without reading
or sending input until discovery succeeds again. Failures and recoveries are
logged, and `list` reports current discovery errors alongside watched panes.

The monitor waits sixty seconds after each completed scan by default. Scan time
adds to that interval. It runs independently of the GNOME widget, so their
Herdr requests can overlap. Each monitor scan reads four inventories per enabled
server and then reads each watched pane; the widget reads one snapshot per server.

The monitor keeps a single-process lock, so a second monitor exits instead of
watching the same runtime concurrently. Stop a manually started monitor before
starting the systemd service.

The `list` command prints the current runtime watch snapshot held by the active
monitor. It is not a fresh Herdr candidate scan.

`codex-resume logs` shows the last 50 service log entries and follows new ones.
Press Ctrl+C to exit the log view; the service continues running.

Useful options:

```text
--once             Check the selected panes once and exit
--dry-run          Log actions without sending input
--interval 5       Wait five seconds between completed scans and the next scan
--message TEXT     Submit TEXT for a capacity error (default: Resume)
```

Only visible terminal text is inspected, so manually scrolling can hide a
relevant error or continuation. A matching continuation below the latest
capacity error suppresses duplicate submission. A failed input submission is fatal because a
timeout can still mean that input was delivered. The monitor exits with status
`2` for this uncertain-delivery case; the service deliberately does not restart
after status `2`. Inspect the logs before restarting it manually.

### Start at login

After installing, enable and start the user service:

```bash
systemctl --user daemon-reload
systemctl --user enable --now codex-resume.service
```

The shipped unit runs `codex-resume resume` with the default `Resume` message.
It has no dependency on a separate Herdr systemd unit and retries ordinary
startup failures after five seconds. The unit uses the user's `.local/bin` and
the standard system binary directories in `PATH`.

Manage it with:

```bash
systemctl --user stop codex-resume.service
systemctl --user restart codex-resume.service
systemctl --user disable --now codex-resume.service
codex-resume logs
```

To use pane-specific settings, create a user drop-in:

```bash
systemctl --user edit codex-resume.service
```

Put this in the editor, then reload and restart the service:

```ini
[Service]
ExecStart=
ExecStart=%h/.local/bin/codex-resume resume --panes codex-gpu --message Kontynuuj
```

The empty `ExecStart=` clears the shipped command before the replacement. Use
`systemctl --user revert codex-resume.service` to remove the drop-in and return
to the generic default command.

Logs use short local times and readable `WORKSPACE:TAB:PANEL` descriptions:

```text
14:25:43 Watching V-GPU:kontynuuj-2:codex-gpu
14:25:43 Watching homestack:1:p1
14:25:43 Watching gpu/phase1:1:p1
```

Workspace and tab labels are used when present; an unnamed tab uses its number.
A pane uses its label or the short `pN` suffix when unnamed.
Remote descriptions include the machine label before the workspace.
