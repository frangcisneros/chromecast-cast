from pathlib import Path

from castlocal import media, subtitles


def test_srt_to_vtt_basic():
    srt = "1\n00:00:01,000 --> 00:00:02,500\nHola mundo\n\n2\n00:00:03,000 --> 00:00:04,000\nChau\n"
    vtt = subtitles.srt_to_vtt(srt)
    assert vtt.startswith("WEBVTT")
    assert "00:00:01.000 --> 00:00:02.500" in vtt
    assert "Hola mundo" in vtt


def test_shift_vtt_positive():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHola\n"
    shifted = subtitles.shift_vtt(vtt, 1.5)
    assert "00:00:02.500 --> 00:00:03.500" in shifted


def test_shift_vtt_negative_drops_past_cues():
    vtt = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\nViejo\n\n"
        "00:00:09.000 --> 00:00:11.000\nMitad\n\n"
        "00:00:20.000 --> 00:00:22.000\nFuturo\n"
    )
    shifted = subtitles.shift_vtt(vtt, -10)
    assert "Viejo" not in shifted  # terminó antes de 0: se descarta
    assert "00:00:00.000 --> 00:00:01.000\nMitad" in shifted  # a caballo: arranca en 0
    assert "00:00:10.000 --> 00:00:12.000\nFuturo" in shifted


def test_find_local_folder_scan(tmp_path: Path):
    video = tmp_path / "peli.mkv"
    video.write_bytes(b"x")
    same = tmp_path / "peli.srt"
    same.write_text("1\n00:00:01,000 --> 00:00:02,000\nHola\n")
    other = tmp_path / "otro-titulo.srt"
    other.write_text("1\n00:00:01,000 --> 00:00:02,000\nHola\n")
    elsewhere = tmp_path / "sub"
    elsewhere.mkdir()
    (elsewhere / "lejos.srt").write_text("x")
    (tmp_path / "peli.ass").write_text("x")  # formato no soportado: se ignora
    found = subtitles.find_local(video)
    assert found == [same, other]


def test_sub_style_injects_font_scale():
    from castlocal import cast_manager, config

    sent = []

    class FakeMC:
        def send_message(self, msg, **kwargs):
            sent.append(msg)

    mc = FakeMC()
    cast_manager._install_sub_style(mc)
    cast_manager._install_sub_style(mc)  # idempotente: no duplica el wrapper
    mc.send_message({"media": {"textTrackStyle": {"edgeType": "OUTLINE"}}})
    assert sent[0]["media"]["textTrackStyle"]["fontScale"] == config.SUBTITLE_SCALE
    mc.send_message({"type": "PING"})
    assert sent[1] == {"type": "PING"}


def test_ffmpeg_cmd_conforms_to_ceiling():
    from pathlib import Path

    from castlocal import streamer

    cmd = streamer.ffmpeg_cmd(Path("/tmp/x.mkv"), 0)
    assert "zerolatency" not in cmd  # quita B-frames: peor calidad
    assert cmd[cmd.index("-crf") + 1] == "18"
    assert cmd[cmd.index("-preset") + 1] == "medium"
    assert cmd[cmd.index("-tune") + 1] == "film"
    assert "-maxrate" in cmd and "-bufsize" in cmd
    assert cmd[cmd.index("-level") + 1] == "4.0"  # default; sube con MAX_LEVEL
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("scale=") and "1920" in vf  # 4K se baja a 1080p


def test_narrow_cues_overscan():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHola\n"
    assert subtitles._narrow_cues(vtt, 100) == vtt  # default: no toca nada
    narrowed = subtitles._narrow_cues(vtt, 85)
    assert "00:00:01.000 --> 00:00:02.000 size:85%" in narrowed
    with_settings = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000 align:start position:0%\nHola\n"
    assert subtitles._narrow_cues(with_settings, 85) == with_settings


def test_shift_vtt_keeps_note_blocks():
    vtt = "WEBVTT\nNOTE un comentario 00:00:01.000\n\n00:00:05.000 --> 00:00:06.000\nHola\n"
    shifted = subtitles.shift_vtt(vtt, 2)
    assert "NOTE un comentario 00:00:01.000" in shifted
    assert "00:00:07.000 --> 00:00:08.000" in shifted


def test_shift_vtt_zero_is_identity():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHola\n"
    assert subtitles.shift_vtt(vtt, 0) == vtt


def test_file_id_stable(tmp_path: Path):
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")
    assert media.file_id(p) == media.file_id(p)
    assert len(media.file_id(p)) == 16


def test_decide_mp4_h264_direct():
    info = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "level": "40"},
            {"codec_type": "audio", "codec_name": "aac", "channels": "2"},
        ]
    }
    assert media.decide(Path("peli.mp4"), info) == ("direct", "video/mp4")


def test_decide_level41_direct_on_gen2(monkeypatch):
    from castlocal import config

    monkeypatch.setattr(config, "MAX_LEVEL", 4.2)
    info = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "level": "41"},
            {"codec_type": "audio", "codec_name": "aac", "channels": "2"},
        ]
    }
    assert media.decide(Path("peli.mp4"), info) == ("direct", "video/mp4")


def test_decide_level41_transcodes():
    info = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "level": "41"},
            {"codec_type": "audio", "codec_name": "aac", "channels": "2"},
        ]
    }
    assert media.decide(Path("peli.mp4"), info) == ("transcode", "video/mp4")


def test_decide_51_audio_remuxes():
    info = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "level": "40"},
            {"codec_type": "audio", "codec_name": "aac", "channels": "6"},
        ]
    }
    assert media.decide(Path("peli.mp4"), info) == ("remux", "video/mp4")


def test_decide_hevc_transcode():
    info = {
        "streams": [
            {"codec_type": "video", "codec_name": "hevc"},
            {"codec_type": "audio", "codec_name": "aac"},
        ]
    }
    assert media.decide(Path("peli.mkv"), info) == ("transcode", "video/mp4")


def test_decide_mkv_h264_transcodes_container():
    info = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264"},
            {"codec_type": "audio", "codec_name": "aac"},
        ]
    }
    assert media.decide(Path("peli.mkv"), info) == ("transcode", "video/mp4")


def test_parse_range():
    assert media.decide(Path("x.mp4"), {}) == ("direct", "video/mp4")
    from castlocal import streamer

    assert streamer.parse_range("bytes=0-99", 1000) == (0, 99)
    assert streamer.parse_range(None, 1000) is None
    assert streamer.parse_range("bytes=9999-10000", 1000) is None


def test_custom_dirs(tmp_path: Path, monkeypatch):
    from castlocal import config

    dirs_file = tmp_path / "dirs.json"
    monkeypatch.setattr(config, "DIRS_FILE", dirs_file)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    assert config.custom_dirs() == []
    other = tmp_path / "pelis"
    other.mkdir()
    config.add_media_dir(str(other))
    assert config.get_media_dirs() == [other]
    with open(dirs_file, encoding="utf-8") as f:
        import json

        assert json.load(f) == [str(other)]
    config.remove_media_dir(str(other))
    assert config.custom_dirs() == []
    try:
        config.add_media_dir(str(tmp_path / "nope"))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
