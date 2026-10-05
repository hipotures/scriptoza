# Herdr resume history

## 2026-10-05

Migrated the standalone monitor from the temporary workspace to
`ai/herdr_resume.py`, with regression tests in `tests/test_herdr_resume.py`.
Public usage and requirements are in `ai/README.md`. The existing installer
`utils/install.py` installs it as `~/.local/bin/herdr-resume`.

Current interface:

```bash
herdr-resume resume
herdr-resume resume --panes aa,bb,cc --message "Resume"
herdr-resume resume --tabs work-1,work-2 --once --dry-run
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
because an uncertain delivery must not be retried blindly. Logs include local
timestamps, pane identity, detection coordinates, and sent actions.

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
`python3 -m unittest discover -s tests -q` (38 Herdr monitor tests and 19
existing tests). Python compilation passed. A real installer run with
`Path.home()` redirected to a temporary directory copied an executable
`herdr-resume` whose bytes matched the source; its `resume --help` command
passed. The user's installed binaries and configuration were not modified.
