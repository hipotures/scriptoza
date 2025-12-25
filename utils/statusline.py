#!/usr/bin/env python3
"""
Custom status line for Claude Code with Rich formatting.
"""
import sys
import json
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.text import Text

# Default log file path
DEFAULT_LOG_FILE = Path.home() / '.claude' / 'log' / 'statusline.log'

def log_input(data: dict, log_file: Path):
    """Log input data to file."""
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(log_file, 'a') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"[{timestamp}]\n")
            f.write(json.dumps(data, indent=2))
            f.write("\n")
    except Exception as e:
        # Silent fail - don't break status line if logging fails
        pass

def shorten_path(path: str, max_segments: int = 2) -> str:
    """Shorten path to last N segments if longer."""
    parts = path.strip('/').split('/')
    if len(parts) > max_segments:
        return '/'.join(parts[-max_segments:])
    return path

def get_git_info(cwd: str) -> tuple[str, str]:
    """Get git branch and stats. Returns (branch, stats)."""
    try:
        # Check if in git repo
        subprocess.run(
            ['git', 'rev-parse', '--git-dir'],
            cwd=cwd,
            capture_output=True,
            check=True
        )

        # Get branch
        result = subprocess.run(
            ['git', '-c', 'core.useBuiltinFSMonitor=false', 'branch', '--show-current'],
            cwd=cwd,
            capture_output=True,
            text=True
        )
        branch = result.stdout.strip()

        # Get diff stats
        result = subprocess.run(
            ['git', '-c', 'core.useBuiltinFSMonitor=false', 'diff', '--shortstat'],
            cwd=cwd,
            capture_output=True,
            text=True
        )
        diff_output = result.stdout.strip()

        ins = 0
        dels = 0
        if diff_output:
            if 'insertion' in diff_output:
                parts = diff_output.split()
                for i, part in enumerate(parts):
                    if 'insertion' in part and i > 0:
                        ins = int(parts[i-1])
                    if 'deletion' in part and i > 0:
                        dels = int(parts[i-1])

        stats = f"(+{ins},-{dels})"

        return (f"⎇ {branch}" if branch else '', stats)
    except:
        return ('', '')

def format_k(value: float) -> str:
    """Format number in thousands with 1 decimal."""
    return f"{value / 1000:.1f}k"

def get_demo_data() -> dict:
    """Generate demo data for testing."""
    return {
        "model": {
            "display_name": "Sonnet 4.5"
        },
        "context_window": {
            "current_usage": {
                "input_tokens": 49900,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0
            },
            "total_output_tokens": 4100
        },
        "workspace": {
            "current_dir": "/home/xai/DEV/scriptoza"
        }
    }

def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description='Status line for Claude Code')
    parser.add_argument('--demo', action='store_true', help='Run in demo mode with simulated data')
    parser.add_argument('--log-file', type=Path, default=DEFAULT_LOG_FILE, help='Path to log file')

    # Parse only known args to avoid issues when stdin is piped
    args, _ = parser.parse_known_args()

    if args.demo:
        data = get_demo_data()
        print("🎨 DEMO MODE - Simulated data", file=sys.stderr)
    else:
        # Read JSON from stdin
        try:
            data = json.load(sys.stdin)
        except Exception as e:
            # If no input, show error and exit
            print(f"Error reading input: {e}", file=sys.stderr)
            return

    # Log input data
    log_input(data, args.log_file)

    # Extract data
    model = data.get('model', {}).get('display_name', 'Unknown')

    # Context usage
    ctx_usage = data.get('context_window', {}).get('current_usage')
    ctx_text = ''
    if ctx_usage:
        total = (
            ctx_usage.get('input_tokens', 0) +
            ctx_usage.get('cache_creation_input_tokens', 0) +
            ctx_usage.get('cache_read_input_tokens', 0)
        )
        ctx_text = f"Ctx: {format_k(total)}"

    # Output tokens
    out_tokens = data.get('context_window', {}).get('total_output_tokens', 0)
    out_text = ''
    if out_tokens > 0:
        out_text = f"Out: {format_k(out_tokens)}"

    # Working directory
    cwd = data.get('workspace', {}).get('current_dir', '')
    cwd_short = shorten_path(cwd)

    # Git info
    branch, stats = get_git_info(cwd)

    console = Console(force_terminal=True, legacy_windows=False)

    # --- Build 2-line status without "black gaps" ---
    SEP_RIGHT = "\ue0b0"  # Right separator (between sections)
    SEP_LEFT = "\ue0b2"   # Left separator (start of line)
    SEP_END = "\ue0b0"    # End separator (end of line)

    def pad_to(t: Text, width: int, style: str) -> Text:
        missing = width - t.cell_len
        if missing > 0:
            t.append(" " * missing, style=style)
        return t

    # Column 1 (left)
    c1r1 = Text()
    c1r1.append(SEP_LEFT, style="red on black")  # Lewy separator (czarne tło -> czerwone)
    c1r1.append(f" Model: {model} ", style="white on red")
    c1r1.append(SEP_RIGHT, style="yellow on red")  # przejście do żółtego

    c1r2 = Text()
    c1r2.append(SEP_LEFT, style="red on black")  # Lewy separator (czarne tło -> czerwone)
    c1r2.append(f" cwd: {cwd_short} ", style="white on red")
    c1r2.append(SEP_RIGHT, style="yellow on red")  # przejście do żółtego

    # Column 2 (middle)
    c2r1 = Text(f" {ctx_text} ", style="black on yellow") if ctx_text else Text("")
    if ctx_text:
        c2r1.append(SEP_RIGHT, style="blue on yellow")  # przejście do niebieskiego

    c2r2 = Text(f" {out_text} ", style="black on yellow") if out_text else Text("")
    if out_text:
        c2r2.append(SEP_RIGHT, style="blue on yellow")

    # Column 3 (right)
    c3r1 = Text(f" {branch} ", style="white on blue") if branch else Text("")
    if branch:
        c3r1.append(SEP_END, style="black on blue")  # Prawy separator na końcu

    c3r2 = Text(f" {stats} ", style="white on blue") if stats else Text("")
    if stats:
        c3r2.append(SEP_END, style="black on blue")  # Prawy separator na końcu

    # Align columns by padding WITH BACKGROUND style (no black gaps)
    col1_w = max(c1r1.cell_len, c1r2.cell_len)
    col2_w = max(c2r1.cell_len, c2r2.cell_len)
    col3_w = max(c3r1.cell_len, c3r2.cell_len)

    pad_to(c1r1, col1_w, "on red")
    pad_to(c1r2, col1_w, "on red")
    if ctx_text:
        pad_to(c2r1, col2_w, "on yellow")
    if out_text:
        pad_to(c2r2, col2_w, "on yellow")
    if branch:
        pad_to(c3r1, col3_w, "on blue")
    if stats:
        pad_to(c3r2, col3_w, "on blue")

    row1 = Text(); row1.append_text(c1r1); row1.append_text(c2r1); row1.append_text(c3r1)
    row2 = Text(); row2.append_text(c1r2); row2.append_text(c2r2); row2.append_text(c3r2)

    # Print
    with console.capture() as capture:
        console.print(row1)
        console.print(row2, end='')

    print(capture.get(), end='')

if __name__ == '__main__':
    main()
