"""Traducción de errores y metadatos de yt-dlp (sin tocar la red)."""

from __future__ import annotations

import pytest
from yt_dlp.utils import DownloadError

from clipforge.core.errors import (
    ExternalToolError,
    SourceTooLongError,
    SourceUnavailableError,
)
from clipforge.services.download.base import SourceMetadata
from clipforge.services.download.ytdlp import YtDlpDownloader, _to_metadata


@pytest.mark.parametrize(
    ("message", "expected_fragment"),
    [
        ("ERROR: [youtube] abc: Private video. Sign in if you've been granted", "privado"),
        ("ERROR: [youtube] abc: Video unavailable", "no está disponible"),
        # Redacción real observada al pedir un id inexistente.
        ("ERROR: [youtube] aaaaaaaaaaa: This video is unavailable", "no está disponible"),
        # Mensaje literal observado en producción con un id inexistente.
        ("ERROR: [youtube] aaaaaaaaaaa: This video is unavailable", "no está disponible"),
        ("ERROR: This video has been removed by the uploader", "eliminado"),
        ("ERROR: Join this channel to get access to members-only content", "miembros"),
        ("ERROR: Sign in to confirm your age", "restricción de edad"),
        ("ERROR: The uploader has not made this video available in your country", "país"),
        ("ERROR: Sign in to confirm you're not a bot", "verificación"),
    ],
)
def test_unavailable_sources_become_domain_errors(message: str, expected_fragment: str) -> None:
    translated = YtDlpDownloader()._translate(DownloadError(message))
    assert isinstance(translated, SourceUnavailableError)
    assert expected_fragment in translated.message


def test_unknown_failures_become_external_tool_errors() -> None:
    translated = YtDlpDownloader()._translate(DownloadError("ERROR: unable to resolve host"))
    assert isinstance(translated, ExternalToolError)
    # El mensaje original se conserva para poder diagnosticar.
    assert "unable to resolve host" in translated.details["ytdlp_error"]


def test_rejects_videos_over_the_duration_limit() -> None:
    long_video = SourceMetadata(title="t", author="a", duration=99_999, thumbnail_url=None)
    with pytest.raises(SourceTooLongError):
        YtDlpDownloader()._assert_duration_allowed(long_video)


def test_accepts_videos_within_the_limit_and_unknown_durations() -> None:
    downloader = YtDlpDownloader()
    downloader._assert_duration_allowed(
        SourceMetadata(title="t", author="a", duration=600, thumbnail_url=None)
    )
    downloader._assert_duration_allowed(
        SourceMetadata(title="t", author="a", duration=None, thumbnail_url=None)
    )


def test_maps_metadata_and_tolerates_missing_fields() -> None:
    full = _to_metadata(
        {"title": "Mi vídeo", "uploader": "Canal", "duration": 123, "thumbnail": "http://x/y.jpg"}
    )
    assert (full.title, full.author, full.duration) == ("Mi vídeo", "Canal", 123.0)

    empty = _to_metadata({})
    assert (empty.title, empty.author, empty.duration, empty.thumbnail_url) == (
        None,
        None,
        None,
        None,
    )


def test_falls_back_to_channel_when_uploader_is_missing() -> None:
    assert _to_metadata({"channel": "Otro canal"}).author == "Otro canal"
