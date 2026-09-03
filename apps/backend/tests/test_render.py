"""Render de clips: se ejecuta ffmpeg de verdad sobre un vídeo generado.

Es el test que de verdad demuestra la FASE 5. Se usa siempre libx264 para que
la comprobación sea reproducible en cualquier máquina; que NVENC funcione en
esta GPU se verifica aparte, en `test_encoder.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.services.subtitles import SourceSegment, build_cues, write_ass
from clipforge.services.video.encoder import LIBX264, EncoderProfile, _profile
from clipforge.services.video.probe import probe_video
from clipforge.services.video.render import render_vertical_clip

CPU_ENCODER: EncoderProfile = _profile(LIBX264)


@pytest.fixture(scope="module")
def source_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Vídeo horizontal de 10 s con audio, como los que procesa el sistema."""
    path = tmp_path_factory.mktemp("render") / "source.mp4"
    subprocess.run(
        [
            settings.ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=10:size=1280x720:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=180,
    )
    return path


def test_renders_a_vertical_clip(source_video: Path, tmp_path: Path) -> None:
    destination = tmp_path / "clip.mp4"

    result = render_vertical_clip(
        source_video, destination, start=2.0, end=6.0, encoder=CPU_ENCODER
    )

    assert result.path.is_file()
    assert (result.width, result.height) == (settings.output_width, settings.output_height)
    assert result.duration == pytest.approx(4.0, abs=0.3)
    assert result.filesize_bytes > 0
    assert result.encoder == LIBX264
    assert result.has_burned_subtitles is False


def test_output_is_really_nine_sixteen(source_video: Path, tmp_path: Path) -> None:
    destination = tmp_path / "clip.mp4"
    render_vertical_clip(source_video, destination, start=0.0, end=3.0, encoder=CPU_ENCODER)

    probed = probe_video(destination)
    assert probed.width / probed.height == pytest.approx(9 / 16, abs=0.001)


def test_audio_is_preserved(source_video: Path, tmp_path: Path) -> None:
    """Un clip mudo no sirve de nada."""
    destination = tmp_path / "clip.mp4"
    render_vertical_clip(source_video, destination, start=1.0, end=4.0, encoder=CPU_ENCODER)

    assert probe_video(destination).has_audio is True


def test_burns_subtitles_when_requested(source_video: Path, tmp_path: Path) -> None:
    cues = build_cues([SourceSegment(start=2.0, end=5.0, text="Texto con acentuación")], 2.0, 6.0)
    subtitles = write_ass(
        cues, tmp_path / "subs" / "clip.ass", settings.output_width, settings.output_height
    )
    destination = tmp_path / "clip.mp4"

    result = render_vertical_clip(
        source_video,
        destination,
        start=2.0,
        end=6.0,
        subtitles=subtitles,
        encoder=CPU_ENCODER,
    )

    assert result.has_burned_subtitles is True
    assert result.path.stat().st_size > 0


def test_burned_output_differs_from_the_clean_one(source_video: Path, tmp_path: Path) -> None:
    """Si el filtro no se aplicase, los dos ficheros serían idénticos."""
    cues = build_cues([SourceSegment(start=0.0, end=3.0, text="SUBTITULO VISIBLE")], 0.0, 3.0)
    subtitles = write_ass(
        cues, tmp_path / "subs" / "clip.ass", settings.output_width, settings.output_height
    )

    clean = tmp_path / "clean.mp4"
    burned = tmp_path / "burned.mp4"
    render_vertical_clip(source_video, clean, start=0.0, end=3.0, encoder=CPU_ENCODER)
    render_vertical_clip(
        source_video, burned, start=0.0, end=3.0, subtitles=subtitles, encoder=CPU_ENCODER
    )

    assert clean.read_bytes() != burned.read_bytes()


def test_creates_missing_output_directories(source_video: Path, tmp_path: Path) -> None:
    destination = tmp_path / "nueva" / "carpeta" / "clip.mp4"
    render_vertical_clip(source_video, destination, start=0.0, end=2.0, encoder=CPU_ENCODER)

    assert destination.is_file()


@pytest.mark.parametrize(("start", "end"), [(5.0, 5.0), (6.0, 2.0)])
def test_invalid_range_is_rejected(
    source_video: Path, tmp_path: Path, start: float, end: float
) -> None:
    with pytest.raises(ExternalToolError, match="Rango"):
        render_vertical_clip(
            source_video, tmp_path / "clip.mp4", start=start, end=end, encoder=CPU_ENCODER
        )


def test_missing_source_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ExternalToolError, match="No existe"):
        render_vertical_clip(
            tmp_path / "no-existe.mp4",
            tmp_path / "clip.mp4",
            start=0.0,
            end=2.0,
            encoder=CPU_ENCODER,
        )
