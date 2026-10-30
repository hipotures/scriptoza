#!/usr/bin/env python3
"""Play a sound whenever YubiKey touch waiting starts or stops.

Note: a waiting-stopped event is NOT proof of successful authentication.
"""

import os
import socket
import subprocess
import time
from pathlib import Path

SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "yubikey-touch-detector.socket"
SOUND_DIR = Path.home() / ".local/share/sounds"
SOUNDS = {
    "1": SOUND_DIR / "universfield-new-notification-066-494545.mp3",
    "0": SOUND_DIR / "universfield-new-notification-064-494547.mp3",
}
REASONS = {"U2F", "GPG", "MAC"}


def handle_event(raw_event: bytes) -> None:
    """Process one fixed-width, five-byte detector event."""
    event = raw_event.decode("ascii", errors="replace")
    reason, separator, state = event.partition("_")
    if reason not in REASONS or separator != "_" or state not in ("0", "1"):
        print(f"Unknown detector event: {event!r}", flush=True)
        return

    if state == "1":
        print(f"Touch requested: {event}", flush=True)
    else:
        print(f"Touch waiting ended (not verified success): {event}", flush=True)

    sound = SOUNDS[state]
    if not sound.is_file():
        print(f"Sound file not found: {sound}", flush=True)
        return
    try:
        subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-volume", "15", str(sound)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        print(f"Sound playback failed: {error}", flush=True)


def main() -> None:
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.connect(str(SOCKET_PATH))
                print(f"Connected to YubiKey touch detector: {SOCKET_PATH}", flush=True)
                buffer = b""
                while True:
                    chunk = stream.recv(4096)
                    if not chunk:
                        print("Detector connection closed; reconnecting", flush=True)
                        break
                    buffer += chunk
                    while len(buffer) >= 5:
                        handle_event(buffer[:5])
                        buffer = buffer[5:]
        except (OSError, ConnectionError) as error:
            print(f"Detector not available: {error}", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
