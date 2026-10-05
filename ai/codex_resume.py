#!/usr/bin/env python3
"""Watch Codex agents and selected Herdr panes, resuming errors and dismissing wait menus."""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime


CAPACITY_MESSAGE = "Selected model is at capacity. Please try a different model."
# Herdr's visible text includes terminal line wrapping, even inside words.
CAPACITY_PATTERN = re.compile(r"\s*".join(map(re.escape, CAPACITY_MESSAGE.replace(" ", ""))))
EXTRA_THOUGHT_MENU_LINES = (
    "Giving this request a little extra thought",
    "1. Retry with a faster model",
    "2. Dismiss and keep waiting",
    "3. Learn more",
)
EXTRA_THOUGHT_MENU_PATTERNS = tuple(
    re.compile(
        r"^[^\S\n]*(?:[›>❯][^\S\n]*)?"
        + r"\s*".join(map(re.escape, line.replace(" ", "")))
        + r"[^\S\n]*$",
        re.MULTILINE,
    )
    for line in EXTRA_THOUGHT_MENU_LINES
)
UNNAMED_PANE = "Unnamed pane"
UNNAMED_TAB = "Unnamed tab"
UNNAMED_WORKSPACE = "Unnamed workspace"


class HerdrError(RuntimeError):
    pass


def log(message):
    print(f"{datetime.now().astimezone().strftime('%H:%M:%S')} {message}", flush=True)


