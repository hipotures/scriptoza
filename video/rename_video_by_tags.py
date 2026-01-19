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

import yaml
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Confirm

# =============================================================================
# STRUKTURY DANYCH
# =============================================================================

@dataclass
class Decision:
    should_rename: bool
    reasons: List[str]
    debug_kv: List[Tuple[str, Any]]


# =============================================================================
# FUNKCJE POMOCNICZE
# =============================================================================

def is_set_value(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, dict, tuple, set)):
        return len(v) > 0
    return True


def load_all_presets() -> Tuple[Dict[str, Any], Optional[str]]:
    """Ładuje konfigurację presetów z YAML."""
    search_paths = [
        Path("rename_video.yaml"),
        Path(sys.argv[0]).parent / "rename_video.yaml",
        Path.home() / ".config" / "scriptoza" / "rename_video.yaml",
    ]

    config_path = None
    for p in search_paths:
        if p.exists():
            config_path = p
            break

    if not config_path:
        return {}, f"Plik konfiguracji nie został znaleziony w: {[str(p) for p in search_paths]}"

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        if not config or "presets" not in config:
            return {}, f"Nieprawidłowa struktura YAML w {config_path} (brak klucza 'presets')"
        
        return config["presets"], None
    except Exception as e:
        return {}, f"Błąd odczytu {config_path}: {e!r}"


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


def evaluate_tags_for_preset(meta: Dict[str, Any], name: str, preset_config: Dict[str, Any]) -> Decision:
    """Ocenia czy dany plik spełnia reguły konkretnego presetu."""
    reasons: List[str] = []
    debug_kv: List[Tuple[str, Any]] = []
    
    rules = preset_config.get("rules", {})
    require = rules.get("require", {})
    exclude = rules.get("exclude", {})

    # 1. EXCLUDE (OR - jakikolwiek blokuje)
    # Sprawdzenie samej obecności kluczy
    for key in exclude.get("keys", []):
        if key in meta and is_set_value(meta.get(key)):
            v = meta.get(key)
            reasons.append(f"EXCLUDE key present: {key}={v!r}")
            debug_kv.append((key, v))
            return Decision(False, reasons, debug_kv)
    
    # Sprawdzenie wartości (regex)
    for key, pattern in exclude.get("matches", {}).items():
        if key in meta and is_set_value(meta.get(key)):
            v = meta.get(key)
            if re.search(str(pattern), str(v), flags=re.IGNORECASE):
                reasons.append(f"EXCLUDE value match: {key}={v!r} ~ /{pattern}/i")
                debug_kv.append((key, v))
                return Decision(False, reasons, debug_kv)

    # 2. REQUIRE (AND - wszystkie muszą być spełnione)
    # Sprawdzenie obecności kluczy
    for key in require.get("keys", []):
        if key not in meta or not is_set_value(meta.get(key)):
            reasons.append(f"REQUIRE key missing/unset: {key}")
            debug_kv.append((key, meta.get(key, None)))
            return Decision(False, reasons, debug_kv)
        debug_kv.append((key, meta.get(key)))

    # Sprawdzenie wartości (regex)
    for key, pattern in require.get("matches", {}).items():
        if key not in meta or not is_set_value(meta.get(key)):
            reasons.append(f"REQUIRE value missing/unset: {key} ~ /{pattern}/i")
            debug_kv.append((key, meta.get(key, None)))
            return Decision(False, reasons, debug_kv)

        v = meta.get(key)
        if not re.search(str(pattern), str(v), flags=re.IGNORECASE):
            reasons.append(f"REQUIRE value no match: {key}={v!r} !~ /{pattern}/i")
            debug_kv.append((key, v))
            return Decision(False, reasons, debug_kv)
        debug_kv.append((key, v))

    reasons.append(f"Preset '{name}' conditions satisfied.")
    return Decision(True, reasons, debug_kv)


