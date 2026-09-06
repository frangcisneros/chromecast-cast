"""Subtitles: local detection, SRT->VTT, offset shift, OpenSubtitles search."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path

import requests

from castlocal import config

_TS = re.compile(r"(\d+:)?(\d{2}):(\d{2})[,.](\d{3})")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def find_local(video: Path) -> list[Path]:
    """Sidecar .srt/.vtt next to the video, same stem first."""
    out: list[Path] = []
    for ext in config.SUB_EXTS:
        cand = video.with_suffix(ext)
        if cand.is_file():
            out.append(cand)
    for sib in video.parent.glob(f"{video.stem}*.*"):
        if sib.is_file() and sib.suffix.lower() in config.SUB_EXTS and sib not in out:
            out.append(sib)
    return out


def srt_to_vtt(text: str) -> str:
    body = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    # Drop a UTF BOM leftover and split into cue blocks on blank lines.
    blocks = [b for b in re.split(r"\n\s*\n", body) if b.strip()]
    cues: list[str] = []
    for block in blocks:
        lines = block.strip().split("\n")
        if lines and re.fullmatch(r"\d+", lines[0].strip()):
            lines = lines[1:]
        if len(lines) >= 2 and "-->" in lines[0]:
            lines[0] = lines[0].replace(",", ".")
            cues.append("\n".join(lines))
        elif "-->" in block:
            cues.append(block.replace(",", "."))
    return "WEBVTT\n\n" + "\n\n".join(cues) + "\n"


def _to_seconds(m: re.Match) -> float:
    hours = int(m.group(1)[:-1]) if m.group(1) else 0
    return hours * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000


def _format_ts(total: float) -> str:
    total = max(0.0, total)
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    s = int(total % 60)
    ms = round((total - int(total)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def shift_vtt(vtt: str, offset: float) -> str:
    if not offset:
        return vtt

    def repl(m: re.Match) -> str:
        return _format_ts(_to_seconds(m) + offset)

    return _TS.sub(repl, vtt)


def load_vtt(path: Path, offset: float = 0) -> str:
    text = read_text(path)
    vtt = text if path.suffix.lower() == ".vtt" else srt_to_vtt(text)
    if not vtt.startswith("WEBVTT"):
        vtt = "WEBVTT\n\n" + vtt
    return shift_vtt(vtt, offset)


def _headers(extra: dict | None = None) -> dict:
    h = {
        "Api-Key": config.OPENSUBTITLES_KEY,
        "User-Agent": "castlocal/0.1",
        "Accept": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def search_opensubtitles(query: str, languages: str = "es") -> list[dict]:
    if not config.OPENSUBTITLES_KEY:
        raise RuntimeError("Falta OPENSUBTITLES_API_KEY: exportala para buscar subtítulos.")
    r = requests.get(
        f"{config.OPENSUBTITLES_API}/subtitles",
        params={"query": query, "languages": languages},
        headers=_headers(),
        timeout=20,
    )
    r.raise_for_status()
    items = []
    for row in r.json().get("data", []):
        attrs = row.get("attributes", {})
        files = attrs.get("files") or []
        items.append(
            {
                "id": str(row.get("id", "")),
                "file_id": files[0].get("file_id") if files else None,
                "release": attrs.get("release", ""),
                "language": attrs.get("language", ""),
                "downloads": attrs.get("download_count", 0),
                "hd": attrs.get("hd", False),
            }
        )
    return items


def download_opensubtitles(file_id: int, dest: Path) -> Path:
    headers = _headers({"Content-Type": "application/json"})
    if config.OPENSUBTITLES_USER and config.OPENSUBTITLES_PASS:
        login = requests.post(
            f"{config.OPENSUBTITLES_API}/login",
            json={"username": config.OPENSUBTITLES_USER, "password": config.OPENSUBTITLES_PASS},
            headers=headers,
            timeout=20,
        )
        login.raise_for_status()
        token = login.json().get("token", "")
        headers["Authorization"] = f"Bearer {token}"
    dl = requests.post(
        f"{config.OPENSUBTITLES_API}/download",
        json={"file_id": file_id},
        headers=headers,
        timeout=20,
    )
    dl.raise_for_status()
    link = dl.json().get("link", "")
    data = requests.get(link, timeout=60).content
    dest.parent.mkdir(parents=True, exist_ok=True)
    if link.endswith(".zip") or data[:2] == b"PK":
        with zipfile.ZipFile(BytesIO(data)) as zf:
            name = next(
                (n for n in zf.namelist() if n.lower().endswith((".srt", ".vtt"))),
                zf.namelist()[0],
            )
            dest.write_bytes(zf.read(name))
    else:
        dest.write_bytes(data)
    return dest
