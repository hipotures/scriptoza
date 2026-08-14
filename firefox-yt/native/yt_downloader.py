#!/usr/bin/env python3

import datetime
import json
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys


CONFIG_PATH = Path.home() / ".config" / "firefox-yt-downloader" / "config"
LOG_PATH = Path.home() / ".local" / "state" / "firefox-yt-downloader" / "error.log"


def log_error(message):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            timestamp = datetime.datetime.now().isoformat(timespec="seconds")
            log_file.write(f"{timestamp} {message}\n")
    except OSError:
        pass


def read_exact(size):
    chunks = []
    remaining = size
    while remaining:
        chunk = sys.stdin.buffer.read(remaining)
        if not chunk:
            raise ValueError("Unexpected end of native messaging input")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message():
    length_bytes = sys.stdin.buffer.read(4)
    if not length_bytes:
        return None
    if len(length_bytes) != 4:
        raise ValueError("Invalid native messaging length prefix")
    message_length = struct.unpack("=I", length_bytes)[0]
    payload = read_exact(message_length)
    return json.loads(payload.decode("utf-8"))


def send_message(message):
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def load_config():
    try:
        lines = [line.strip() for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as error:
        raise RuntimeError(f"Cannot read configuration file {CONFIG_PATH}: {error}") from error

    config = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or key not in {"DOWNLOAD_DIR", "YTDLP_ARGS"} or key in config:
            raise RuntimeError(f"Configuration file contains an invalid line: {CONFIG_PATH}")
        config[key] = value.strip()

    if "DOWNLOAD_DIR" not in config:
        raise RuntimeError(f"Configuration file must contain a DOWNLOAD_DIR= line: {CONFIG_PATH}")

    download_dir = Path(config["DOWNLOAD_DIR"])
    if not download_dir.is_absolute():
        raise RuntimeError("DOWNLOAD_DIR in the configuration must be an absolute path")

    try:
        yt_dlp_args = shlex.split(config.get("YTDLP_ARGS", ""))
    except ValueError as error:
        raise RuntimeError(f"YTDLP_ARGS has invalid quoting: {CONFIG_PATH}") from error
    return download_dir, yt_dlp_args


def start_download(message):
    if not isinstance(message, dict):
        raise ValueError("The native message must be a JSON object")

    url = message.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("The URL must start with http:// or https://")

    yt_dlp = shutil.which("yt-dlp")
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed or is not on PATH")

    download_path, yt_dlp_args = load_config()
    download_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_template = str(download_path / f"{timestamp}.%(ext)s")
    subprocess.Popen(
        [yt_dlp, *yt_dlp_args, url, "-o", output_template],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    return {"status": "started", "output": output_template}


def main():
    while True:
        try:
            message = read_message()
            if message is None:
                return
            response = start_download(message)
        except Exception as error:
            log_error(str(error))
            response = {"status": "error", "error": str(error)}

        try:
            send_message(response)
        except Exception as error:
            log_error(str(error))
            return


if __name__ == "__main__":
    main()
