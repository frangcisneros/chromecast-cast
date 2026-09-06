"""HTTP serving: direct files with Range/CORS + live ffmpeg transcode."""

from __future__ import annotations

import contextlib
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

CHUNK = 1024 * 256

_tlock = threading.Lock()
_transcode: dict = {}


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    if not header or not header.startswith("bytes="):
        return None
    try:
        first, _, last = header[len("bytes=") :].partition("-")
        start = int(first) if first else 0
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if start >= size:
        return None
    return start, min(end, size - 1)


def file_chunks(path: Path, start: int, end: int) -> Iterator[bytes]:
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = f.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def ffmpeg_cmd(path: Path, start: float, mode: str = "transcode") -> list[str]:
    base = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(max(0.0, float(start))),
        "-i",
        str(path),
    ]
    if mode == "remux":
        video_args = ["-c:v", "copy"]
    else:
        video_args = [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-profile:v",
            "high",
            "-level",
            "4.0",
            "-pix_fmt",
            "yuv420p",
        ]
    return (
        base
        + video_args
        + [
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ac",
            "2",
            "-movflags",
            "frag_keyframe+empty_moov+default_base_moof",
            "-f",
            "mp4",
            "pipe:1",
        ]
    )


def transcode_start(media_id: str, path: Path, start: float = 0, mode: str = "transcode") -> None:
    transcode_stop()
    proc = subprocess.Popen(
        ffmpeg_cmd(path, start, mode),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    with _tlock:
        _transcode.update(
            {"media_id": media_id, "process": proc, "start": float(start), "mode": mode}
        )


def transcode_stop() -> None:
    with _tlock:
        proc = _transcode.pop("process", None)
        _transcode.pop("media_id", None)
    if proc is not None:
        with contextlib.suppress(OSError):
            proc.kill()
        with contextlib.suppress(subprocess.SubprocessError):
            proc.wait(timeout=5)


def transcode_chunks() -> Iterator[bytes]:
    with _tlock:
        proc = _transcode.get("process")
    if proc is None or proc.stdout is None:
        return
    while True:
        data = proc.stdout.read(CHUNK)
        if not data:
            break
        yield data


def transcode_active() -> bool:
    with _tlock:
        proc = _transcode.get("process")
    return proc is not None and proc.poll() is None
