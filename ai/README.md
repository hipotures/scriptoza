# AI Utilities

## Codex Resume

`codex_resume.py` monitors Codex panes and responds to two visible states:

- a capacity error, followed by the configured message and Enter;
- the complete “Giving this request a little extra thought” menu, dismissed by
  pressing option `2` without Enter while preserving the current model.

The runtime uses Python's standard library and the `herdr` executable in
`PATH`. It connects to the current user's Herdr server, so it can run from any
terminal or as a systemd user service; it does not need to run inside a Herdr
pane.

Install the command and the optional user service from the repository root:

```bash
python3 utils/install.py
```

The installer copies `codex-resume` to `~/.local/bin` and the service unit to
`~/.config/systemd/user/codex-resume.service`. It does not enable or start the
service automatically.

Run a monitor manually with the default message or with an explicitly named
remote pane:

```bash
codex-resume resume
codex-resume resume --panes codex-gpu --message Kontynuuj
```

Automatic discovery includes every live pane whose current-server agent record
has `agent == "codex"`. Use `--panes` or `--tabs` for comma-separated pane/tab
labels or IDs. An explicit selector that is not present yet is kept pending
and retried on later polls; this also lets a selector survive a pane closing
and reopening. Panes that are not recognized by the current server can be
selected explicitly. Exact IDs take precedence over labels; labels include all
matching panes or tabs, and overlapping selections are deduplicated by pane ID.

The monitor keeps a single-process lock, so a second monitor exits instead of
watching the same runtime concurrently. Stop a manually started monitor before
starting the systemd service.

The `list` command prints the current runtime watch snapshot held by the active
monitor. It is not a fresh Herdr candidate scan.

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
journalctl --user -u codex-resume.service -f
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
```

Workspace and tab labels are used when present; an unnamed tab uses its number.
A pane uses its label or the short `pN` suffix when unnamed.
