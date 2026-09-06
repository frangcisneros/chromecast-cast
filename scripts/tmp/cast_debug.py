"""Try successive LOAD variants against the Gen 1 Chromecast.

Each variant holds ~25s so there is time to look at the TV.
Run: uv run python scripts/tmp/cast_debug.py
"""

from __future__ import annotations

import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pychromecast

HOST = "192.168.1.38"
HTTP_PORT = 8123
MEDIA_URL = f"http://192.168.1.52:{HTTP_PORT}/test_baseline.mp4"
SAMPLE = "http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4"


def serve():
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory="scripts/tmp", **kw)

        def log_message(self, format, *args):  # noqa: A002
            print("HTTP HIT:", format % args)

    ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), H).serve_forever()


def report(tag: str, mc) -> None:
    try:
        mc.update_status()
    except Exception as e:
        print(f"[{tag}] update_status err: {e}")
        return
    st = mc.status
    print(
        f"[{tag}] state={st.player_state} idle={st.idle_reason} "
        f"t={st.current_time} dur={st.duration}"
    )


def main() -> None:
    threading.Thread(target=serve, daemon=True).start()
    subprocess.run(["curl", "-s", "-o", "/dev/null", MEDIA_URL], check=False)
    devs, browser = pychromecast.get_chromecasts(timeout=6, known_hosts=[HOST])
    cc = devs[0]
    cc.wait(timeout=10)
    mc = cc.media_controller

    variants = [
        ("V1 raw-minimal-LOAD", lambda: mc.send_message(
            {
                "type": "LOAD",
                "media": {
                    "contentId": MEDIA_URL,
                    "contentType": "video/mp4",
                    "streamType": "BUFFERED",
                },
                "autoplay": True,
            }
        )),
        ("V2 play_media-defaults", lambda: mc.play_media(MEDIA_URL, "video/mp4")),
        ("V3 buffered+title", lambda: mc.play_media(
            MEDIA_URL, "video/mp4", title="test", stream_type="BUFFERED")),
        ("V4 google-sample", lambda: mc.play_media(
            SAMPLE, "video/mp4", title="bbb", stream_type="BUFFERED")),
    ]
    for tag, fn in variants:
        print(f"--- {tag} @ {time.strftime('%H:%M:%S')} ---")
        try:
            fn()
        except Exception as e:
            print(f"[{tag}] send err: {e}")
        for i in range(5):
            time.sleep(5)
            report(f"{tag} +{(i + 1) * 5}s", mc)
    try:
        cc.quit_app()
    except Exception:
        pass
    pychromecast.stop_discovery(browser)
    print("DONE")


if __name__ == "__main__":
    main()
