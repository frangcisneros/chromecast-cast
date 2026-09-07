"""Flask app: browse files, cast, control playback, manage subtitles."""

from __future__ import annotations

import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from castlocal import cast_manager, config, media, streamer, subtitles

_session: dict = {
    "media_id": None,
    "mode": None,
    "sub": "none",
    "offset": 0.0,
    "base": 0.0,
    "duration": None,
}
_files_cache: dict = {"at": 0.0, "items": []}
_probe_cache: dict = {}


def full_duration(vf: media.VideoFile) -> float | None:
    cached = _probe_cache.get(vf.id)
    if cached is not None:
        return cached
    dur = media.duration(media.probe(vf.path))
    _probe_cache[vf.id] = dur
    return dur


def base_url() -> str:
    return f"http://{config.lan_ip()}:{config.PORT}"


def files(refresh: bool = False) -> list[media.VideoFile]:
    if refresh or time.time() - _files_cache["at"] > 30:
        _files_cache["items"] = media.scan()
        _files_cache["at"] = time.time()
    return _files_cache["items"]


def find_media(media_id: str) -> media.VideoFile | None:
    for vf in files():
        if vf.id == media_id:
            return vf
    files(refresh=True)
    for vf in files():
        if vf.id == media_id:
            return vf
    return None


def sub_sources(vf: media.VideoFile) -> list[dict]:
    """Local sidecars + downloaded cache entries for this video."""
    srcs = [{"key": "none", "label": "Sin subtítulos"}]
    for i, path in enumerate(subtitles.find_local(vf.path)):
        srcs.append({"key": f"local:{i}", "label": f"Local: {path.name}", "path": str(path)})
    cache_dir = config.SUBS_CACHE / vf.id
    if cache_dir.is_dir():
        for path in sorted(cache_dir.glob("*")):
            if path.suffix.lower() in config.SUB_EXTS:
                srcs.append({"key": f"cache:{path.name}", "label": f"Descargado: {path.name}"})
    return srcs


def resolve_sub(vf: media.VideoFile, key: str) -> Path | None:
    if key == "none":
        return None
    if key.startswith("local:"):
        paths = subtitles.find_local(vf.path)
        try:
            return paths[int(key.split(":", 1)[1])]
        except (ValueError, IndexError):
            return None
    if key.startswith("cache:"):
        cand = config.SUBS_CACHE / vf.id / key.split(":", 1)[1]
        return cand if cand.is_file() else None
    return None


def sub_url(vf: media.VideoFile, key: str, offset: float) -> str | None:
    if resolve_sub(vf, key) is None:
        return None
    return f"{base_url()}/subs/{vf.id}?key={key}&offset={offset}"


