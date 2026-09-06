from pathlib import Path

from castlocal import media, subtitles


def test_srt_to_vtt_basic():
    srt = "1\n00:00:01,000 --> 00:00:02,500\nHola mundo\n\n2\n00:00:03,000 --> 00:00:04,000\nChau\n"
    vtt = subtitles.srt_to_vtt(srt)
    assert vtt.startswith("WEBVTT")
    assert "00:00:01.000 --> 00:00:02.500" in vtt
    assert "Hola mundo" in vtt


def test_shift_vtt_positive_and_clamp():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHola\n"
    shifted = subtitles.shift_vtt(vtt, 1.5)
    assert "00:00:02.500 --> 00:00:03.500" in shifted
    back = subtitles.shift_vtt(shifted, -10)
    assert "00:00:00.000 -->" in back


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