def get_current_suffix(path: Path, all_presets: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """
    Sprawdza czy plik ma już przypisany którykolwiek ze znanych suffixów.
    Zwraca krotkę (delimiter, suffix) jeśli znaleziono, w przeciwnym razie None.
    """
    stem = path.stem.lower()
    # Sortujemy po długości suffixu (malejąco), aby uniknąć błędnych dopasowań (np. _q vs _qvr)
    sorted_presets = sorted(all_presets.items(), key=lambda x: len(x[1].get("suffix", "")), reverse=True)
    
    for _, cfg in sorted_presets:
        s = cfg.get("suffix", "").lower()
        d = cfg.get("delimiter", "_").lower()
        if s and stem.endswith(f"{d}{s}"):
            return cfg.get("delimiter", "_"), cfg.get("suffix", "")
    return None


def build_target_name(path: Path, suffix: str, delim: str, old_suffix_info: Optional[Tuple[str, str]] = None) -> Path:
    """Buduje nową nazwę, opcjonalnie zastępując stary suffix."""
    if old_suffix_info:
        old_delim, old_suf = old_suffix_info
        # Usuwamy stary suffix z końca rdzenia nazwy
        # Używamy re.escape dla bezpieczeństwa, choć suffixy to zwykle alfanumeryki
        pattern = re.escape(f"{old_delim}{old_suf}") + "$"
        new_stem = re.sub(pattern, "", path.stem, flags=re.IGNORECASE)
        return path.with_name(f"{new_stem}{delim}{suffix}{path.suffix}")
    
    return path.with_name(f"{path.stem}{delim}{suffix}{path.suffix}")


def iter_mp4_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".mp4"]


def safe_rename_no_overwrite(src: Path, dst: Path) -> Tuple[bool, Optional[str]]:
    try:
        if not src.exists():
            return False, "source disappeared before rename"
        if dst.exists():
            return False, "target already exists"

        os.link(src, dst)
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


def build_epilog(all_presets: Optional[Dict[str, Any]] = None) -> str:
    preset_info = ""
    if all_presets:
        preset_info = "\nDostępne presety (YAML):\n"
        for name, cfg in all_presets.items():
            desc = cfg.get("description", "(brak opisu)")
            suf = cfg.get("suffix", "??")
            delim = cfg.get("delimiter", "_")
            preset_info += f"  - {name}: {desc} (suffix: {delim}{suf})\n"
    
    return f"""\nOpis działania:
- Skrypt skanuje rekursywnie katalog bieżący (.) i wszystkie podkatalogi w poszukiwaniu plików *.mp4 (case-insensitive).
- Dla każdego pliku uruchamia: exiftool -json <plik> i dopasowuje pierwszy pasujący preset z YAML.

Logika presetów (kaskada):
- Skrypt sprawdza presety w kolejności ich wystąpienia w pliku YAML.
- Zastosowany zostanie PIERWSZY preset, którego warunki 'require' są spełnione i 'exclude' nie są spełnione.
{preset_info}Zmiana nazwy:
- Dokleja <delim><suffix> tuż przed prawdziwym rozszerzeniem, zachowując oryginalny case rozszerzenia.
- Nigdy nie nadpisuje istniejących plików: konflikt jest raportowany i plik jest pomijany.
- --dry-run: nie wykonuje zmian, tylko wypisuje co BY zrobił.
"""


# =============================================================================
# MAIN
# =============================================================================