def herdr(*args):
    try:
        result = subprocess.run(
            ["herdr", *args], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HerdrError(f"herdr {' '.join(args[:3])}: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise HerdrError(f"herdr {' '.join(args[:3])}: {detail}")
    return result.stdout


def inventory(kind):
    try:
        return json.loads(herdr(kind, "list"))["result"][f"{kind}s"]
    except (ValueError, KeyError, TypeError) as exc:
        raise HerdrError(f"Invalid JSON from herdr {kind} list") from exc


def resolve_targets(kind, targets, tabs, panes):
    """Resolve explicit pane or tab selectors, including shared labels."""
    selected = {}
    items = panes if kind == "pane" else tabs
    for target in targets:
        id_matches = [item for item in items if target == item[f"{kind}_id"]]
        label_matches = [item for item in items if target == item.get("label")]
        matches = id_matches or label_matches
        if not matches:
            raise HerdrError(f"Target not found: {target!r}")
        for item in matches:
            members = (
                [item] if kind == "pane"
                else [pane for pane in panes if pane["tab_id"] == item["tab_id"]]
            )
            if not members:
                raise HerdrError(f"Target has no live panes: {target!r}")
            for pane in members:
                selected[pane["pane_id"]] = pane
    return selected


def discover_targets(pane_targets, tab_targets):
    panes = inventory("pane")
    codex_ids = {
        agent["pane_id"] for agent in inventory("agent") if agent.get("agent") == "codex"
    }
    tabs = inventory("tab")
    selected = {pane["pane_id"]: pane for pane in panes if pane["pane_id"] in codex_ids}
    if pane_targets:
        selected.update(resolve_targets("pane", pane_targets, [], panes))
    if tab_targets:
        selected.update(resolve_targets("tab", tab_targets, tabs, panes))
    workspace_names = {
        workspace.get("workspace_id"): workspace.get("label") or UNNAMED_WORKSPACE
        for workspace in inventory("workspace")
    }
    tab_names = {
        tab.get("tab_id"): _display_text(tab.get("label"))
        or _display_text(tab.get("number"))
        or UNNAMED_TAB
        for tab in tabs
    }
    return {
        pane_id: {
            **pane,
            "workspace_name": workspace_names.get(
                pane.get("workspace_id"), UNNAMED_WORKSPACE
            ),
            "tab_name": tab_names.get(pane.get("tab_id"), UNNAMED_TAB),
        }
        for pane_id, pane in selected.items()
    }


def _display_text(value):
    """Collapse whitespace so terminal metadata cannot create multiline logs."""
    return " ".join(str(value).split()) if value is not None else ""


def _pane_name(pane):
    label = _display_text(pane.get("label"))
    if label:
        return label
    pane_id = _display_text(pane.get("pane_id"))
    if pane_id:
        return pane_id.rsplit(":", 1)[-1]
    return UNNAMED_PANE


def describe_pane(pane):
    """Return a compact workspace, tab, and pane description."""
    workspace = _display_text(pane.get("workspace_name")) or UNNAMED_WORKSPACE
    tab = _display_text(pane.get("tab_name")) or UNNAMED_TAB
    return f"{workspace}:{tab}:{_pane_name(pane)}"


class Monitor:
    def __init__(self, message, dry_run=False):
        self.message = message
        self.dry_run = dry_run
        self.continuation_pattern = re.compile(
            r"^\s*›\s*"
            + r"\s*".join(map(re.escape, message.replace(" ", "")))
            + r"[^\S\n]*$",
            re.MULTILINE | re.IGNORECASE,
        )
        self.errors = {}
        self.dismissed_menus = set()
        self.pane_descriptions = {}

    def poll(self, selected):
        current = set(selected)
        current_descriptions = {
            pane_id: describe_pane(pane) for pane_id, pane in selected.items()
        }
        previous = set(self.pane_descriptions)
        for pane_id in sorted(current - previous):
            description = current_descriptions[pane_id]
            log(f"Watching {description}")
        for pane_id in sorted(previous - current):
            description = self.pane_descriptions.pop(pane_id)
            log(f"Stopped watching {description}")
            self.errors.pop(pane_id, None)
            self.dismissed_menus.discard(pane_id)
        self.pane_descriptions.update(current_descriptions)
        for pane_id in selected:
            target = current_descriptions[pane_id]
            try:
                visible = herdr("pane", "read", pane_id, "--source", "visible", "--format", "text")
            except HerdrError as exc:
                detail = str(exc).replace(pane_id, target)
                log(f"Read failed for {target}; keeping detection state: {detail}")
                continue
            if all(pattern.search(visible) for pattern in EXTRA_THOUGHT_MENU_PATTERNS):
                if pane_id not in self.dismissed_menus:
                    log(f"Detected extra-thought menu in {target}")
                    # A timeout can still mean input was delivered; do not retry blindly.
                    self.dismissed_menus.add(pane_id)
                    if self.dry_run:
                        log(f"DRY RUN {target}: would press 2 (Dismiss and keep waiting)")
                    else:
                        herdr("pane", "send-keys", pane_id, "2")
                        log(f"Sent key 2 signal to {target}: Dismiss and keep waiting")
                elif self.dry_run:
                    log(f"DRY RUN {target}: already handled extra-thought menu")
                continue
            self.dismissed_menus.discard(pane_id)
            # Match Codex's error row, excluding drafts and echoed user prompts.
            matches = [
                match for match in CAPACITY_PATTERN.finditer(visible)
                if visible[visible.rfind("\n", 0, match.start()) + 1:match.start()].strip() == "■"
            ]
            count = len(matches)
            row = 0
            context = ""
            if matches:
                latest = matches[-1]
                row = visible.count("\n", 0, latest.start()) + 1
                # Ignore line reflow; retain nearby transcript as the error's identity.
                context = "".join(visible[:latest.start()].split())[-256:]
            previous_count, _, previous_context = self.errors.get(pane_id, (0, 0, ""))
            same_context = (
                context == previous_context
                or (context and previous_context and (
                    context.endswith(previous_context) or previous_context.endswith(context)
                ))
            )
            new_error = count and (
                previous_count == 0 or count > previous_count
                or not same_context
            )
            already_continued = bool(matches) and bool(
                self.continuation_pattern.search(visible[matches[-1].end():])
            )
            self.errors[pane_id] = (count, row, context)
            if new_error and not already_continued:
                positions = []
                for match in matches:
                    row = visible.count("\n", 0, match.start()) + 1
                    column = match.start() - visible.rfind("\n", 0, match.start())
                    positions.append(f"{row}:{column}")
                log(f"Detected capacity error in {target}; text positions (row:column): {', '.join(positions)}")
                if self.dry_run:
                    log(f"DRY RUN {target}: would submit {self.message!r} + Enter")
                else:
                    # One ordered submission, with Herdr handling bracketed paste.
                    # If this fails, exit: a timeout may still mean input was delivered.
                    herdr("pane", "run", pane_id, self.message)
                    log(f"Sent {self.message!r} + Enter signal to {target}")
            elif self.dry_run:
                if already_continued:
                    status = "continuation below latest error; no input sent"
                else:
                    status = "already handled visible error" if count else "no visible capacity error"
                log(f"DRY RUN {target}: {status}")


def positive_seconds(value):
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Must be a positive number of seconds") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("Must be a finite positive number of seconds")
    return seconds


def selector_list(value):
    targets = [target.strip() for target in value.split(",")]
    if any(not target for target in targets):
        raise argparse.ArgumentTypeError("Use comma-separated nonempty labels or IDs")
    return targets


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    resume = commands.add_parser(
        "resume", help="Monitor all recognized Codex agents plus explicitly selected panes",
        description="Monitor all recognized Codex agents plus selected panes/tabs, deduplicated by pane ID.",
    )
    resume.add_argument(
        "--panes", type=selector_list, metavar="NAME,NAME,...",
        default=[], help="Additional comma-separated exact pane labels or IDs; include all matches",
    )
    resume.add_argument(
        "--tabs", type=selector_list, metavar="NAME,NAME,...",
        default=[], help="Additional comma-separated exact tab labels or IDs; include all their panes",
    )
    resume.add_argument("--interval", type=positive_seconds, default=5.0, help="Poll seconds (default: 5)")
    resume.add_argument("--message", default="Resume", help="Text to submit (default: Resume)")
    resume.add_argument("--once", action="store_true", help="Check all selected panes once, then exit")
    resume.add_argument("--dry-run", action="store_true", help="Log detections without sending input")
    args = parser.parse_args(argv)
    if os.environ.get("HERDR_ENV") != "1":
        parser.error("Run this script inside a Herdr-managed pane (HERDR_ENV=1)")
    if not args.message.strip() or any(ord(character) < 32 or ord(character) == 127 for character in args.message):
        parser.error("--message must be nonempty, single-line text without terminal controls")
    monitor = Monitor(args.message, args.dry_run)
    log(f"{'Dry run' if args.dry_run else 'Monitor'} started; interval={args.interval:g}s; Ctrl+C to stop")
    first = True
    try:
        while True:
            try:
                selected = discover_targets(args.panes, args.tabs)
            except HerdrError as exc:
                if first or args.once:
                    raise
                log(f"Discovery failed; no input sent this cycle: {exc}")
            else:
                monitor.poll(selected)
            first = False
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log("Monitor stopped")
        return 0
    except HerdrError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
