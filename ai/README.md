# AI Utilities

## Codex Resume

`codex_resume.py` monitors visible Herdr panes for Codex states that need an
automatic response:

- a capacity error, followed by the configured message and Enter;
- the complete “Giving this request a little extra thought” menu, dismissed by
  pressing option `2` without Enter while preserving the current model.

The runtime uses Python's standard library and the `herdr` executable installed
in `PATH`. Run it inside a Herdr-managed pane with `HERDR_ENV=1`:

```bash
python3 ai/codex_resume.py resume
```

Install from the repository root with:

```bash
python3 utils/install.py
```

The installer adds the `codex-resume` command. It uses the existing `rich`
dependency required by `utils/install.py`:

```bash
codex-resume resume --panes aa,bb,cc --message 'Resume'
```

Automatic discovery includes every live pane whose current-server agent record
has `agent == "codex"`. Use `--panes` for comma-separated pane labels or IDs and
`--tabs` for comma-separated tab labels or IDs; both options may be used
together. Exact IDs take precedence over labels, labels include all matching
panes (a tab label includes every pane in each matching tab), and overlapping
selections are deduplicated by `pane_id`. Panes that are not recognized by the
current server must be selected explicitly.

Useful options:

```text
--once             Check the selected panes once and exit
--dry-run          Log actions without sending input
--interval 5       Poll every five seconds (the default)
--message TEXT     Submit TEXT for a capacity error (default: Resume)
```

Only visible terminal text is inspected, so manually scrolling can hide a
relevant error or continuation. The continuation guard looks below the latest
capacity error for the configured message, case-insensitively. Run one monitor
per pane. A failed input submission stops the monitor because delivery is
uncertain.

Logs include timestamps, pane labels and IDs, tab IDs, detected text positions,
and actions taken.
