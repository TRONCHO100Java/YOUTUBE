"""Extracción de audio: se ejecuta ffmpeg de verdad sobre un fichero generado."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.services.video.audio import CHANNELS, SAMPLE_RATE, extract_audio


def _make_media(path: Path, *, with_audio: bool) -> Path:
    """Genera un vídeo de prueba de 1 s con ffmpeg, con o sin pista de audio."""
    command = [
        settings.ffmpeg_path,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=1:size=320x240:rate=10",
    ]
    if with_audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(command, capture_output=True, check=True, timeout=120)
    return path


def _probe(path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            settings.ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    streams = json.loads(completed.stdout)["streams"]
    return dict(streams[0])


def test_extracts_wav_in_the_format_whisper_expects(tmp_path: Path) -> None:
    video = _make_media(tmp_path / "input.mp4", with_audio=True)
    destination = tmp_path / "out" / "audio.wav"

    result = extract_audio(video, destination)

    assert result == destination
    assert destination.stat().st_size > 0
    stream = _probe(destination)
    assert stream["codec_name"] == "pcm_s16le"
    assert int(stream["sample_rate"]) == SAMPLE_RATE  # type: ignore[call-overload]
    assert stream["channels"] == CHANNELS


def test_overwrites_previous_extraction(tmp_path: Path) -> None:
    """Un reintento no debe quedarse esperando la confirmación de ffmpeg."""
    video = _make_media(tmp_path / "input.mp4", with_audio=True)
    destination = tmp_path / "audio.wav"
    destination.write_bytes(b"residuo de una ejecucion anterior")

    extract_audio(video, destination)

    assert destination.read_bytes()[:4] == b"RIFF"


def test_fails_when_the_video_has_no_audio_track(tmp_path: Path) -> None:
    video = _make_media(tmp_path / "mudo.mp4", with_audio=False)
    with pytest.raises(ExternalToolError):
        extract_audio(video, tmp_path / "audio.wav")


def test_fails_when_the_video_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ExternalToolError, match="No existe"):
        extract_audio(tmp_path / "no-existe.mp4", tmp_path / "audio.wav")
