"""Runtime configuration from environment with sane defaults."""

from __future__ import annotations

import os
import socket
from pathlib import Path

CACHE_DIR = Path(os.environ.get("CASTLOCAL_CACHE", str(Path.home() / ".cache" / "castlocal")))
SUBS_CACHE = CACHE_DIR / "subs"
CONFIG_DIR = Path.home() / ".config" / "castlocal"
DIRS_FILE = CONFIG_DIR / "dirs.json"
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


def custom_dirs() -> list[Path]:
    """User-added folders from the web UI. Empty = use defaults."""
    try:
        import json

        raw = json.loads(DIRS_FILE.read_text(encoding="utf-8"))
        return [Path(p).expanduser() for p in raw if isinstance(p, str) and p.strip()]
    except (OSError, ValueError):
        return []


def get_media_dirs() -> list[Path]:
    customs = [p for p in custom_dirs() if p.is_dir()]
    return customs or default_media_dirs()


def add_media_dir(path_str: str) -> Path:
    path = Path(path_str.strip()).expanduser()
    if not str(path):
        raise ValueError("ruta vacía")
    if not path.is_dir():
        raise ValueError(f"no es una carpeta: {path}")
    current = [str(p) for p in custom_dirs()]
    if str(path) not in current:
        current.append(str(path))
        _save_dirs(current)
    return path


def remove_media_dir(path_str: str) -> None:
    path = str(Path(path_str.strip()).expanduser())
    _save_dirs([p for p in (str(p) for p in custom_dirs()) if p != path])


def clear_custom_dirs() -> None:
    _save_dirs([])


def _save_dirs(paths: list[str]) -> None:
    import json

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DIRS_FILE.write_text(json.dumps(paths, indent=2), encoding="utf-8")


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
