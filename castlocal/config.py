"""Runtime configuration from environment with sane defaults."""

from __future__ import annotations

import os
import socket
from pathlib import Path

CACHE_DIR = Path(os.environ.get("CASTLOCAL_CACHE", str(Path.home() / ".cache" / "castlocal")))
SUBS_CACHE = CACHE_DIR / "subs"
PORT = int(os.environ.get("CASTLOCAL_PORT", "8000"))

VIDEO_EXTS = {
    ".mp4",
    ".m4v",
    ".mkv",
    ".webm",
    ".avi",
    ".mov",
    ".ts",
    ".m2ts",
    ".wmv",
    ".mpg",
    ".mpeg",
}

SUB_EXTS = (".srt", ".vtt")

OPENSUBTITLES_API = "https://api.opensubtitles.com/api/v1"
OPENSUBTITLES_KEY = os.environ.get("OPENSUBTITLES_API_KEY", "")
OPENSUBTITLES_USER = os.environ.get("OPENSUBTITLES_USER", "")
OPENSUBTITLES_PASS = os.environ.get("OPENSUBTITLES_PASS", "")


def default_media_dirs() -> list[Path]:
    env = os.environ.get("CASTLOCAL_DIRS", "")
    if env:
        return [Path(p).expanduser() for p in env.split(":") if p.strip()]
    home = Path.home()
    return [home / "Downloads", home / "Videos"]


def lan_ip() -> str:
    """Best-effort LAN IP so the Chromecast can fetch from us."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def ensure_dirs() -> None:
    SUBS_CACHE.mkdir(parents=True, exist_ok=True)
