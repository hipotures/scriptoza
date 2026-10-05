#!/usr/bin/env python3
"""Watch Codex agents and selected Herdr panes, resuming errors and dismissing wait menus."""

import argparse
import errno
import fcntl
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path


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


class UncertainSendError(HerdrError):
    """Input delivery may have succeeded even though Herdr reported an error."""


class MonitorAlreadyRunning(RuntimeError):
    pass


RUNTIME_DIRECTORY_NAME = "codex-resume"
LOCK_FILENAME = "monitor.lock"
STATUS_FILENAME = "status.json"


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
    """Resolve currently live explicit selectors, including shared labels.

    A selector can refer to a pane or tab that has not appeared yet, for
    example while a remote session is still starting.  Missing selectors are
    therefore left pending for the next discovery cycle.
    """
    selected = {}
    items = panes if kind == "pane" else tabs
    for target in targets:
        id_matches = [item for item in items if target == item.get(f"{kind}_id")]
        label_matches = [item for item in items if target == item.get("label")]
        matches = id_matches or label_matches
        if not matches:
            continue
        for item in matches:
            members = (
                [item] if kind == "pane"
                else [pane for pane in panes if pane["tab_id"] == item["tab_id"]]
            )
            if not members:
                continue
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


def runtime_directory():
    """Return the per-user runtime directory used by the monitor."""
    runtime_root = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_root:
        runtime_root = f"/run/user/{os.getuid()}"
    return Path(runtime_root) / RUNTIME_DIRECTORY_NAME


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RuntimeState:
    """Own the monitor lock and its atomically replaced status snapshot."""

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else runtime_directory()
        self.lock_path = self.directory / LOCK_FILENAME
        self.status_path = self.directory / STATUS_FILENAME
        self._lock_file = None

    def acquire(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self._lock_file = self.lock_path.open("a+", encoding="utf-8")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if self._lock_file is not None:
                self._lock_file.close()
                self._lock_file = None
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise MonitorAlreadyRunning("Monitor is already running") from exc
            raise

    def release(self):
        if self._lock_file is None:
            return
        try:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            self._lock_file.close()
            self._lock_file = None

    def is_locked(self):
        """Probe whether another process currently owns the monitor lock."""
        try:
            lock_file = self.lock_path.open("r", encoding="utf-8")
        except FileNotFoundError:
            return False
        try:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    return True
                raise
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            return False
        finally:
            lock_file.close()

    def write_status(
        self,
        status,
        message,
        dry_run,
        panes=(),
        last_panes=(),
        error=None,
        last_check=None,
    ):
        payload = {
            "status": status,
            "last_check": last_check,
            "message": message,
            "dry_run": bool(dry_run),
            "panes": list(panes),
            "last_panes": list(last_panes),
            "error": error,
        }
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.status_path.with_name(
            f".{self.status_path.name}.{os.getpid()}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.status_path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def read_status(self):
        try:
            with self.status_path.open("r", encoding="utf-8") as stream:
                return json.load(stream), None
        except FileNotFoundError:
            return None, "status snapshot is not available yet"
        except (OSError, ValueError, TypeError) as exc:
            return None, f"cannot read status snapshot: {exc}"

    def clear_status(self):
        try:
            self.status_path.unlink()
        except FileNotFoundError:
            pass


def _format_freshness(timestamp):
    if not timestamp:
        return "never"
    try:
        checked = datetime.fromisoformat(timestamp)
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        age = max(0, int((datetime.now(timezone.utc) - checked).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return "unknown"
    if age < 60:
        return f"{age}s ago"
    if age < 3600:
        return f"{age // 60}m ago"
    return f"{age // 3600}h ago"


def _status_error(value):
    """Keep stale-status output readable without exposing internal pane IDs."""
    text = _display_text(value)
    return re.sub(r"\b[^\s:]+:p[^\s:]+\b", "pane", text)


def list_status():
    """Print the monitor snapshot without contacting Herdr."""
    state = RuntimeState()
    try:
        active = state.is_locked()
    except OSError as exc:
        print(f"Monitor status unavailable: cannot inspect lock: {exc}")
        return 1
    if not active:
        print("Monitor is not running")
        return 1
    snapshot, read_error = state.read_status()
    if read_error:
        print(f"Monitor is running (status unavailable: {read_error})")
        return 0
    if not isinstance(snapshot, dict):
        print("Monitor is running (status unavailable: invalid snapshot)")
        return 0
    status = snapshot.get("status", "unknown")
    if status == "starting":
        heading = "Monitor is starting"
    elif status == "stale":
        heading = "Monitor is running; discovery is stale"
    elif status == "watching":
        heading = "Monitor is running"
    else:
        heading = "Monitor is running; status is unknown"
    mode = "dry-run=yes" if snapshot.get("dry_run") else "dry-run=no"
    message = _display_text(snapshot.get("message")) or "(empty)"
    freshness = _format_freshness(snapshot.get("last_check"))
    print(f"{heading}; last check {freshness}; {mode}; message={message!r}")
    if status == "stale":
        error = _status_error(snapshot.get("error")) or "discovery failed"
        print(f"Error: {error}")
        panes = snapshot.get("last_panes", ())
        if panes:
            print("Last known panes:")
    else:
        panes = snapshot.get("panes", ())
    if isinstance(panes, list | tuple):
        for pane in panes:
            description = _display_text(pane)
            if description:
                print(description)
    return 0


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
                        try:
                            herdr("pane", "send-keys", pane_id, "2")
                        except HerdrError as exc:
                            raise UncertainSendError(
                                f"Input delivery uncertain for {target}: {exc}"
                            ) from exc
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
                    try:
                        herdr("pane", "run", pane_id, self.message)
                    except HerdrError as exc:
                        raise UncertainSendError(
                            f"Input delivery uncertain for {target}: {exc}"
                        ) from exc
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


def _safe_status_update(state, **kwargs):
    if state is None:
        return
    try:
        state.write_status(**kwargs)
    except (OSError, TypeError, ValueError) as exc:
        # State output must never trigger another pane input.
        log(f"Status update failed: {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Show the live monitor status without contacting Herdr")
    commands.add_parser("logs", help="Show recent service logs and follow new entries; Ctrl+C to exit")
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
    if args.command == "list":
        return list_status()
    if args.command == "logs":
        try:
            os.execvp("journalctl", [
                "journalctl", "--user", "--unit=codex-resume.service",
                "--lines=50", "--follow", "--output=cat", "--no-pager",
            ])
        except OSError as exc:
            print(f"Error: cannot open service logs: {exc}", file=sys.stderr)
            return 1
        return 0
    if not args.message.strip() or any(ord(character) < 32 or ord(character) == 127 for character in args.message):
        parser.error("--message must be nonempty, single-line text without terminal controls")

    # A one-shot dry run only reads panes, so it remains usable while the live
    # monitor owns the lock and does not create or replace its status state.
    state = None
    if not (args.once and args.dry_run):
        state = RuntimeState()
        try:
            state.acquire()
        except MonitorAlreadyRunning as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"Error: cannot initialize monitor runtime state: {exc}", file=sys.stderr)
            return 1

    monitor = Monitor(args.message, args.dry_run)
    first = True
    stop_requested = threading.Event()
    previous_sigterm = None
    signal_installed = False

    def handle_sigterm(signum, frame):
        stop_requested.set()

    try:
        try:
            previous_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, handle_sigterm)
            signal_installed = True
        except (OSError, ValueError):
            # Tests or embedded callers may not run the monitor on the main thread.
            pass
        _safe_status_update(
            state,
            status="starting",
            message=args.message,
            dry_run=args.dry_run,
            panes=(),
            last_panes=(),
            error=None,
            last_check=None,
        )
        log(
            f"{'Dry run' if args.dry_run else 'Monitor'} started; "
            f"interval={args.interval:g}s; Ctrl+C to stop"
        )
        while True:
            if stop_requested.is_set():
                log("Monitor stopped")
                return 0
            try:
                selected = discover_targets(args.panes, args.tabs)
            except HerdrError as exc:
                if first or args.once:
                    raise
                detail = f"Discovery failed; no input sent this cycle: {exc}"
                log(detail)
                _safe_status_update(
                    state,
                    status="stale",
                    message=args.message,
                    dry_run=args.dry_run,
                    panes=(),
                    last_panes=tuple(sorted(monitor.pane_descriptions.values())),
                    error=detail,
                    last_check=_utc_now(),
                )
            else:
                monitor.poll(selected)
                _safe_status_update(
                    state,
                    status="watching",
                    message=args.message,
                    dry_run=args.dry_run,
                    panes=tuple(sorted(monitor.pane_descriptions.values())),
                    last_panes=(),
                    error=None,
                    last_check=_utc_now(),
                )
            first = False
            if args.once:
                return 0
            if stop_requested.wait(args.interval):
                log("Monitor stopped")
                return 0
    except KeyboardInterrupt:
        log("Monitor stopped")
        return 0
    except UncertainSendError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except HerdrError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if signal_installed:
            try:
                signal.signal(signal.SIGTERM, previous_sigterm)
            except (OSError, ValueError) as exc:
                log(f"Signal handler cleanup failed: {exc}")
        if state is not None:
            try:
                state.clear_status()
            except OSError as exc:
                log(f"Status cleanup failed: {exc}")
            try:
                state.release()
            except OSError as exc:
                log(f"Lock cleanup failed: {exc}")


if __name__ == "__main__":
    sys.exit(main())
