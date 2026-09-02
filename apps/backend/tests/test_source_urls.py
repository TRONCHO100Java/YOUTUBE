"""Validación de URLs de origen: es la frontera de confianza del sistema."""

from __future__ import annotations

import pytest

from clipforge.core.errors import UnsupportedSourceError
from clipforge.db.models.enums import SourceType
from clipforge.services.source.urls import validate_source_url

VIDEO_ID = "dQw4w9WgXcQ"
CANONICAL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"http://youtube.com/watch?v={VIDEO_ID}",
        f"https://m.youtube.com/watch?v={VIDEO_ID}",
        f"https://music.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}",
        f"  https://youtu.be/{VIDEO_ID}  ",
        f"www.youtube.com/watch?v={VIDEO_ID}",
    ],
)
def test_accepts_every_youtube_url_shape(url: str) -> None:
    ref = validate_source_url(url)
    assert ref.video_id == VIDEO_ID
    assert ref.source_type is SourceType.YOUTUBE


def test_normalizes_to_a_canonical_url() -> None:
    """Listas, timestamps y parámetros de tracking se descartan."""
    messy = f"https://www.youtube.com/watch?v={VIDEO_ID}&list=PL123&t=42s&si=abc"
    assert validate_source_url(messy).url == CANONICAL


def test_different_shapes_produce_the_same_canonical_url() -> None:
    assert validate_source_url(f"https://youtu.be/{VIDEO_ID}").url == CANONICAL
    assert validate_source_url(f"https://m.youtube.com/watch?v={VIDEO_ID}").url == CANONICAL


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("", "vacía"),
        ("   ", "solo espacios"),
        ("https://vimeo.com/12345678", "host no permitido"),
        ("https://evil.com/watch?v=dQw4w9WgXcQ", "host no permitido aunque imite la ruta"),
        ("file:///C:/Windows/System32", "esquema no permitido"),
        ("javascript:alert(1)", "esquema no permitido"),
        (f"https://user:pass@youtube.com/watch?v={VIDEO_ID}", "credenciales embebidas"),
        ("https://www.youtube.com/watch?v=corto", "id con formato inválido"),
        ("https://www.youtube.com/", "sin identificador"),
        ("https://www.youtube.com/results?search_query=test", "no es un vídeo"),
        (f"https://www.youtube.com.evil.com/watch?v={VIDEO_ID}", "sufijo de host malicioso"),
    ],
)
def test_rejects_invalid_sources(url: str, reason: str) -> None:
    with pytest.raises(UnsupportedSourceError):
        validate_source_url(url)


def test_rejects_absurdly_long_urls() -> None:
    with pytest.raises(UnsupportedSourceError, match="supera"):
        validate_source_url("https://www.youtube.com/watch?v=" + "a" * 3000)
