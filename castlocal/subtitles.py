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
    """Sidecar .srt/.vtt for video: same name first, then rest of the folder.

    Order is deterministic (sorted) so local:{i} keys stay stable between
    the file list and the subtitle switch.
    """
    out: list[Path] = []
    for ext in config.SUB_EXTS:
        cand = video.with_suffix(ext)
        if cand.is_file():
            out.append(cand)
    try:
        siblings = sorted(
            p for p in video.parent.iterdir() if p.is_file() and p.suffix.lower() in config.SUB_EXTS
        )
    except OSError:
        siblings = []
    stem = video.stem.lower()
    prefixed = [p for p in siblings if p not in out and p.stem.lower().startswith(stem)]
    rest = [p for p in siblings if p not in out and p not in prefixed]
    return out + prefixed + rest


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
    """Shift cue timestamps by offset seconds (block-wise).

    Cues ending at or before 0 after shifting are dropped (they belong to
    a part of the video that is not playing anymore, e.g. after a seek
    restarts a transcode from a later position); a cue straddling 0 starts
    at 0. Non-cue blocks (NOTE, STYLE, header) are kept as-is.
    """
    if not offset:
        return vtt
    lines = vtt.split("\n")
    head: list[str] = []
    i = 0
    while i < len(lines) and lines[i].strip():
        head.append(lines[i])
        i += 1
    blocks = [b for b in re.split(r"\n\s*\n", "\n".join(lines[i:])) if b.strip()]
    kept: list[str] = []
    for block in blocks:
        blines = block.strip().split("\n")
        tline_idx = next((k for k, ln in enumerate(blines) if "-->" in ln), None)
        if tline_idx is None:
            kept.append(block.strip())
            continue
        stamps = list(_TS.finditer(blines[tline_idx]))[:2]
        if len(stamps) < 2:
            kept.append(block.strip())
            continue
        start = _to_seconds(stamps[0]) + offset
        end = _to_seconds(stamps[1]) + offset
        if end <= 0:
            continue
        line = blines[tline_idx]
        (s0, s1), (e0, e1) = stamps[0].span(), stamps[1].span()
        line = line[:e0] + _format_ts(end) + line[e1:]
        line = line[:s0] + _format_ts(max(0.0, start)) + line[s1:]
        blines[tline_idx] = line
        kept.append("\n".join(blines))
    return "\n\n".join(head + kept) + "\n"


def _narrow_cues(vtt: str, width: int) -> str:
    """Append `size:N%` to cue timing lines that carry no settings.

    Narrows the cue box (centered) so edge text survives TV overscan.
    width >= 100 (or <= 0) = no-op.
    """
    if width >= 100 or width <= 0:
        return vtt
    out = []
    for line in vtt.split("\n"):
        if "-->" in line:
            _head, _, tail = line.partition("-->")
            stamps = list(_TS.finditer(tail))
            if stamps and not tail[stamps[-1].end() :].strip():
                line = line.rstrip() + f" size:{width}%"
        out.append(line)
    return "\n".join(out)


def load_vtt(path: Path, offset: float = 0) -> str:
    text = read_text(path)
    vtt = text if path.suffix.lower() == ".vtt" else srt_to_vtt(text)
    if not vtt.startswith("WEBVTT"):
        vtt = "WEBVTT\n\n" + vtt
    vtt = shift_vtt(vtt, offset)
    return _narrow_cues(vtt, config.SUB_WIDTH)


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
