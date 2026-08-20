#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "opencv-python>=4.8",
#     "requests>=2.31",
#     "rich>=13",
# ]
# ///

import base64
import os
import re
from collections import Counter
from datetime import datetime

import cv2
import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)


HOST = "192.168.100.107"
PORT = 8080
MODEL = "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL"
BASE_URL = f"http://{HOST}:{PORT}/v1/chat/completions"
TIMEOUT = 180
IMAGE_WIDTH = 512
MAX_TOKENS = 32
LOG_FILE = "/tmp/video_rotation_detector.log"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}

PROMPT = """
Look at this video frame and determine its visual orientation.

Your task is to determine what CLOCKWISE rotation must be applied to the
raw image so that the scene appears naturally upright.

Return exactly ONE of these values:

0
90
180
270
-1

Meaning:

0   = the image is already upright
90  = rotate image 90 degrees clockwise
180 = rotate image 180 degrees
270 = rotate image 270 degrees clockwise
-1  = impossible to determine orientation from this image

Use visual clues such as:
- people should stand upright
- faces should be upright
- buildings should be vertical
- text should be readable normally
- ground should be below the sky
- furniture and objects should obey gravity

Even if there are no people, infer orientation from the whole scene.

Do NOT explain your answer.
Do NOT output words.
Output exactly one number.
"""

LOG_HANDLE = None
CONSOLE = Console(stderr=True)


class OllamaConnectionError(RuntimeError):
    pass


def log(message=""):
    CONSOLE.print(message, markup=False)
    if LOG_HANDLE is not None:
        print(message, file=LOG_HANDLE)
        LOG_HANDLE.flush()


def log_rule(title, style="cyan"):
    CONSOLE.rule(title, style=style, align="left")
    if LOG_HANDLE is not None:
        print(title, file=LOG_HANDLE)
        LOG_HANDLE.flush()


def frame_to_base64(frame):
    height, width = frame.shape[:2]
    resized_height = max(1, int(height * IMAGE_WIDTH / width))
    frame = cv2.resize(
        frame,
        (IMAGE_WIDTH, resized_height),
        interpolation=cv2.INTER_AREA,
    )
    log(f"  sending to AI: {frame.shape[1]}x{frame.shape[0]}")
    encoded, buffer = cv2.imencode(
        ".jpg",
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, 90],
    )
    if not encoded:
        raise RuntimeError("JPEG encoding failed")
    return base64.b64encode(buffer).decode("ascii")


def ask_rotation(frame, session, label):
    payload = {
        "model": MODEL,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                "data:image/jpeg;base64,"
                                + frame_to_base64(frame)
                            )
                        },
                    },
                ],
            }
        ],
    }

    try:
        response = session.post(
            BASE_URL,
            json=payload,
            timeout=TIMEOUT,
        )
    except (requests.ConnectionError, requests.Timeout) as error:
        raise OllamaConnectionError from error

    response.raise_for_status()
    data = response.json()

    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        log(f"  [{label}] unexpected API response: {data!r}")
        return -1

    content = message.get("content") or ""
    reasoning = (
        message.get("reasoning_content")
        or message.get("reasoning")
        or ""
    )
    log(f"  [{label}] content={content!r}")
    if reasoning:
        log(f"  [{label}] reasoning={reasoning!r}")

    content = str(content).strip()
    valid_answers = {"-1", "0", "90", "180", "270"}
    if content in valid_answers:
        return int(content)

    matches = re.findall(
        r"(?<!\d)(?:-1|270|180|90|0)(?!\d)",
        content,
    )
    if matches:
        rotation = int(matches[-1])
        log(f"  [{label}] parsed={rotation}")
        return rotation

    log(f"  [{label}] could not parse answer")
    return -1


def sample_frames(path):
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        return None

    capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
    orientation_meta = capture.get(cv2.CAP_PROP_ORIENTATION_META)
    orientation_auto = capture.get(cv2.CAP_PROP_ORIENTATION_AUTO)
    frame_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    log(
        f"  orientation_meta={orientation_meta} "
        f"orientation_auto={orientation_auto} "
        f"size={frame_width}x{frame_height} "
        f"frames={frame_count}"
    )

    if frame_count <= 0:
        capture.release()
        return None

    frames = []
    for fraction in (0.15, 0.325, 0.50, 0.675, 0.85):
        frame_number = int((frame_count - 1) * fraction)
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        succeeded, frame = capture.read()
        if succeeded and frame is not None:
            log(
                f"  frame {fraction:.1%}: "
                f"{frame.shape[1]}x{frame.shape[0]} "
                f"frame_no={frame_number}"
            )
            frames.append((fraction, frame))
        else:
            log(f"  frame {fraction:.1%}: READ FAILED")

    capture.release()
    return frames or None


