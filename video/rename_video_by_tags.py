#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

# =============================================================================
# KONFIGURACJA TAGÓW (edytuj tutaj)
# =============================================================================
DEFAULT_SUFFIX = "qvr"
DEFAULT_DELIM = "_"

# Pozytywne warunki - AND (wszystkie aktywne muszą przejść)
POSITIVE_KEYS_REQUIRED: List[str] = [
    "AndroidVersion",
    # "GPSPosition",
]
POSITIVE_VALUE_RULES: List[Tuple[str, str]] = [
    # ("AndroidVersion", r"\b9\b"),
]

# Negatywne warunki - OR (jakikolwiek blokuje)
NEGATIVE_KEYS_PRESENT: List[str] = [
    # "CameraModelName",
]
NEGATIVE_VALUE_RULES: List[Tuple[str, str]] = [
    ("Make", r"panasonic"),
    ("CameraModelName", r"DMC-FZ1000"),
]


# =============================================================================
# IMPLEMENTACJA
# =============================================================================

@dataclass
class Decision:
    should_rename: bool
    reasons: List[str]
    debug_kv: List[Tuple[str, Any]]


def is_set_value(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, dict, tuple, set)):
        return len(v) > 0
    return True


def run_exiftool_json(path: Path, timeout_s: int = 30) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    cmd = ["exiftool", "-json", str(path)]
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return None, "exiftool not found in PATH"
    except subprocess.TimeoutExpired:
        return None, f"exiftool timeout after {timeout_s}s"
    except Exception as e:
        return None, f"exiftool exec error: {e!r}"

    if p.returncode != 0:
        err = (p.stderr or "").strip()
        out = (p.stdout or "").strip()
        msg = err if err else (out[:200] if out else f"exiftool exit code {p.returncode}")
        return None, msg

    try:
        data = json.loads(p.stdout)
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return None, "unexpected exiftool JSON structure"
        return data[0], None
    except json.JSONDecodeError as e:
        return None, f"json decode error: {e}"


def evaluate_tags(meta: Dict[str, Any]) -> Decision:
    reasons: List[str] = []
    debug_kv: List[Tuple[str, Any]] = []

    # NEGATIVE (OR)
    for key in NEGATIVE_KEYS_PRESENT:
        if key in meta and is_set_value(meta.get(key)):
            v = meta.get(key)
            reasons.append(f"NEGATIVE key present: {key}={v!r}")
            debug_kv.append((key, v))
            return Decision(False, reasons, debug_kv)

    for key, pattern in NEGATIVE_VALUE_RULES:
        if key in meta and is_set_value(meta.get(key)):
            v = meta.get(key)
            if re.search(pattern, str(v), flags=re.IGNORECASE):
                reasons.append(f"NEGATIVE value match: {key}={v!r} ~ /{pattern}/i")
                debug_kv.append((key, v))
                return Decision(False, reasons, debug_kv)

    # POSITIVE (AND)
    for key in POSITIVE_KEYS_REQUIRED:
        if key not in meta or not is_set_value(meta.get(key)):
            reasons.append(f"POSITIVE key missing/unset: {key}")
            debug_kv.append((key, meta.get(key, None)))
            return Decision(False, reasons, debug_kv)
        debug_kv.append((key, meta.get(key)))

    for key, pattern in POSITIVE_VALUE_RULES:
        if key not in meta or not is_set_value(meta.get(key)):
            reasons.append(f"POSITIVE value missing/unset: {key} ~ /{pattern}/i")
            debug_kv.append((key, meta.get(key, None)))
            return Decision(False, reasons, debug_kv)

        v = meta.get(key)
        if not re.search(pattern, str(v), flags=re.IGNORECASE):
            reasons.append(f"POSITIVE value no match: {key}={v!r} !~ /{pattern}/i")
            debug_kv.append((key, v))
            return Decision(False, reasons, debug_kv)
        debug_kv.append((key, v))

    reasons.append("All POSITIVE conditions satisfied; no NEGATIVE matched.")
    return Decision(True, reasons, debug_kv)


