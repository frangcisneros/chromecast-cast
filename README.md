# castlocal

Send a video file from this PC to a Chromecast. Open the server address on
the PC or the phone, pick a file, pick the Chromecast, press Castear.

The phone's Google Home app picks up playback on its own (play, pause,
volume, seek). No extra setup for that.

## Requirements

- Python 3.11+ with [uv](https://docs.astral.sh/uv/), ffmpeg with libx264
- A Chromecast on the same WiFi as this PC (tested on 1st-gen)
- Port 8000/tcp reachable from the phone

## Run

Double-click `castlocal-console.sh` (or the Castlocal menu entry) to toggle
the server: the first double-click starts it and shows the address in a
popup, the second asks whether to stop it. No terminal needed. Without a
graphical session it falls back to console mode (Q stops it).

To install the menu entry:

```bash
sed "s|@@DIR@@|$PWD|" castlocal.desktop.template > ~/.local/share/applications/castlocal.desktop
```

Manual run:

```bash
uv run python -m castlocal.app
```

Autostart on login:

```bash
mkdir -p ~/.config/systemd/user
sed "s|@@DIR@@|$PWD|" castlocal.service > ~/.config/systemd/user/castlocal.service
systemctl --user enable --now castlocal
```

## How it works

- Files come from `~/Downloads` and `~/Videos`, newest first. Override with
  `CASTLOCAL_DIRS=/path/one:/path/two`, or add folders from the web UI.
- MP4 with H264 + AAC plays directly. Anything else (MKV, HEVC, AVI, DTS)
  gets converted on the fly with ffmpeg to H264 + AAC (CRF 18, bitrate
  capped at the High@L4.0 ceiling). Seeking a converted file restarts the conversion at
  the new position, subtitles included (their timing shifts so they stay
  in sync).
- Subtitles: any `.srt`/`.vtt` in the video's folder is picked up
  automatically (same file name first). You can also search OpenSubtitles
  in Spanish, download one of the results, or upload your own `.srt`.
  They render 1.15x (`CASTLOCAL_SUB_SCALE`). The `±0.5s` buttons shift a
  badly synced subtitle.

## Configuration

All optional, via environment (or `~/.config/castlocal.env` for the launcher):

| Variable | Default | Meaning |
|---|---|---|
| `CASTLOCAL_PORT` | `8000` | Server port |
| `CASTLOCAL_DIRS` | `~/Downloads:~/Videos` | Folders to scan, `:` separated |
| `CASTLOCAL_SUB_SCALE` | `1.15` | Subtitle size multiplier on the TV |
| `CASTLOCAL_MAX_LEVEL` | `4.0` | H264 level ceiling (`4.2` for 2nd/3rd-gen) |
| `CASTLOCAL_SUB_WIDTH` | `100` | Subtitle box width % (`85` if the TV overscans edges) |
| `OPENSUBTITLES_API_KEY` | — | Key from opensubtitles.com (enables search) |
| `OPENSUBTITLES_USER` / `OPENSUBTITLES_PASS` | — | Login there (enables downloads) |

Without a key, upload still works: download the `.srt` from wherever you
like and attach it with "Subir .srt".

## Tests

```bash
uv run pytest
```

## Notes

- PC and Chromecast must share the same WiFi.
- Tested against a 1st-gen Chromecast. 1080p H264 plays; 4K and 60fps get
  converted down. On a 2nd/3rd-gen (H264 up to Level 4.2, 5 GHz WiFi),
  set `CASTLOCAL_MAX_LEVEL=4.2` so more files play directly.

## License

GPLv3 — see [LICENSE](LICENSE).
