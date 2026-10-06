# AI Utilities

## GNOME Codex Status

`codex-status/` is a GNOME Shell 50 extension written in JavaScript/GJS. It
shows local Codex agents and Codex agents on every enabled saved Herdr machine.
It reads agent status directly from Herdr and runs independently of
`codex-resume`; it never sends input, marks completions as seen, or controls
services.
It requires `herdr` and GNU coreutils `timeout` in the user's executable paths.

Install and enable it for your user:

```bash
bash ai/install_codex_status.sh
```

Log out and log back in after installing or updating it. GNOME Shell 50 loads
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
Collector/model changes and stylesheet changes require a new session.

The panel shows one colored dot per non-idle agent, with no icon or counters.
Agents sharing a state have separate dots. Idle agents are hidden from the panel
while any other state is present. If all agents are idle, every idle agent has
its own gray dot so the full list remains accessible.
Click it to see the complete list, including idle agents, with each agent's
machine, workspace, tab, pane, and current state.

| Herdr state | Appearance | Meaning |
| --- | --- | --- |
| `blocked` | Blinking red | Waiting for an answer or approval |
| `done` | Green | Completed; Herdr has not marked the result as seen |
| `working` | Steady blue | Working |
| `unknown` | Yellow | Herdr cannot classify the agent's state |
| `idle` | Gray | Ready for another instruction |

The table order is also the menu's state priority. `done` means the turn
finished, not necessarily that the task succeeded. Reading status does not
change `done` to `idle`.

Polling starts immediately and then runs every 5 seconds. A slow round never
overlaps the next round, and opening the menu does not trigger extra requests.
Each round reads the enabled machine list once and requests one `api snapshot`
per server, concurrently. Snapshots contain agent and layout names in one
response. Subprocess communication is asynchronous; an 8-second timeout stops
unresponsive requests, with a one-second termination grace period. The timeout
also covers SSH child processes, and disabling the widget terminates their
process groups. Unreachable remote machines are ignored: they have no
rows or warning indicators and their agents do not contribute to counters.
An unavailable remote profile is not queried again for 60 seconds, while active
agents continue updating every 5 seconds. A recovered machine returns on the
next retry. The Herdr CLI does not expose the client's sidebar connection
state in its machine list; failed remote snapshot requests identify machines
to ignore. A machine-list or local-server failure is still reported in the menu.
Disabling the extension removes timers, destroys its panel/menu, and stops its
pending commands.

The menu footer shows the update time, total polling latency, and time spent
parsing JSON. Run the standalone GJS benchmark for three rounds and their mean:

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
gnome-extensions pack ai/codex-status --extra-source=collector.js --extra-source=model.js --extra-source=reload.js --out-dir=/tmp --force
dbus-run-session -- gnome-shell-test-tool --headless --extension /tmp/codex-status@scriptoza.shell-extension.zip ai/codex_status_shell_test.js
```

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

Discovery runs concurrently across servers. An unreachable server does not stop
monitoring the others. Its previous detection state is retained without reading
or sending input until discovery succeeds again. Failures and recoveries are
logged, and `list` reports current discovery errors alongside watched panes.

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
--interval 5       Poll every five seconds (the default)
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
