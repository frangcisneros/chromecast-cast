# castlocal

Send a video file from this PC to the Chromecast. Open `http://192.168.1.52:8000`
on the PC or the phone, pick a file, pick the Chromecast, press Castear.

The phone's Google Home app picks up playback on its own (play, pause,
volume, seek). No extra setup for that.

## How it works

- Files come from `~/Downloads` and `~/Videos`, newest first. Override with
  `CASTLOCAL_DIRS=/path/one:/path/two`.
- MP4 with H264 + AAC plays directly. Anything else (MKV, HEVC, AVI, DTS)
  gets converted on the fly with ffmpeg to H264 + AAC. Seeking a converted
  file restarts the conversion at the new position.
- Subtitles: sidecar `.srt`/`.vtt` next to the video is picked up
  automatically. You can also search OpenSubtitles in Spanish, download one
  of the results, or upload your own `.srt`. The `±0.5s` buttons shift a
  badly synced subtitle.

## Run

Console launcher (opens a terminal, Q stops it and closes):

```bash
./castlocal-console.sh
```

Or from the app menu: Castlocal. To install the menu entry:

```bash
sed "s|@@DIR@@|$PWD|" castlocal.desktop.template > ~/.local/share/applications/castlocal.desktop
```

Manual run:

```bash
cd ~/projects/castlocal
uv run python -m castlocal.app
```

Autostart on login:

```bash
mkdir -p ~/.config/systemd/user
cp castlocal.service ~/.config/systemd/user/
systemctl --user enable --now castlocal
```

## Subtitle search (optional)

Searching needs a free key from opensubtitles.com. Downloading also needs
a username and password there.

```bash
export OPENSUBTITLES_API_KEY=...
export OPENSUBTITLES_USER=...
export OPENSUBTITLES_PASS=...
```

Without a key, upload works anyway: download the `.srt` from wherever you
like and attach it with "Subir .srt".

## Notes

- PC and Chromecast must share the same WiFi (`192.168.1.x`).
- Port 8000/tcp must be reachable. This repo's firewall already allows it.
- Tested against a 1st-gen Chromecast. 1080p H264 plays; 4K and 60fps get
  converted down.
