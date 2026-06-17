#!/usr/bin/env python3
"""Export a MuseScore .mscz file to a tagged MP3 named from workTitle."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


MUSESCORE_PATH_CANDIDATES = (
    "musescore",
    "musescore4",
    "mscore",
    "mscore4",
    "MuseScore-Studio",
)


@dataclass(frozen=True)
class ScoreMetadata:
    work_title: str
    movement_title: str = ""
    composer: str = ""
    copyright: str = ""
    subtitle: str = ""
    alt_titles: str = ""
    mixer_comment: str = ""
    audio_settings_json: str = ""

    @property
    def output_title(self) -> str:
        return self.work_title or self.movement_title

    def ffmpeg_metadata_args(self) -> list[str]:
        args: list[str] = []
        title = self.output_title
        if title:
            args.extend(["-metadata", f"title={title}"])
        if self.composer:
            args.extend(["-metadata", f"artist={self.composer}"])
            args.extend(["-metadata", f"composer={self.composer}"])
        if self.copyright:
            args.extend(["-metadata", f"copyright={self.copyright}"])

        comment_parts = [value for value in (self.subtitle, self.alt_titles, self.mixer_comment) if value]
        if comment_parts:
            args.extend(["-metadata", f"comment={' | '.join(comment_parts)}"])
        if self.audio_settings_json:
            args.extend(["-metadata", f"musescore:audiosettings={self.audio_settings_json}"])
        return args


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _format_number(value: object, *, scale: int = 1) -> str:
    if not isinstance(value, int | float):
        return str(value)
    scaled = value * scale
    rounded = round(scaled)
    if abs(scaled - rounded) < 0.000001:
        return str(rounded)
    return f"{scaled:.2f}".rstrip("0").rstrip(".")


def _instrument_label(instrument_id: object) -> str:
    if not isinstance(instrument_id, str) or not instrument_id:
        return "Track"
    return " ".join(word.capitalize() for word in re.split(r"[_\s-]+", instrument_id) if word)


def _sound_label(track: dict[str, object]) -> str:
    input_settings = track.get("in", {})
    if not isinstance(input_settings, dict):
        return ""
    resource_meta = input_settings.get("resourceMeta", {})
    if not isinstance(resource_meta, dict):
        return ""
    attributes = resource_meta.get("attributes", {})
    if not isinstance(attributes, dict):
        attributes = {}
    for key in ("museName", "presetName", "soundFontName"):
        value = attributes.get(key)
        if isinstance(value, str) and value:
            return value
    value = resource_meta.get("id")
    return value if isinstance(value, str) else ""


def _aux_sends_summary(out_settings: dict[str, object]) -> str:
    aux_sends = out_settings.get("auxSends")
    if not isinstance(aux_sends, list):
        return ""
    values: list[str] = []
    for send in aux_sends:
        if not isinstance(send, dict) or send.get("active") is False:
            continue
        amount = send.get("signalAmount")
        if isinstance(amount, int | float):
            values.append(f"{_format_number(amount, scale=100)}%")
    return ",".join(values)


def _fx_summary(out_settings: dict[str, object]) -> str:
    fx_chain = out_settings.get("fxChain")
    if not isinstance(fx_chain, dict):
        return ""
    names: list[str] = []
    for key in sorted(fx_chain):
        fx = fx_chain[key]
        if not isinstance(fx, dict) or fx.get("active") is False:
            continue
        resource_meta = fx.get("resourceMeta", {})
        if not isinstance(resource_meta, dict):
            continue
        fx_id = resource_meta.get("id")
        if isinstance(fx_id, str) and fx_id:
            names.append(fx_id)
    return ",".join(names)


def _track_summary(track: dict[str, object]) -> str:
    out_settings = track.get("out", {})
    if not isinstance(out_settings, dict):
        out_settings = {}

    parts = [_instrument_label(track.get("instrumentId"))]
    sound = _sound_label(track)
    if sound:
        parts.append(f"sound={sound}")
    if "volumeDb" in out_settings:
        parts.append(f"vol={_format_number(out_settings['volumeDb'])}")
    if "balance" in out_settings:
        parts.append(f"pan={_format_number(out_settings['balance'], scale=100)}")
    aux_sends = _aux_sends_summary(out_settings)
    if aux_sends:
        parts.append(f"aux={aux_sends}")
    return " ".join(parts)


def _aux_summary(aux_settings: dict[str, object], index: int) -> str:
    out_settings = aux_settings.get("out", {})
    if not isinstance(out_settings, dict):
        out_settings = {}

    parts = [f"Aux{index}"]
    if "volumeDb" in out_settings:
        parts.append(f"vol={_format_number(out_settings['volumeDb'])}")
    if "balance" in out_settings:
        parts.append(f"pan={_format_number(out_settings['balance'], scale=100)}")
    fx = _fx_summary(out_settings)
    if fx:
        parts.append(f"fx={fx}")
    return " ".join(parts)


def _master_summary(audio_settings: dict[str, object]) -> str:
    master = audio_settings.get("master")
    if not isinstance(master, dict):
        return ""

    parts = ["Master"]
    if "volumeDb" in master:
        parts.append(f"vol={_format_number(master['volumeDb'])}")
    if "balance" in master:
        parts.append(f"pan={_format_number(master['balance'], scale=100)}")
    fx = _fx_summary(master)
    if fx:
        parts.append(f"fx={fx}")
    return " ".join(parts)


def _mixer_comment(audio_settings: dict[str, object]) -> str:
    summaries: list[str] = []

    tracks = audio_settings.get("tracks")
    if isinstance(tracks, list):
        summaries.extend(_track_summary(track) for track in tracks if isinstance(track, dict))

    aux = audio_settings.get("aux")
    if isinstance(aux, list):
        summaries.extend(
            _aux_summary(aux_settings, index)
            for index, aux_settings in enumerate(aux, start=1)
            if isinstance(aux_settings, dict)
        )

    master = _master_summary(audio_settings)
    if master:
        summaries.append(master)

    return f"MuseScore mixer: {'; '.join(summaries)}" if summaries else ""


def _extract_audio_settings(archive: zipfile.ZipFile) -> tuple[str, str]:
    if "audiosettings.json" not in archive.namelist():
        return "", ""
    audio_settings = json.loads(archive.read("audiosettings.json"))
    if not isinstance(audio_settings, dict):
        return "", ""
    audio_settings_json = json.dumps(audio_settings, ensure_ascii=False, separators=(",", ":"))
    return _mixer_comment(audio_settings), audio_settings_json


def extract_metadata(score_path: Path) -> ScoreMetadata:
    with zipfile.ZipFile(score_path) as archive:
        mscx_names = [name for name in archive.namelist() if name.endswith(".mscx")]
        if len(mscx_names) != 1:
            raise ValueError(f"Expected exactly one .mscx file in {score_path}, found {len(mscx_names)}")
        with archive.open(mscx_names[0]) as score_xml:
            root = ElementTree.parse(score_xml).getroot()
        mixer_comment, audio_settings_json = _extract_audio_settings(archive)

    tags: dict[str, str] = {}
    for tag in root.iter("metaTag"):
        name = tag.attrib.get("name", "")
        if name:
            tags[name] = _clean_text(tag.text)

    return ScoreMetadata(
        work_title=tags.get("workTitle", ""),
        movement_title=tags.get("movementTitle", ""),
        composer=tags.get("composer", ""),
        copyright=tags.get("copyright", ""),
        subtitle=tags.get("subtitle", ""),
        alt_titles=tags.get("Alt Titles", ""),
        mixer_comment=mixer_comment,
        audio_settings_json=audio_settings_json,
    )


def safe_filename(stem: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", stem)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.strip(".")
    if not cleaned:
        raise ValueError("Score has no usable workTitle or movementTitle for MP3 filename")
    return f"{cleaned}.mp3"


def next_available_path(path: Path) -> Path:
    if not path.exists():
        return path

    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def resolve_musescore_bin(explicit: str | None) -> str:
    if explicit:
        return str(Path(explicit).expanduser())
    env_value = os.environ.get("MUSESCORE_BIN")
    if env_value:
        return str(Path(env_value).expanduser())
    for candidate in MUSESCORE_PATH_CANDIDATES:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise FileNotFoundError(
        "MuseScore binary not found. Set MUSESCORE_BIN, pass --musescore-bin, "
        "or install MuseScore so it is available in PATH."
    )


def run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)


def export_with_tags(
    score_path: Path,
    *,
    output_dir: Path | None,
    force: bool,
    musescore_bin: str,
    ffmpeg_bin: str,
) -> Path:
    score_path = score_path.expanduser().resolve()
    if score_path.suffix.lower() != ".mscz":
        raise ValueError("Input must be a .mscz file")
    if not score_path.exists():
        raise FileNotFoundError(score_path)
    musescore_path = Path(musescore_bin).expanduser()
    is_path = "/" in musescore_bin or "\\" in musescore_bin
    if is_path and not musescore_path.exists():
        raise FileNotFoundError(f"MuseScore binary not found: {musescore_path}")
    if not is_path and shutil.which(musescore_bin) is None:
        raise FileNotFoundError(f"MuseScore binary not found in PATH: {musescore_bin}")
    if shutil.which(ffmpeg_bin) is None:
        raise FileNotFoundError(f"ffmpeg binary not found in PATH: {ffmpeg_bin}")

    metadata = extract_metadata(score_path)
    target_dir = (output_dir.expanduser().resolve() if output_dir else score_path.parent)
    target_dir.mkdir(parents=True, exist_ok=True)
    base_output_path = target_dir / safe_filename(metadata.output_title)
    output_path = base_output_path if force else next_available_path(base_output_path)

    temp_handle = tempfile.NamedTemporaryFile(
        prefix=f"{score_path.stem}.",
        suffix=".untagged.mp3",
        dir=target_dir,
        delete=False,
    )
    temp_path = Path(temp_handle.name)
    temp_handle.close()

    tagged_temp = output_path.with_name(f".{output_path.stem}.tagged.tmp.mp3")
    try:
        run_command([str(musescore_path if is_path else musescore_bin), "-o", str(temp_path), str(score_path)])

        ffmpeg_command = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(temp_path),
            "-map",
            "0:a",
            "-codec",
            "copy",
            "-id3v2_version",
            "3",
            *metadata.ffmpeg_metadata_args(),
            str(tagged_temp),
        ]
        run_command(ffmpeg_command)

        if output_path.exists():
            output_path.unlink()
        tagged_temp.replace(output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
        if tagged_temp.exists():
            tagged_temp.unlink()

    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a MuseScore .mscz file to a tagged MP3 named from workTitle."
    )
    parser.add_argument("score", type=Path, help="Path to the .mscz score")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Directory for the final MP3. Defaults to the score directory.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite workTitle.mp3 instead of creating workTitle_1.mp3, workTitle_2.mp3, etc.",
    )
    parser.add_argument(
        "--musescore-bin",
        help="MuseScore binary/AppImage path. Defaults to MUSESCORE_BIN or a MuseScore command in PATH.",
    )
    parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg binary name or path")
    parser.add_argument(
        "--print-mixer-json",
        action="store_true",
        help="Print the full audiosettings.json metadata after export. By default only the readable mixer summary is printed.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        metadata = extract_metadata(args.score)
        output_path = export_with_tags(
            args.score,
            output_dir=args.output_dir,
            force=args.force,
            musescore_bin=resolve_musescore_bin(args.musescore_bin),
            ffmpeg_bin=args.ffmpeg_bin,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(output_path)
    if metadata.mixer_comment:
        print(metadata.mixer_comment)
    if args.print_mixer_json and metadata.audio_settings_json:
        print(f"musescore:audiosettings={metadata.audio_settings_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
