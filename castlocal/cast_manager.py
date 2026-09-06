"""Thin thread-safe wrapper around pychromecast.

Uses the Default Media Receiver, so the phone's Google Home app and the
system Cast notification pick up playback automatically.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any

import pychromecast

_lock = threading.Lock()
_cast: Any | None = None
_device: dict[str, Any] = {}


def discover(timeout: int = 6) -> list[dict[str, Any]]:
    try:
        devices, browser = pychromecast.get_chromecasts(timeout=timeout)
        pychromecast.stop_discovery(browser)
    except Exception:
        return []
    out = []
    for cc in devices:
        out.append(
            {
                "name": cc.cast_info.friendly_name,
                "host": cc.cast_info.host,
                "port": cc.cast_info.port,
                "model": cc.cast_info.model_name,
            }
        )
    return sorted(out, key=lambda d: d["name"])


def connect(host: str | None = None, name: str | None = None, timeout: int = 10):
    """Connect to a device; reuse the existing connection when possible."""
    global _cast, _device
    with _lock:
        if _cast is not None and host is None and name is None:
            return _cast
        if host:
            devices, _browser = pychromecast.get_chromecasts(timeout=6, known_hosts=[host])
            cc = next((d for d in devices if d.cast_info.host == host), None)
            if cc is None and devices:
                cc = devices[0]
            if cc is None:
                raise ConnectionError(f"no Chromecast at {host}")
        else:
            devices, _browser = pychromecast.get_chromecasts(timeout=6)
            cc = None
            for dev in devices:
                if name and dev.cast_info.friendly_name == name:
                    cc = dev
                    break
            if cc is None and devices and name is None:
                cc = devices[0]
            if cc is None:
                raise ConnectionError("no Chromecast found on this network")
        cc.wait(timeout=timeout)
        _cast = cc
        _device = {
            "name": cc.cast_info.friendly_name,
            "host": cc.cast_info.host,
            "model": cc.cast_info.model_name,
        }
        return cc


def current():
    with _lock:
        return _cast


def _require():
    cc = current()
    if cc is None:
        raise ConnectionError("not connected to any Chromecast")
    return cc


def device_info() -> dict[str, Any] | None:
    with _lock:
        return dict(_device) if _device else None


def play(
    url: str,
    content_type: str,
    title: str,
    sub_url: str | None = None,
    start: float = 0,
    duration: float | None = None,
) -> None:
    cc = connect()
    mc = cc.media_controller
    mc.play_media(
        url,
        content_type,
        title=title,
        subtitles=sub_url,
        subtitles_lang="es",
        subtitles_mime="text/vtt",
        subtitle_id=1,
        current_time=start or None,
        autoplay=True,
        stream_type="BUFFERED",
        media_info={"duration": duration} if duration else None,
    )
    mc.block_until_active(timeout=15)


def pause() -> None:
    _require().media_controller.pause()


def resume() -> None:
    _require().media_controller.play()


def stop() -> None:
    cc = current()
    if cc is None:
        return
    try:
        cc.media_controller.stop()
    finally:
        with contextlib.suppress(Exception):
            cc.quit_app()


def seek(position: float) -> None:
    _require().media_controller.seek(float(position))


def set_volume(level: float) -> None:
    cc = _require()
    cc.set_volume(max(0.0, min(1.0, float(level))))


def set_muted(muted: bool) -> None:
    _require().set_volume_muted(bool(muted))


def status() -> dict[str, Any]:
    cc = current()
    if cc is None:
        return {"connected": False}
    mc = cc.media_controller
    with contextlib.suppress(Exception):
        mc.update_status()
    st = mc.status
    if st is None:
        return {"connected": True, "player_state": "UNKNOWN"}
    try:
        cc_status = cc.status
        volume = cc_status.volume_level if cc_status else st.volume_level
        muted = cc_status.volume_muted if cc_status else st.volume_muted
    except Exception:
        volume, muted = st.volume_level, st.volume_muted
    return {
        "connected": True,
        "player_state": st.player_state,
        "idle_reason": st.idle_reason,
        "current_time": st.current_time,
        "duration": st.duration,
        "volume_level": volume,
        "volume_muted": muted,
        "supports_pause": bool(st.supported_media_commands & 1),
        "supports_seek": bool(st.supported_media_commands & 2),
    }
