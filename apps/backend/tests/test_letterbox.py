"""Detección del letterbox incrustado, con vídeos generados de verdad.

Muchos vídeos de YouTube llevan barras negras quemadas en la imagen. Sin
detectarlas, el clip vertical hereda una cuarta parte de marco negro.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clipforge.core.config import settings
from clipforge.services.video.crop import CropWindow, center_crop_within
from clipforge.services.video.letterbox import detect_content_window


def _make_video(path: Path, filter_complex: str) -> Path:
    subprocess.run(
        [
            settings.ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=1920x1080:rate=25",
            "-vf",
            filter_complex,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=180,
    )
    return path


@pytest.fixture(scope="module")
def letterboxed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """1920x1080 con 140 px de barra negra arriba y abajo."""
    path = tmp_path_factory.mktemp("letterbox") / "bars.mp4"
    return _make_video(path, "scale=1920:800,pad=1920:1080:0:140:black")


@pytest.fixture(scope="module")
def full_frame(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """1920x1080 sin barras."""
    path = tmp_path_factory.mktemp("letterbox") / "full.mp4"
    return _make_video(path, "null")


def test_detects_the_black_bars(letterboxed: Path) -> None:
    window = detect_content_window(letterboxed, 1920, 1080)

    assert window.height == pytest.approx(800, abs=8)
    assert window.y == pytest.approx(140, abs=8)
    assert window.width == 1920


def test_leaves_a_clean_frame_alone(full_frame: Path) -> None:
    window = detect_content_window(full_frame, 1920, 1080)

    assert window == CropWindow(x=0, y=0, width=1920, height=1080)


def test_falls_back_to_the_full_frame_when_ffmpeg_fails(tmp_path: Path) -> None:
    """Ante la duda, no recortar: unas barras molestan menos que un mal encuadre."""
    window = detect_content_window(tmp_path / "no-existe.mp4", 1920, 1080)

    assert window == CropWindow(x=0, y=0, width=1920, height=1080)


def test_black_frames_do_not_produce_an_absurd_crop(tmp_path: Path) -> None:
    """Un muestreo sobre negro total propondría recortarlo casi todo."""
    path = tmp_path / "black.mp4"
    subprocess.run(
        [
            settings.ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:size=1920x1080:rate=25:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=180,
    )

    window = detect_content_window(path, 1920, 1080)
    assert window == CropWindow(x=0, y=0, width=1920, height=1080)


def test_crop_stays_inside_the_detected_content(letterboxed: Path) -> None:
    content = detect_content_window(letterboxed, 1920, 1080)
    window = center_crop_within(content, settings.output_width, settings.output_height)

    assert window.y >= content.y
    assert window.y + window.height <= content.y + content.height
    assert window.x >= content.x
    assert window.x + window.width <= content.x + content.width


def test_crop_within_a_full_frame_matches_a_plain_center_crop() -> None:
    content = CropWindow(x=0, y=0, width=1920, height=1080)
    window = center_crop_within(content, 1080, 1920)

    assert window.height == 1080
    assert window.width == 606
