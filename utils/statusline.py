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
        "cost": {
            "total_cost_usd": 0.31
        },
        "context_window": {
            "total_input_tokens": 14828,
            "total_output_tokens": 4275,
            "current_usage": {
                "input_tokens": 49900,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0
            }
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

    # Column 2: In/Out (total tokens)
    in_tokens = data.get('context_window', {}).get('total_input_tokens', 0)
    out_tokens = data.get('context_window', {}).get('total_output_tokens', 0)
    in_val = format_k(in_tokens)
    out_val = format_k(out_tokens)

    # Column 3: Ctx/Cost
    ctx_usage = data.get('context_window', {}).get('current_usage')
    ctx_total = 0
    if ctx_usage:
        ctx_total = (
            ctx_usage.get('input_tokens', 0) +
            ctx_usage.get('cache_creation_input_tokens', 0) +
            ctx_usage.get('cache_read_input_tokens', 0)
        )
    ctx_val = format_k(ctx_total)
    cost_usd = data.get('cost', {}).get('total_cost_usd', 0)
    cost_val = f"{cost_usd:.2f}"

    # Right-align values in column 2 (In/Out)
    max_val_width_col2 = max(len(in_val), len(out_val))
    in_text = f"In:  {in_val:>{max_val_width_col2}}"
    out_text = f"Out: {out_val:>{max_val_width_col2}}"

    # Right-align values in column 3 (Ctx/Cost)
    max_val_width_col3 = max(len(ctx_val), len(cost_val))
    ctx_text = f"Ctx: {ctx_val:>{max_val_width_col3}}"
    cost_text = f"USD: {cost_val:>{max_val_width_col3}}"

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

    # Column 1 (left) - Model/cwd
    c1r1 = Text(f" {model} ", style="white on red")
    c1r2 = Text(f" {cwd_short} ", style="white on red")

    # Column 2 (In/Out) - yellow
    c2r1 = Text(f" {in_text} ", style="black on yellow")
    c2r2 = Text(f" {out_text} ", style="black on yellow")

    # Column 3 (Ctx/Cost) - green (NEW)
    c3r1 = Text(f" {ctx_text} ", style="black on green")
    c3r2 = Text(f" {cost_text} ", style="black on green")

    # Column 4 (branch/stats) - blue
    c4r1 = Text(f" {branch} ", style="white on blue") if branch else Text("")
    c4r2 = Text(f" {stats} ", style="white on blue") if stats else Text("")

    # Align columns by padding WITH BACKGROUND style (no black gaps)
    col1_w = max(c1r1.cell_len, c1r2.cell_len)
    col2_w = max(c2r1.cell_len, c2r2.cell_len)
    col3_w = max(c3r1.cell_len, c3r2.cell_len)
    col4_w = max(c4r1.cell_len, c4r2.cell_len)

    pad_to(c1r1, col1_w, "on red")
    pad_to(c1r2, col1_w, "on red")
    pad_to(c2r1, col2_w, "on yellow")
    pad_to(c2r2, col2_w, "on yellow")
    pad_to(c3r1, col3_w, "on green")
    pad_to(c3r2, col3_w, "on green")
    if branch:
        pad_to(c4r1, col4_w, "on blue")
    if stats:
        pad_to(c4r2, col4_w, "on blue")

    # Złóż wiersze z separatorami TYLKO SKRAJNYMI
    # Row 1
    row1 = Text()
    row1.append(SEP_LEFT, style="red")  # Lewy separator
    row1.append_text(c1r1)
    row1.append_text(c2r1)
    row1.append_text(c3r1)
    row1.append_text(c4r1)
    if branch:
        row1.append(SEP_END, style="blue")  # Prawy separator

    # Row 2
    row2 = Text()
    row2.append(SEP_LEFT, style="red")  # Lewy separator
    row2.append_text(c1r2)
    row2.append_text(c2r2)
    row2.append_text(c3r2)
    row2.append_text(c4r2)
    if stats:
        row2.append(SEP_END, style="blue")  # Prawy separator

    # Print
    with console.capture() as capture:
        console.print(row1)
        console.print(row2, end='')

    print(capture.get(), end='')

if __name__ == '__main__':
    main()