def analyze(path, session):
    frames = sample_frames(path)
    if not frames:
        log("  ! could not read frames")
        return None

    votes = []
    for index, (fraction, frame) in enumerate(frames, 1):
        label = f"{index}/{len(frames)} {fraction:.1%}"
        try:
            rotation = ask_rotation(frame, session, label)
        except OllamaConnectionError:
            raise
        except requests.RequestException as error:
            log(f"  [{label}] API ERROR: {error}")
            rotation = -1
        except (ValueError, TypeError) as error:
            log(f"  [{label}] invalid API response: {error}")
            rotation = -1
        votes.append(rotation)

    log(f"  votes: {votes}")
    valid_votes = [
        vote for vote in votes if vote in (0, 90, 180, 270)
    ]
    if not valid_votes:
        log("  no valid rotation votes")
        return None

    counts = Counter(valid_votes)
    rotation, count = counts.most_common(1)[0]
    log(f"  valid votes: {dict(counts)}, winner={rotation}")
    if count < 2:
        log("  insufficient agreement")
        return None

    tied = [
        candidate
        for candidate, candidate_count in counts.items()
        if candidate_count == count
    ]
    if len(tied) != 1:
        log(f"  ambiguous tie: {tied}")
        return None

    return rotation


def rotation_path(video_path):
    base, _ = os.path.splitext(video_path)
    return base + ".rot"


def write_rotation_file(video_path, rotation):
    path = rotation_path(video_path)
    with open(path, "w", encoding="utf-8") as file:
        file.write(f"--video-rotate={rotation}\n")
    return path


def main():
    global LOG_HANDLE

    LOG_HANDLE = open(
        LOG_FILE,
        "a",
        encoding="utf-8",
        buffering=1,
    )
    session = requests.Session()

    try:
        log("")
        log_rule("video-rotation-detector")
        log(
            "video-rotation-detector started: "
            f"{datetime.now().isoformat(timespec='seconds')}"
        )
        log(f"model: {MODEL}")
        log(f"server: {BASE_URL}")
        log(f"image width sent to AI: {IMAGE_WIDTH}")
        log(f"log: {LOG_FILE}")
        log("")

        files = sorted(
            filename
            for filename in os.listdir(".")
            if (
                os.path.isfile(filename)
                and os.path.splitext(filename)[1].lower()
                in VIDEO_EXTENSIONS
            )
        )
        if not files:
            log("No video files found.")
            return 0

        had_failures = False
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=CONSOLE,
            expand=False,
        ) as progress:
            task = progress.add_task(
                "Analyzing videos".ljust(25),
                total=len(files),
            )

            for filename in files:
                sidecar_path = rotation_path(filename)
                log("")
                log_rule(filename, style="blue")

                if os.path.exists(sidecar_path):
                    try:
                        with open(
                            sidecar_path,
                            "r",
                            encoding="utf-8",
                        ) as file:
                            existing = file.read().strip()
                    except OSError as error:
                        existing = f"<could not read: {error}>"
                    log(
                        "  SKIP: sidecar already exists: "
                        f"{sidecar_path}"
                    )
                    log(f"  existing value: {existing}")
                    progress.advance(task)
                    continue

                try:
                    rotation = analyze(filename, session)
                except OllamaConnectionError:
                    log(
                        "ERROR: Could not connect to the Ollama "
                        f"server at {BASE_URL}. The server did not "
                        "respond."
                    )
                    return 2

                if rotation is None:
                    log("  NO RESULT: .rot file was not created")
                    had_failures = True
                    progress.advance(task)
                    continue

                try:
                    created = write_rotation_file(
                        filename,
                        rotation,
                    )
                except OSError as error:
                    log(f"  could not create .rot file: {error}")
                    had_failures = True
                    progress.advance(task)
                    continue

                log(f"  RESULT: --video-rotate={rotation}")
                log(f"  CREATED: {created}")
                progress.advance(task)

        log("")
        log(
            "video-rotation-detector finished: "
            f"{datetime.now().isoformat(timespec='seconds')}"
        )
        return 1 if had_failures else 0
    finally:
        session.close()
        LOG_HANDLE.close()
        LOG_HANDLE = None


if __name__ == "__main__":
    raise SystemExit(main())