def create_app() -> Flask:
    config.ensure_dirs()
    app = Flask(__name__)

    @app.after_request
    def cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Range, Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/api/server")
    def server():
        return jsonify({"base_url": base_url(), "port": config.PORT})

    @app.get("/api/dirs")
    def list_dirs():
        return jsonify(
            {
                "dirs": [str(p) for p in config.get_media_dirs()],
                "custom": [str(p) for p in config.custom_dirs()],
                "defaults": [str(p) for p in config.default_media_dirs()],
            }
        )

    @app.post("/api/dirs")
    def add_dir():
        body = request.get_json(force=True, silent=True) or {}
        try:
            added = config.add_media_dir(str(body.get("path", "")))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        _files_cache["at"] = 0
        return jsonify({"ok": True, "added": str(added)})

    @app.delete("/api/dirs")
    def delete_dir():
        body = request.get_json(force=True, silent=True) or {}
        config.remove_media_dir(str(body.get("path", "")))
        _files_cache["at"] = 0
        return jsonify({"ok": True})

    @app.post("/api/dirs/reset")
    def reset_dirs():
        config.clear_custom_dirs()
        _files_cache["at"] = 0
        return jsonify({"ok": True})

    @app.get("/api/files")
    def list_files():
        items = []
        for vf in files(refresh=True):
            mode, _mime = media.decide(vf.path)
            srcs = [{"key": s["key"], "label": s["label"]} for s in sub_sources(vf)]
            items.append(
                {
                    "id": vf.id,
                    "name": vf.name,
                    "size_mb": round(vf.size / 1024 / 1024),
                    "mtime": vf.mtime,
                    "mode": mode,
                    "subs": srcs,
                }
            )
        return jsonify({"files": items})

    @app.get("/api/devices")
    def devices():
        try:
            found = cast_manager.discover()
        except Exception as exc:
            return jsonify({"devices": [], "error": str(exc)}), 200
        return jsonify({"devices": found, "connected": cast_manager.device_info()})

    @app.post("/api/connect")
    def connect():
        body = request.get_json(force=True, silent=True) or {}
        try:
            cast_manager.connect(host=body.get("host"), name=body.get("name"))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"connected": cast_manager.device_info()})

    @app.post("/api/cast")
    def cast():
        body = request.get_json(force=True, silent=True) or {}
        vf = find_media(str(body.get("media", "")))
        if vf is None:
            return jsonify({"error": "archivo no encontrado"}), 404
        sub_key = str(body.get("sub", "none"))
        offset = float(body.get("offset", 0) or 0)
        start = float(body.get("start", 0) or 0)
        mode, mime = media.decide(vf.path)
        surl = sub_url(vf, sub_key, offset)
        dur = full_duration(vf)
        try:
            if mode == "direct":
                streamer.transcode_stop()
                url = f"{base_url()}/media/{vf.id}"
                cast_manager.play(url, mime, vf.name, sub_url=surl, start=start)
                base = 0.0
            else:
                url = f"{base_url()}/transcode/{vf.id}?start={start}"
                streamer.transcode_start(vf.id, vf.path, start, mode)
                # El receptor arranca su reloj en 0 aunque el video empiece en
                # `start`: desplazar los subs para que sigan sincronizados.
                surl = sub_url(vf, sub_key, offset - start)
                cast_manager.play(url, mime, vf.name, sub_url=surl, start=0, duration=dur)
                base = start
        except Exception as exc:
            streamer.transcode_stop()
            return jsonify({"error": str(exc)}), 502
        _session.update(
            {
                "media_id": vf.id,
                "mode": mode,
                "sub": sub_key,
                "offset": offset,
                "base": base,
                "duration": dur,
            }
        )
        return jsonify({"ok": True, "mode": mode, "device": cast_manager.device_info()})

    @app.get("/api/status")
    def status():
        try:
            st = cast_manager.status()
        except Exception as exc:
            return jsonify({"connected": False, "error": str(exc)})
        base = float(_session.get("base") or 0)
        total = float(_session.get("duration") or 0)
        if st.get("connected") and _session.get("mode") in ("remux", "transcode"):
            current = float(st.get("current_time") or 0)
            st["current_time"] = min(base + current, total) if total else base + current
            if total:
                st["duration"] = total
        st["session"] = {k: v for k, v in _session.items()}
        return jsonify(st)

    @app.post("/api/pause")
    def pause():
        cast_manager.pause()
        return jsonify({"ok": True})

    @app.post("/api/play")
    def play():
        cast_manager.resume()
        return jsonify({"ok": True})

    @app.post("/api/stop")
    def stop():
        cast_manager.stop()
        streamer.transcode_stop()
        _session.update({"media_id": None, "mode": None})
        return jsonify({"ok": True})

    @app.post("/api/seek")
    def seek():
        body = request.get_json(force=True, silent=True) or {}
        try:
            st = cast_manager.status()
            current = float(st.get("current_time") or 0)
        except Exception:
            current = 0
        if "position" in body:
            target = float(body["position"])
        else:
            target = current + float(body.get("delta", 0))
        target = max(0.0, target)
        if _session.get("mode") in ("remux", "transcode") and _session.get("media_id"):
            vf = find_media(str(_session["media_id"]))
            if vf is not None:
                pipe = str(_session.get("mode"))
                streamer.transcode_start(vf.id, vf.path, target, pipe)
                url = f"{base_url()}/transcode/{vf.id}?start={target}"
                user_offset = float(_session.get("offset", 0) or 0)
                # El receptor reinicia su reloj en 0: correr los subs -target.
                sub = sub_url(vf, str(_session.get("sub", "none")), user_offset - target)
                cast_manager.play(
                    url, "video/mp4", vf.name, sub_url=sub, start=0, duration=full_duration(vf)
                )
                _session["base"] = target
                return jsonify({"ok": True, "position": target, "reloaded": True})
        cast_manager.seek(target)
        return jsonify({"ok": True, "position": target})

    @app.post("/api/subtitle")
    def subtitle():
        """Switch subtitle mid-playback: re-LOAD from current position."""
        body = request.get_json(force=True, silent=True) or {}
        if not _session.get("media_id"):
            return jsonify({"error": "nada en reproducción"}), 409
        vf = find_media(str(_session["media_id"]))
        if vf is None:
            return jsonify({"error": "archivo no encontrado"}), 404
        sub_key = str(body.get("sub", "none"))
        offset = float(body.get("offset", _session.get("offset", 0)) or 0)
        _session.update({"sub": sub_key, "offset": offset})
        try:
            st = cast_manager.status()
            pos = float(st.get("current_time") or 0)
        except Exception:
            pos = 0
        mode = str(_session.get("mode") or "direct")
        if mode in ("remux", "transcode"):
            # El Chromecast cuenta desde el inicio del transcode actual;
            # la posición real es base + lo que lleva andando (igual que /api/status).
            pos = float(_session.get("base") or 0) + pos
            dur = full_duration(vf)
            if dur:
                pos = min(pos, max(0.0, dur - 1))
        surl = sub_url(vf, sub_key, offset)
        try:
            if mode in ("remux", "transcode"):
                streamer.transcode_start(vf.id, vf.path, pos, mode)
                url = f"{base_url()}/transcode/{vf.id}?start={pos}"
                dur = full_duration(vf)
                # Reloj del receptor vuelve a 0: correr los subs -pos.
                surl = sub_url(vf, sub_key, offset - pos)
                cast_manager.play(url, "video/mp4", vf.name, sub_url=surl, start=0, duration=dur)
                _session["base"] = pos
            else:
                url = f"{base_url()}/media/{vf.id}"
                cast_manager.play(url, "video/mp4", vf.name, sub_url=surl, start=pos)
                _session["base"] = 0.0
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"ok": True})

    @app.post("/api/volume")
    def volume():
        body = request.get_json(force=True, silent=True) or {}
        if "muted" in body:
            cast_manager.set_muted(bool(body["muted"]))
        if "level" in body:
            cast_manager.set_volume(float(body["level"]))
        if "delta" in body:
            st = cast_manager.status()
            cast_manager.set_volume(float(st.get("volume_level") or 0) + float(body["delta"]))
        return jsonify({"ok": True})

    @app.get("/media/<media_id>")
    def serve_media(media_id: str):
        vf = find_media(media_id)
        if vf is None:
            return jsonify({"error": "archivo no encontrado"}), 404
        size = vf.path.stat().st_size
        rng = streamer.parse_range(request.headers.get("Range"), size)
        headers = {
            "Content-Type": "video/mp4",
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
        }
        if rng is None:
            headers["Content-Length"] = str(size)
            return Response(streamer.file_chunks(vf.path, 0, size - 1), status=200, headers=headers)
        start, end = rng
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        return Response(streamer.file_chunks(vf.path, start, end), status=206, headers=headers)

    @app.get("/transcode/<media_id>")
    def serve_transcode(media_id: str):
        vf = find_media(media_id)
        if vf is None:
            return jsonify({"error": "archivo no encontrado"}), 404
        start = float(request.args.get("start", 0) or 0)
        streamer.transcode_start(vf.id, vf.path, start)
        headers = {"Content-Type": "video/mp4", "Access-Control-Allow-Origin": "*"}
        return Response(streamer.transcode_chunks(), status=200, headers=headers)

    @app.get("/subs/<media_id>")
    def serve_sub(media_id: str):
        vf = find_media(media_id)
        if vf is None:
            return jsonify({"error": "archivo no encontrado"}), 404
        key = request.args.get("key", "none")
        offset = float(request.args.get("offset", 0) or 0)
        path = resolve_sub(vf, key)
        if path is None:
            return jsonify({"error": "subtítulo no encontrado"}), 404
        try:
            vtt = subtitles.load_vtt(path, offset)
        except OSError as exc:
            return jsonify({"error": str(exc)}), 500
        print(f"[subs] serve media={media_id} key={key} bytes={len(vtt)}", flush=True)
        return Response(vtt, status=200, content_type="text/vtt; charset=utf-8")

    @app.get("/api/subs/list")
    def subs_list():
        vf = find_media(str(request.args.get("media", "")))
        if vf is None:
            return jsonify({"error": "archivo no encontrado"}), 404
        srcs = sub_sources(vf)
        return jsonify({"subs": [{"key": s["key"], "label": s["label"]} for s in srcs]})

    @app.get("/api/subs/search")
    def subs_search():
        vf = find_media(str(request.args.get("media", "")))
        query = request.args.get("q", "") or (vf.path.stem if vf else "")
        if vf is None:
            return jsonify({"error": "archivo no encontrado"}), 404
        try:
            items = subtitles.search_opensubtitles(query)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"subs": items})

    @app.post("/api/subs/download")
    def subs_download():
        body = request.get_json(force=True, silent=True) or {}
        vf = find_media(str(body.get("media", "")))
        if vf is None:
            return jsonify({"error": "archivo no encontrado"}), 404
        if not body.get("file_id"):
            return jsonify({"error": "falta file_id"}), 400
        try:
            dest = config.SUBS_CACHE / vf.id / f"os_{body.get('file_id')}.srt"
            subtitles.download_opensubtitles(int(str(body.get("file_id"))), dest)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502
        return jsonify({"ok": True, "key": f"cache:{dest.name}"})

    @app.post("/api/subs/upload")
    def subs_upload():
        media_id = request.form.get("media", "")
        vf = find_media(media_id)
        if vf is None:
            return jsonify({"error": "archivo no encontrado"}), 404
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "falta archivo .srt/.vtt"}), 400
        suffix = Path(f.filename).suffix.lower()
        if suffix not in config.SUB_EXTS:
            return jsonify({"error": "solo .srt o .vtt"}), 400
        dest = config.SUBS_CACHE / vf.id / f.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        f.save(dest)
        return jsonify({"ok": True, "key": f"cache:{dest.name}"})

    return app


def main() -> None:
    from waitress import serve

    config.ensure_dirs()
    app = create_app()
    print(f"castlocal en http://{config.lan_ip()}:{config.PORT}")
    print(f"local en http://127.0.0.1:{config.PORT}")
    serve(app, host="0.0.0.0", port=config.PORT)


if __name__ == "__main__":
    main()
