"""Media discovery + ffprobe capability check.

Chromecast Gen 1/2 plays natively: H.264 (<= High L4.1) / VP8 video in
MP4/WebM with AAC/MP3 audio. Anything else goes through ffmpeg transcode.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from castlocal import config

DIRECT_VIDEO = {"h264", "avc", "vp8"}
DIRECT_AUDIO = {"aac", "mp3", "vorbis", "opus", "flac", "wav", "mp4a"}
DIRECT_MP4_EXTS = {".mp4", ".m4v", ".mov"}


@dataclass
class VideoFile:
    id: str
    name: str
    path: Path
    size: int
    mtime: float

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()


def file_id(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:16]


def scan() -> list[VideoFile]:
    found: list[VideoFile] = []
    for root in config.default_media_dirs():
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in config.VIDEO_EXTS:
                continue
            if path.stat().st_size < 1024 * 1024:
                continue
            st = path.stat()
            found.append(
                VideoFile(
                    id=file_id(path),
                    name=path.name,
                    path=path,
                    size=st.st_size,
                    mtime=st.st_mtime,
                )
            )
    found.sort(key=lambda v: v.mtime, reverse=True)
    return found


def probe(path: Path) -> dict:
    """Return ffprobe streams/format dict; empty dict on failure."""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}


def _streams(info: dict) -> tuple[str, str]:
    vcodec, acodec = "", ""
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and not vcodec:
            vcodec = str(s.get("codec_name", "")).lower()
        elif s.get("codec_type") == "audio" and not acodec:
            acodec = str(s.get("codec_name", "")).lower()
    return vcodec, acodec


def video_props(info: dict) -> tuple[str, float | None]:
    """Return (vcodec, level) e.g. ('h264', 4.1); level None if unknown."""
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            vcodec = str(s.get("codec_name", "")).lower()
            try:
                level = int(str(s.get("level", ""))) / 10
            except (ValueError, TypeError):
                level = None
            return vcodec, level
    return "", None


def audio_props(info: dict) -> tuple[str, int]:
    """Return (acodec, channels); channels 0 if unknown."""
    for s in info.get("streams", []):
        if s.get("codec_type") == "audio":
            acodec = str(s.get("codec_name", "")).lower()
            try:
                channels = int(str(s.get("channels", "0")))
            except (ValueError, TypeError):
                channels = 0
            return acodec, channels
    return "", 0


def decide(path: Path, info: dict | None = None) -> tuple[str, str]:
    """Return (mode, mime).

    Modes: 'direct' (as-is), 'remux' (copy video, AAC stereo audio),
    'transcode' (full H264 L4.0 + AAC stereo re-encode for Gen 1).
    """
    suffix = path.suffix.lower()
    if suffix == ".webm":
        info = info if info is not None else probe(path)
        vcodec, acodec = _streams(info)
        if vcodec in {"vp8", "vp9"} and (not acodec or acodec in DIRECT_AUDIO):
            return "direct", "video/webm"
        return "transcode", "video/mp4"
    if suffix not in DIRECT_MP4_EXTS:
        return "transcode", "video/mp4"
    info = info if info is not None else probe(path)
    if not info:
        # Unprobable MP4: try direct, Chromecast will error visibly if wrong.
        return "direct", "video/mp4"
    vcodec, level = video_props(info)
    acodec, channels = audio_props(info)
    video_ok = vcodec in DIRECT_VIDEO and (level is None or level <= 4.0)
    audio_ok = (not acodec or acodec in DIRECT_AUDIO) and (channels == 0 or channels <= 2)
    if video_ok and audio_ok:
        return "direct", "video/mp4"
    if video_ok:
        return "remux", "video/mp4"
    return "transcode", "video/mp4"


def duration(info: dict) -> float | None:
    try:
        return float(info.get("format", {}).get("duration", ""))
    except (ValueError, TypeError):
        return None
