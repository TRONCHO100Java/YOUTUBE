"""Lo que se le manda a YouTube, antes de mandárselo.

Los límites se aplican aquí y no se dejan a la API: que una subida entera se
rechace por un título de dos caracteres de más sería absurdo cuando el fichero
ya ha viajado.
"""

from __future__ import annotations

from pathlib import Path

from clipforge.services.publish.youtube import (
    CATEGORY_ID,
    MAX_DESCRIPTION,
    MAX_TAGS_CHARS,
    MAX_TITLE,
    UploadRequest,
    _body,
    _fit_tags,
)


def request(**overrides: object) -> UploadRequest:
    base = {
        "video": Path("clip.mp4"),
        "title": "Farmer slips into the mud",
        "description": "A farmer takes a tumble.",
        "tags": ("shorts", "farmfails"),
        "privacy": "private",
    }
    return UploadRequest(**{**base, **overrides})  # type: ignore[arg-type]


def test_the_video_carries_its_text_and_its_tags() -> None:
    body = _body(request())

    assert body["snippet"]["title"] == "Farmer slips into the mud"
    assert body["snippet"]["tags"] == ["shorts", "farmfails"]
    assert body["snippet"]["categoryId"] == CATEGORY_ID


def test_a_title_longer_than_youtube_allows_is_cut_here() -> None:
    body = _body(request(title="x" * 300))

    assert len(body["snippet"]["title"]) == MAX_TITLE


def test_a_description_longer_than_youtube_allows_is_cut_here() -> None:
    body = _body(request(description="x" * 10_000))

    assert len(body["snippet"]["description"]) == MAX_DESCRIPTION


def test_privacy_travels_as_asked() -> None:
    assert _body(request(privacy="unlisted"))["status"]["privacyStatus"] == "unlisted"


def test_an_unknown_privacy_falls_back_to_private() -> None:
    """Ante la duda, privado: publicar algo sin querer no tiene vuelta atrás."""
    assert _body(request(privacy="publico"))["status"]["privacyStatus"] == "private"


def test_nothing_here_is_made_for_kids() -> None:
    """Sin declararlo, YouTube pregunta por cada vídeo desde el panel."""
    assert _body(request())["status"]["selfDeclaredMadeForKids"] is False


def test_the_tags_that_fit_are_the_first_ones() -> None:
    """Las primeras son shorts y los nombres propios: son las que deben sobrevivir."""
    tags = tuple(f"tag{index:03d}" for index in range(200))
    fitted = _fit_tags(tags)

    assert fitted[0] == "tag000"
    assert sum(len(tag) + 1 for tag in fitted) <= MAX_TAGS_CHARS


def test_a_normal_set_of_tags_survives_whole() -> None:
    tags = ("shorts", "KaiCenat", "Motivation", "RoleModel", "Perseverance")

    assert _fit_tags(tags) == list(tags)
