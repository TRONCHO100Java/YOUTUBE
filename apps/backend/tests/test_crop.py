"""Geometría del recorte vertical."""

from __future__ import annotations

import pytest

from clipforge.core.errors import ExternalToolError
from clipforge.services.video.crop import center_crop

VERTICAL = (1080, 1920)


def test_horizontal_source_keeps_full_height_and_crops_the_sides() -> None:
    window = center_crop(1920, 1080, *VERTICAL)

    assert window.height == 1080
    assert window.width == 606  # 1080 * 9/16, redondeado a par
    assert window.y == 0
    assert window.x == (1920 - 606) // 2 // 2 * 2


def test_already_vertical_source_is_not_cropped_sideways() -> None:
    window = center_crop(1080, 1920, *VERTICAL)

    assert (window.width, window.height) == (1080, 1920)
    assert (window.x, window.y) == (0, 0)


def test_taller_than_target_source_crops_top_and_bottom() -> None:
    """Un vídeo más estrecho que 9:16 se recorta en altura, no en anchura."""
    window = center_crop(1080, 2400, *VERTICAL)

    assert window.width == 1080
    assert window.height == 1920
    assert window.y > 0


def test_square_source_is_cropped_sideways() -> None:
    """Un cuadrado es más ancho que 9:16, así que se recorta por los lados."""
    window = center_crop(1000, 1000, *VERTICAL)

    assert window.height == 1000
    assert window.width == 562  # 1000 * 9/16, redondeado a par
    assert window.y == 0
    assert window.x > 0


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (1280, 720), (640, 480), (1080, 1920), (3840, 2160), (1001, 999)],
)
def test_dimensions_are_always_even(width: int, height: int) -> None:
    """H.264 exige dimensiones pares; un impar hace fallar el codificador."""
    window = center_crop(width, height, *VERTICAL)

    assert window.width % 2 == 0
    assert window.height % 2 == 0
    assert window.x % 2 == 0
    assert window.y % 2 == 0


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (1280, 720), (640, 480), (3840, 2160)],
)
def test_window_never_exceeds_the_source(width: int, height: int) -> None:
    window = center_crop(width, height, *VERTICAL)

    assert window.x + window.width <= width
    assert window.y + window.height <= height


def test_filter_string_matches_ffmpeg_syntax() -> None:
    window = center_crop(1920, 1080, *VERTICAL)
    assert window.to_filter() == f"crop={window.width}:{window.height}:{window.x}:{window.y}"


@pytest.mark.parametrize(
    ("args"),
    [(0, 1080, 1080, 1920), (1920, 0, 1080, 1920), (1920, 1080, 0, 1920), (-10, 100, 100, 100)],
)
def test_invalid_dimensions_are_rejected(args: tuple[int, int, int, int]) -> None:
    with pytest.raises(ExternalToolError):
        center_crop(*args)