def main(argv: List[str]) -> int:
    # 1. Wstępne ładowanie konfiguracji dla pomocy --help
    all_presets, config_err = load_all_presets()
    
    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name,
        description="Bezpiecznie dopisuje suffix do nazw MP4 na podstawie metadanych exiftool i reguł z pliku YAML.",
        epilog=build_epilog(all_presets),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--debug", action="store_true", help="Wypisz szczegóły decyzji dla każdego pliku")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout dla exiftool (domyślnie: 30s)")
    parser.add_argument("--dry-run", action="store_true", help="Tylko pokaż co zostanie zmienione")
    parser.add_argument("--scan", action="store_true", help="Uruchom bez pytania o potwierdzenie")
    parser.add_argument("--force", action="store_true", help="Wymuś zmianę nawet jeśli plik ma już znany suffix (pozwala na zmianę profilu)")

    args = parser.parse_args(argv)
    console = Console()

    if config_err:
        console.print(f"[red]Błąd konfiguracji:[/red] {config_err}")
        return 1
    if not all_presets:
        console.print(f"[red]Błąd: Nie znaleziono żadnych presetów w konfiguracji.[/red]")
        return 1

    if not args.scan and not argv:
        if not Confirm.ask("Nie podano argumentów. Czy skanować bieżący katalog?", default=False):
            console.print("[yellow]Anulowano.[/yellow]")
            return 0

    root = Path(".").resolve()
    files = iter_mp4_files(root)

    stats = {
        "scanned": 0,
        "renamed": 0,
        "would_rename": 0,
        "conflicts": 0,
        "skipped_already_suffixed": 0,
        "skipped_no_match": 0,
        "errors_exiftool": 0,
        "errors_rename": 0,
        "presets_matched": {},  # Nowy licznik: {preset_name: count}
    }

    if not files:
        console.print("[yellow]Nie znaleziono plików .mp4.[/yellow]")
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
        task = progress.add_task("Analizowanie plików", total=len(files))

        for path in files:
            stats["scanned"] += 1

            meta, exif_err = run_exiftool_json(path, timeout_s=args.timeout)
            if exif_err is not None or meta is None:
                stats["errors_exiftool"] += 1
                if args.debug:
                    console.print(f"\n[bold]{path}[/bold] [red]EXIFTOOL ERROR:[/red] {exif_err}")
                progress.advance(task)
                continue

            matched_preset_name = None
            final_decision = None
            
            # Kaskada presetów
            for preset_name, preset_rules in all_presets.items():
                decision = evaluate_tags_for_preset(meta, preset_name, preset_rules)

                if args.debug:
                    console.print(f"\n[bold]{path}[/bold] (Preset: [cyan]{preset_name}[/cyan])")
                    for k, v in decision.debug_kv:
                        console.print(f"    {k}: {v!r}")
                    for r in decision.reasons:
                        status_color = "green" if decision.should_rename else "yellow"
                        console.print(f"    - [{status_color}]{r}[/{status_color}]")

                if decision.should_rename:
                    matched_preset_name = preset_name
                    final_decision = decision
                    # Zliczanie dopasowania
                    stats["presets_matched"][preset_name] = stats["presets_matched"].get(preset_name, 0) + 1
                    break

            if not final_decision or not final_decision.should_rename:
                stats["skipped_no_match"] += 1
                progress.advance(task)
                continue

            # Pobranie parametrów z pasującego presetu
            preset_cfg = all_presets[matched_preset_name]
            suffix = preset_cfg.get("suffix", "")
            delimiter = preset_cfg.get("delimiter", "_")

            # Inteligentne sprawdzenie istniejącego suffixu
            old_suffix_info = get_current_suffix(path, all_presets)
            
            if old_suffix_info:
                old_delim, old_suf = old_suffix_info
                # Jeśli ma już ten sam suffix - zawsze pomijamy
                if old_suf.lower() == suffix.lower() and old_delim == delimiter:
                    stats["skipped_already_suffixed"] += 1
                    progress.advance(task)
                    continue
                
                # Jeśli ma INNY znany suffix i NIE ma --force - pomijamy (nowe domyślne zachowanie)
                if not args.force:
                    stats["skipped_already_suffixed"] += 1
                    if args.debug:
                        console.print(f"  [yellow]SKIP[/yellow] plik ma już suffix {old_delim}{old_suf} (użyj --force aby zmienić)")
                    progress.advance(task)
                    continue
                
                # Jeśli jest --force i inny suffix - będziemy go zastępować

            target = build_target_name(path, suffix, delimiter, old_suffix_info)

            if target.exists():
                stats["conflicts"] += 1
                console.print(f"[yellow]KONFLIKT NAZWY[/yellow] {path.name} -> {target.name} (cel istnieje)")
                progress.advance(task)
                continue

            if args.dry_run:
                stats["would_rename"] += 1
                action = "replace suffix" if old_suffix_info else "rename"
                console.print(f"[cyan]DRY-RUN[/cyan] {action}: {path.name} -> {target.name} (preset: {matched_preset_name})")
            else:
                ok, ren_err = safe_rename_no_overwrite(path, target)
                if ok:
                    stats["renamed"] += 1
                else:
                    stats["errors_rename"] += 1
                    console.print(f"[red]BŁĄD ZMIANY NAZWY[/red] {path.name} -> {target.name}: {ren_err}")

            progress.advance(task)

    console.print("\n[bold]Podsumowanie[/bold]")
    console.print(f"  Przeskanowano: {stats['scanned']}")
    console.print(f"  Zmieniono nazwy: {stats['renamed']}")
    
    if stats["presets_matched"]:
        preset_lines = [f"    - {name}: {count}" for name, count in stats["presets_matched"].items()]
        console.print("  Dopasowane presety:\n" + "\n".join(preset_lines))

    if args.dry_run:
        console.print(f"  Do zmiany (dry-run): {stats['would_rename']}")
    console.print(f"  Konflikty: {stats['conflicts']}")
    console.print(f"  Pominięto (już z suffixem): {stats['skipped_already_suffixed']}")
    console.print(f"  Pominięto (brak dopasowania): {stats['skipped_no_match']}")
    console.print(f"  Błędy exiftool: {stats['errors_exiftool']}")
    console.print(f"  Błędy rename: {stats['errors_rename']}")

    return 0


if __name__ == "__main__":
    console = Console()
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        console.print("\n[yellow]Przerwano przez użytkownika.[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[bold red]Nieoczekiwany błąd:[/bold red] {e!r}")
        import traceback
        traceback.print_exc()
        sys.exit(1)