# Codex resume history

## User service and live watch list (2026-10-05)

`codex-resume logs` shows the last 50 service log entries and follows new ones
with compact output. Ctrl+C exits the viewer without stopping the service.

The installer now copies `ai/codex-resume.service` to
`~/.config/systemd/user/codex-resume.service`. Enable login autostart with
`systemctl --user daemon-reload` and
`systemctl --user enable --now codex-resume.service`. The generic unit uses the
default `Resume` message; see `ai/README.md` for a user drop-in with explicit
pane selectors and a different message.

`codex-resume list` reads the active monitor's runtime snapshot without calling
Herdr. It shows the last check time, mode, message, and readable watch names.
An inactive monitor does not expose old snapshots as a current watch list;
discovery failures mark the snapshot stale. A user runtime lock prevents
simultaneous monitors. A one-shot dry run can still run beside the monitor.

Monitoring no longer requires `HERDR_ENV=1`. Missing explicit selectors stay
pending until the pane or tab appears, without blocking other Codex sessions.
The service retries ordinary startup failures after five seconds, but uncertain
input delivery exits with status `2`, which prevents automatic restart.

## 2026-10-05

Migrated the standalone monitor from the temporary workspace to
`ai/codex_resume.py`, with regression tests in `tests/test_codex_resume.py`.
Public usage and requirements are in `ai/README.md`. The existing installer
`utils/install.py` installs it as `~/.local/bin/codex-resume`.

Current interface:

```bash
codex-resume resume
codex-resume resume --panes aa,bb,cc --message "Resume"
codex-resume resume --tabs work-1,work-2 --once --dry-run
```

The `resume` command discovers all recognized Codex agents on the current
Herdr server and adds any explicitly selected panes or tabs. Overlapping
selections are deduplicated by `pane_id` before reading or sending input.
Labels are matched exactly, with all duplicate labels included; IDs take
precedence. Raw SSH terminals can be included explicitly even if Herdr does
not recognize their remote agents. Saved remote machine inventories are not
automatically scanned.

Only the visible viewport is read. A real capacity error (the `■` row) submits
the configurable message plus Enter. A matching continuation prompt below the
latest error prevents duplicate submission; error identity tracking tolerates
movement/reflow. The complete extra-thought menu sends only key `2`, preserving
the model, once while continuously visible. A failed send stops monitoring
because an uncertain delivery must not be retried blindly. Logs use short local
times and human-readable `WORKSPACE:TAB:PANEL` descriptions, for example
`14:25:43 Watching V-GPU:kontynuuj-2:codex-gpu`. Panel labels are preferred;
the pane ID suffix is used when a panel has no label, and tab numbers are used
when a tab has no label.

Earlier user-authorized live tests verified text plus Enter for a capacity
error and confirmed that key `2` dismisses the extra-thought menu. The latest
combined-discovery dry run selected five unique panes from four Codex agents
plus two explicit pane IDs, including one overlap. It sent no input.
No continuous monitor was started during migration. Existing pane labels and
Herdr layout were not changed. Detailed earlier research remains in the
scratch workspace history `/home/user/DEV/tmp/HERDR_RESUME.md`.

Continue development in this repository. Do not restore obsolete script names
or positional-target aliases.

Verification after migration: all 57 repository tests passed with
`python3 -m unittest discover -s tests -q` (38 Codex monitor tests and 19
existing tests). Python compilation passed. A real installer run with
`Path.home()` redirected to a temporary directory copied an executable
`codex-resume` whose bytes matched the source; its `resume --help` command
passed. The user's installed binaries and configuration were not modified.