def build_target_name(path: Path, suffix: str, delim: str) -> Path:
    return path.with_name(f"{path.stem}{delim}{suffix}{path.suffix}")


def already_suffixed(path: Path, suffix: str, delim: str) -> bool:
    return path.stem.lower().endswith(f"{delim}{suffix}".lower())


def iter_mp4_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".mp4"]


def safe_rename_no_overwrite(src: Path, dst: Path) -> Tuple[bool, Optional[str]]:
    """
    Maksymalnie bezpieczne:
      - nigdy nie nadpisuje dst
      - próba jest odporna na wyścigi (EEXIST)
      - jeśli nie można wykonać operacji w pełni, nie usuwa źródła
    Technika: hardlink dst -> src (fail jeśli dst istnieje), potem usuń src.
    """
    try:
        if not src.exists():
            return False, "source disappeared before rename"
        if dst.exists():
            return False, "target already exists"

        os.link(src, dst)  # atomowe "stwórz jeśli nie istnieje"
        try:
            os.unlink(src)
        except Exception as e_unlink:
            try:
                os.unlink(dst)
            except Exception:
                pass
            return False, f"linked but failed to remove source: {e_unlink!r}"

        return True, None

    except FileExistsError:
        return False, "target already exists (race)"
    except OSError as e:
        return False, f"os error: {e.strerror or str(e)}"


