#!/usr/bin/env python3
"""
Aggregate Claude Code JSONL history into per-session, per-model, per-day token totals.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple


MILLION = 1_000_000


PRICING_USD_PER_M = {
    "sonnet": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "opus_legacy": {
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,
        "cache_read": 1.50,
    },
    "opus_4_5": {
        "input": 5.00,
        "output": 25.00,
        "cache_write": 6.25,
        "cache_read": 0.50,
    },
    "haiku_4_5": {
        "input": 1.00,
        "output": 5.00,
        "cache_write": 1.25,
        "cache_read": 0.10,
    },
    "haiku_legacy": {
        "input": 0.80,
        "output": 4.00,
        "cache_write": 1.00,
        "cache_read": 0.08,
    },
}


@dataclass
class TokenTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    def add(self, input_tokens: int, output_tokens: int, cache_write: int, cache_read: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_write_tokens += cache_write
        self.cache_read_tokens += cache_read


def iter_jsonl_files(root: Path) -> Iterable[Path]:
    if root.is_file() and root.suffix == ".jsonl":
        yield root
        return
    if not root.exists():
        return
    for path in root.rglob("*.jsonl"):
        if path.is_file():
            yield path


def parse_date(value: Any, fallback_date: str) -> str:
    if value is None:
        return fallback_date
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1_000_000_000_000 else value
        try:
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
            return dt.date().isoformat()
        except (OSError, OverflowError, ValueError):
            return fallback_date
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return fallback_date
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.date().isoformat()
    return fallback_date


def int_or_zero(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def cache_write_tokens(usage: Dict[str, Any]) -> int:
    direct = usage.get("cache_creation_input_tokens")
    if isinstance(direct, (int, float)):
        return int(direct)
    cache_creation = usage.get("cache_creation")
    if isinstance(cache_creation, dict):
        total = 0
        for token_count in cache_creation.values():
            total += int_or_zero(token_count)
        return total
    return 0


def cache_read_tokens(usage: Dict[str, Any]) -> int:
    return int_or_zero(usage.get("cache_read_input_tokens"))


def pricing_for_model(model: str) -> Optional[Dict[str, float]]:
    if not model:
        return None
    lowered = model.lower()
    if "sonnet" in lowered:
        return PRICING_USD_PER_M["sonnet"]
    if "opus" in lowered:
        if "4-5" in lowered or "4_5" in lowered or "4.5" in lowered:
            return PRICING_USD_PER_M["opus_4_5"]
        return PRICING_USD_PER_M["opus_legacy"]
    if "haiku" in lowered:
        if "4-5" in lowered or "4_5" in lowered or "4.5" in lowered:
            return PRICING_USD_PER_M["haiku_4_5"]
        return PRICING_USD_PER_M["haiku_legacy"]
    return None


def cost_usd(
    pricing: Optional[Dict[str, float]],
    input_tokens: int,
    output_tokens: int,
    cache_write: int,
    cache_read: int,
) -> Optional[float]:
    if not pricing:
        return None
    return (
        (input_tokens / MILLION) * pricing["input"]
        + (output_tokens / MILLION) * pricing["output"]
        + (cache_write / MILLION) * pricing["cache_write"]
        + (cache_read / MILLION) * pricing["cache_read"]
    )


def collect_totals(root: Path) -> Dict[Tuple[str, str, str], TokenTotals]:
    totals: Dict[Tuple[str, str, str], TokenTotals] = {}
    for path in iter_jsonl_files(root):
        try:
            file_date = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()
        except (OSError, ValueError):
            file_date = "unknown"
        session_id_fallback = path.stem
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = obj.get("message")
                if not isinstance(message, dict):
                    continue
                if message.get("role") != "assistant":
                    continue
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue
                session_id = obj.get("sessionId") or obj.get("session_id") or session_id_fallback
                model = message.get("model") or obj.get("model") or "unknown"
                date = parse_date(obj.get("timestamp"), file_date)
                key = (date, session_id, model)
                input_tokens = int_or_zero(usage.get("input_tokens"))
                output_tokens = int_or_zero(usage.get("output_tokens"))
                cache_write = cache_write_tokens(usage)
                cache_read = cache_read_tokens(usage)
                totals.setdefault(key, TokenTotals()).add(input_tokens, output_tokens, cache_write, cache_read)
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize Claude Code JSONL history by session, model, and day.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("~/.claude/projects").expanduser(),
        help="Root directory with Claude Code project JSONL files.",
    )
    parser.add_argument(
        "--format",
        choices=("csv", "tsv"),
        default="csv",
        help="Output format.",
    )
    parser.add_argument(
        "--include-cost",
        action="store_true",
        help="Include estimated cost based on hardcoded pricing.",
    )
    args = parser.parse_args()

    root = args.root.expanduser()
    totals = collect_totals(root)
    delimiter = "," if args.format == "csv" else "\t"
    writer = csv.writer(sys.stdout, delimiter=delimiter)

    headers = [
        "date",
        "session_id",
        "model",
        "input_tokens",
        "output_tokens",
        "cache_write_tokens",
        "cache_read_tokens",
    ]
    if args.include_cost:
        headers.append("cost_usd")

    writer.writerow(headers)

    def sort_key(item: Tuple[Tuple[str, str, str], TokenTotals]) -> Tuple[int, str, str, str]:
        date, session_id, model = item[0]
        return (1 if date == "unknown" else 0, date, session_id, model)

    for (date, session_id, model), total in sorted(totals.items(), key=sort_key):
        if (
            total.input_tokens == 0
            and total.output_tokens == 0
            and total.cache_write_tokens == 0
            and total.cache_read_tokens == 0
        ):
            continue
        row = [
            date,
            session_id,
            model,
            total.input_tokens,
            total.output_tokens,
            total.cache_write_tokens,
            total.cache_read_tokens,
        ]
        if args.include_cost:
            pricing = pricing_for_model(model)
            cost = cost_usd(
                pricing,
                total.input_tokens,
                total.output_tokens,
                total.cache_write_tokens,
                total.cache_read_tokens,
            )
            row.append("" if cost is None else f"{cost:.6f}")
        writer.writerow(row)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
