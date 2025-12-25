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

        stats = ''
        if diff_output:
            ins = 0
            dels = 0
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

    # Build status line with Rich formatting (2 lines)
    console = Console()

    # LINE 1: Model + CWD
    line1 = []
    line1.append(f"[white on red] Model: {model} [/]")
    line1.append("[red on black]▶[/]")
    line1.append(f"[white on black] cwd: {cwd_short} [/]")

    # LINE 2: Context + Output + Git
    line2 = []

    # Context and Output section (yellow background)
    yellow_parts = []
    if ctx_text:
        yellow_parts.append(f" {ctx_text} ")
    if out_text:
        yellow_parts.append(f" {out_text} ")

    if yellow_parts:
        line2.append(f"[black on yellow]{''.join(yellow_parts)}[/]")

    # Git section (blue background)
    if branch or stats:
        line2.append("[yellow on blue]▶[/]")
        blue_parts = []
        if branch:
            blue_parts.append(f" {branch} ")
        if stats:
            blue_parts.append(f" {stats} ")
        line2.append(f"[white on blue]{''.join(blue_parts)}[/]")

    # Print both lines
    with console.capture() as capture:
        console.print(''.join(line1))
        console.print(''.join(line2), end='')

    # Output the captured text
    print(capture.get(), end='')

if __name__ == '__main__':
    main()