def build_epilog() -> str:
    pos_keys = ", ".join(POSITIVE_KEYS_REQUIRED) if POSITIVE_KEYS_REQUIRED else "(brak)"
    pos_vals = ", ".join([f"{k}~/{p}/i" for k, p in POSITIVE_VALUE_RULES]) if POSITIVE_VALUE_RULES else "(brak)"
    neg_keys = ", ".join(NEGATIVE_KEYS_PRESENT) if NEGATIVE_KEYS_PRESENT else "(brak)"
    neg_vals = ", ".join([f"{k}~/{p}/i" for k, p in NEGATIVE_VALUE_RULES]) if NEGATIVE_VALUE_RULES else "(brak)"

    return f"""\
Opis działania:
- Skrypt skanuje rekursywnie katalog bieżący (.) i wszystkie podkatalogi w poszukiwaniu plików *.mp4 (case-insensitive).
- Dla każdego pliku uruchamia: exiftool -json <plik> i podejmuje decyzję o zmianie nazwy na podstawie tagów.

Logika tagów:
- Pozytywne warunki (AND): WSZYSTKIE muszą być spełnione, aby zmienić nazwę.
  * Obecność kluczy (POSITIVE_KEYS_REQUIRED): {pos_keys}
  * Dopasowanie wartości regex (POSITIVE_VALUE_RULES): {pos_vals}
- Negatywne warunki (OR): jeśli JAKIKOLWIEK zadziała, zmiana nazwy jest zablokowana.
  * Obecność kluczy (NEGATIVE_KEYS_PRESENT): {neg_keys}
  * Dopasowanie wartości regex (NEGATIVE_VALUE_RULES): {neg_vals}

Zmiana nazwy:
- Dokleja <delim><suffix> tuż przed prawdziwym rozszerzeniem, zachowując oryginalny case rozszerzenia.
- Nigdy nie nadpisuje istniejących plików: konflikt jest raportowany i plik jest pomijany.
- --dry-run: nie wykonuje zmian, tylko wypisuje co BY zrobił.

Konfiguracja tagów:
- Edytuj listy POSITIVE_* i NEGATIVE_* na początku pliku (możesz komentować linie, aby wyłączyć warunki).
"""


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name,
        description="Bezpiecznie dopisuje suffix do nazw MP4 wykrytych jako nagrania z telefonu na podstawie metadanych exiftool.",
        epilog=build_epilog(),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--suffix", default=DEFAULT_SUFFIX, help=f"Suffix bez separatora (domyślnie: {DEFAULT_SUFFIX})")
    parser.add_argument("--delim", default=DEFAULT_DELIM, help=f"Separator przed suffixem (domyślnie: {DEFAULT_DELIM!r})")
    parser.add_argument("--debug", action="store_true", help="Wypisz tagi i powody, które wpłynęły na decyzję (dla każdego pliku)")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout dla exiftool per plik w sekundach (domyślnie: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Nie zmieniaj nazw plików; tylko pokaż planowane operacje")

    args = parser.parse_args(argv)

    console = Console()
    root = Path(".").resolve()
    files = iter_mp4_files(root)

    stats = {
        "scanned": 0,
        "renamed": 0,
        "would_rename": 0,
        "conflicts": 0,
        "skipped_already_suffixed": 0,
        "skipped_no_match": 0,
        "skipped_negative_block": 0,
        "errors_exiftool": 0,
        "errors_rename": 0,
    }

    if not files:
        console.print("[yellow]No .mp4 files found.[/yellow]")
        return 0

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )

    with progress:
        task = progress.add_task("Analyzing files", total=len(files))

        for path in files:
            stats["scanned"] += 1

            if already_suffixed(path, args.suffix, args.delim):
                stats["skipped_already_suffixed"] += 1
                progress.advance(task)
                continue

            meta, err = run_exiftool_json(path, timeout_s=args.timeout)
            if err is not None or meta is None:
                stats["errors_exiftool"] += 1
                if args.debug:
                    console.print(f"[red]EXIFTOOL ERROR[/red] {path}: {err}")
                progress.advance(task)
                continue

            decision = evaluate_tags(meta)

            if args.debug:
                console.print(f"\n[bold]{path}[/bold]")
                for k, v in decision.debug_kv:
                    console.print(f"  {k}: {v!r}")
                for r in decision.reasons:
                    console.print(f"  - {r}")

            if not decision.should_rename:
                if any(r.startswith("NEGATIVE") for r in decision.reasons):
                    stats["skipped_negative_block"] += 1
                else:
                    stats["skipped_no_match"] += 1
                progress.advance(task)
                continue

            target = build_target_name(path, args.suffix, args.delim)

            if target.exists():
                stats["conflicts"] += 1
                console.print(f"[yellow]NAME CONFLICT[/yellow] {path} -> {target} (target exists; skipping)")
                progress.advance(task)
                continue

            if args.dry_run:
                stats["would_rename"] += 1
                console.print(f"[cyan]DRY-RUN[/cyan] would rename: {path} -> {target}")
                progress.advance(task)
                continue

            ok, ren_err = safe_rename_no_overwrite(path, target)
            if ok:
                stats["renamed"] += 1
                if args.debug:
                    console.print(f"[green]RENAMED[/green] {path.name} -> {target.name}")
            else:
                if ren_err and "target already exists" in ren_err:
                    stats["conflicts"] += 1
                    console.print(f"[yellow]NAME CONFLICT[/yellow] {path} -> {target} ({ren_err})")
                else:
                    stats["errors_rename"] += 1
                    console.print(f"[red]RENAME FAILED[/red] {path} -> {target} ({ren_err})")

            progress.advance(task)

    console.print("\n[bold]Summary[/bold]")
    console.print(f"  Root: {root}")
    console.print(f"  Scanned: {stats['scanned']}")
    console.print(f"  Renamed: {stats['renamed']}")
    if args.dry_run:
        console.print(f"  Would rename: {stats['would_rename']}")
    console.print(f"  Conflicts: {stats['conflicts']}")
    console.print(f"  Skipped (already suffixed): {stats['skipped_already_suffixed']}")
    console.print(f"  Skipped (no match): {stats['skipped_no_match']}")
    console.print(f"  Skipped (negative block): {stats['skipped_negative_block']}")
    console.print(f"  Errors (exiftool): {stats['errors_exiftool']}")
    console.print(f"  Errors (rename): {stats['errors_rename']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

