# Repository Guidelines

## Project Structure & Module Organization

Scriptoza is a collection of standalone utilities grouped by purpose. Put video tools in `video/`, photo tools in `photo/`, and general-purpose scripts in `utils/`. Each category has its own `README.md`; update it when behavior or requirements change. `firefox-yt/` contains the Firefox extension, native helper, and packaging scripts. Older utilities live in `deprecated/`. Automated checks are in `tests/`, with test modules named `test_*.py`.

The root `.gitignore` ignores files by default and allow-lists supported paths and extensions. When adding a new directory or file type, add an explicit allow rule.

## Build, Test, and Development Commands

There is no repository-wide build step. Run scripts directly from the repository root, for example:

```bash
python3 video/check_collisions.py /path/to/videos
python3 photo/rename_photo.py /path/to/photo.jpg
python3 utils/install.py
python3 -m unittest discover -s tests -v
```

The installer copies selected utilities to `~/.local/bin` and configuration to `~/.config/scriptoza`. For the Firefox integration, run `firefox-yt/install.sh`; create an extension archive with `firefox-yt/package.sh /tmp/firefox-yt.xpi`.

## Coding Style & Naming Conventions

Keep scripts self-contained and avoid cross-category dependencies. Use four-space indentation in Python, `snake_case` for functions and variables, `UPPER_CASE` for constants, and `Path` for filesystem work. Prefer `argparse`, type hints, and standard-library features already used in the repository. JavaScript follows `camelCase`, semicolons, and strict mode. Keep code, help text, logs, and comments in English. Do not add comments unless they clarify genuinely non-obvious behavior.

For multi-file operations, use `rich.progress` with the repository's compact, non-expanding layout and consistently padded task descriptions.

## Testing Guidelines

Tests use the standard-library `unittest` framework. Add focused `TestCase` classes and `test_*` methods under `tests/`. Run the full suite before committing. There is no configured coverage threshold, formatter, or linter; manually exercise changed CLIs with representative inputs and safe options such as `--dry-run` where available.

## Commit & Pull Request Guidelines

Use concise, imperative, sentence-case commit subjects, such as `Add video rotation detector`. Keep each commit scoped to one change. Pull requests should explain the problem and solution, list verification commands, link relevant issues, and include terminal output or screenshots when user-visible behavior changes.
