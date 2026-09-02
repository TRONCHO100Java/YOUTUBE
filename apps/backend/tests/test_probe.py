"""Parseo de la salida de ffprobe (sin ejecutar el binario)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipforge.core.errors import ExternalToolError
from clipforge.services.video.probe import _parse, _parse_fps

FAKE_PATH = Path("video.mp4")


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "format": {"duration": "612.345"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }
    base.update(overrides)
    return base


def test_parses_a_standard_video() -> None:
    metadata = _parse(_payload(), FAKE_PATH)
    assert metadata.duration == pytest.approx(612.345)
    assert (metadata.width, metadata.height) == (1920, 1080)
    assert metadata.fps == pytest.approx(29.97, abs=0.01)
    assert metadata.has_audio is True
    assert metadata.video_codec == "h264"


def test_detects_video_without_audio() -> None:
    payload = _payload(streams=[{"codec_type": "video", "width": 1280, "height": 720}])
    assert _parse(payload, FAKE_PATH).has_audio is False


def test_falls_back_to_stream_duration() -> None:
    payload = _payload(format={})
    payload["streams"] = [{"codec_type": "video", "width": 640, "height": 360, "duration": "12.5"}]
    assert _parse(payload, FAKE_PATH).duration == pytest.approx(12.5)


def test_rejects_file_without_video_stream() -> None:
    payload = _payload(streams=[{"codec_type": "audio", "codec_name": "mp3"}])
    with pytest.raises(ExternalToolError, match="pista de vídeo"):
        _parse(payload, FAKE_PATH)


def test_rejects_unknown_duration() -> None:
    payload = _payload(format={})
    with pytest.raises(ExternalToolError, match="duración"):
        _parse(payload, FAKE_PATH)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("30/1", 30.0), ("24000/1001", 23.976), ("0/0", 0.0), ("25", 25.0), (None, 0.0)],
)
def test_parses_frame_rate_fractions(raw: object, expected: float) -> None:
    assert _parse_fps(raw) == pytest.approx(expected, abs=0.001)
