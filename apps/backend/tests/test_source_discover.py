"""Buscar vídeos y leer canales sin API de YouTube.

Lo que llega de fuera —el RSS de un canal, la lista de yt-dlp— se trata igual
que la respuesta de un LLM: puede venir incompleta, desordenada o rota, y
ninguna de las tres cosas puede dejar de vigilar un canal.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from clipforge.core.errors import ExternalToolError, ValidationError
from clipforge.services.source.discover import (
    DiscoveryFilters,
    VideoResult,
    channel_feed,
    parse_feed,
)

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <title>Kai Cenat Live</title>
  <entry>
    <yt:videoId>CWxYHlXbhmg</yt:videoId>
    <yt:channelId>UC4orTSLcC0JVsj2aOCZC6QA</yt:channelId>
    <title>KAI CENAT TRAINS AT THE MOST DANGEROUS GYM</title>
    <author><name>Kai Cenat Live</name></author>
    <published>2026-08-27T10:00:00+00:00</published>
    <media:group>
      <media:thumbnail url="https://i.ytimg.com/vi/CWxYHlXbhmg/hqdefault.jpg"/>
    </media:group>
  </entry>
  <entry>
    <yt:videoId>MsyQgyJbjns</yt:videoId>
    <yt:channelId>UC4orTSLcC0JVsj2aOCZC6QA</yt:channelId>
    <title>DIAMOND GYM GOES CRAZY</title>
    <author><name>Kai Cenat Live</name></author>
    <published>2026-09-04T18:30:00+00:00</published>
  </entry>
</feed>"""


def video(**overrides: object) -> VideoResult:
    base = {
        "video_id": "CWxYHlXbhmg",
        "title": "Un vídeo",
        "url": "https://www.youtube.com/watch?v=CWxYHlXbhmg",
        "duration": 600.0,
        "view_count": 50_000,
    }
    return VideoResult(**{**base, **overrides})  # type: ignore[arg-type]


# ---------------------------------------------------------------------- feed
def test_the_feed_gives_back_its_videos() -> None:
    videos = parse_feed(FEED)

    assert len(videos) == 2
    assert videos[0].video_id == "MsyQgyJbjns"
    assert videos[0].url == "https://www.youtube.com/watch?v=MsyQgyJbjns"


def test_the_newest_video_comes_first() -> None:
    """El orden importa: la marca de agua se calcula sobre el más reciente."""
    videos = parse_feed(FEED)

    assert videos[0].published_at is not None
    assert videos[1].published_at is not None
    assert videos[0].published_at > videos[1].published_at


def test_a_video_without_its_own_thumbnail_still_has_one() -> None:
    videos = parse_feed(FEED)

    assert videos[0].thumbnail is None
    assert videos[1].thumbnail is not None


def test_an_entry_without_id_does_not_break_the_rest() -> None:
    """Un canal que publica algo raro no puede dejar de vigilarse por eso."""
    broken = FEED.replace("<yt:videoId>CWxYHlXbhmg</yt:videoId>", "")

    assert len(parse_feed(broken)) == 1


def test_something_that_is_not_even_xml_is_an_error() -> None:
    with pytest.raises(ExternalToolError):
        parse_feed("<html><p>Error de YouTube")


def test_xml_without_entries_is_simply_no_videos() -> None:
    """Un feed vacío no es un fallo: es un canal que no ha publicado nada."""
    assert parse_feed('<feed xmlns="http://www.w3.org/2005/Atom"></feed>') == []


def test_an_id_that_is_not_a_channel_never_reaches_the_network() -> None:
    with pytest.raises(ValidationError):
        channel_feed("no-soy-un-canal")


# ------------------------------------------------------------------- filtros
def test_without_filters_everything_passes() -> None:
    assert DiscoveryFilters().accepts(video()) is True


def test_a_video_that_is_too_short_is_left_out() -> None:
    assert DiscoveryFilters(min_duration=900).accepts(video(duration=600.0)) is False


def test_a_video_that_is_too_long_is_left_out() -> None:
    """Bajar tres horas de vídeo para sacar cinco clips no compensa."""
    assert DiscoveryFilters(max_duration=1800).accepts(video(duration=10_800.0)) is False


def test_a_video_nobody_watched_is_left_out() -> None:
    assert DiscoveryFilters(min_views=100_000).accepts(video(view_count=200)) is False


def test_what_we_do_not_know_does_not_disqualify() -> None:
    """YouTube no siempre da las vistas: descartar por eso perdería vídeos buenos."""
    assert DiscoveryFilters(min_views=100_000).accepts(video(view_count=None)) is True
    assert DiscoveryFilters(min_duration=900).accepts(video(duration=None)) is True


def test_the_limits_are_inclusive() -> None:
    assert DiscoveryFilters(min_duration=600).accepts(video(duration=600.0)) is True
    assert DiscoveryFilters(max_duration=600).accepts(video(duration=600.0)) is True
    assert DiscoveryFilters(min_views=50_000).accepts(video(view_count=50_000)) is True


def test_the_filters_add_up() -> None:
    rules = DiscoveryFilters(min_duration=300, max_duration=1800, min_views=10_000)

    assert rules.accepts(video(duration=900.0, view_count=50_000)) is True
    assert rules.accepts(video(duration=900.0, view_count=500)) is False
    assert rules.accepts(video(duration=7200.0, view_count=50_000)) is False


# -------------------------------------------------------------- marca de agua
def test_the_watermark_is_what_stops_a_new_channel_queueing_fifteen_videos() -> None:
    """Vigilar un canal es querer lo que publique a partir de ahora."""
    from clipforge.worker.tasks.ingest import _is_new

    videos = parse_feed(FEED)
    watermark = max(v.published_at for v in videos if v.published_at)

    assert all(_is_new(v, watermark) is False for v in videos)


def test_a_video_published_after_the_watermark_is_new() -> None:
    from clipforge.worker.tasks.ingest import _is_new

    watermark = datetime(2026, 9, 1, tzinfo=UTC)
    videos = parse_feed(FEED)

    assert [v.video_id for v in videos if _is_new(v, watermark)] == ["MsyQgyJbjns"]


def test_without_a_watermark_everything_is_new() -> None:
    from clipforge.worker.tasks.ingest import _is_new

    assert all(_is_new(v, None) for v in parse_feed(FEED))


def test_a_video_without_a_date_is_not_queued_over_and_over() -> None:
    """El feed trae siempre los mismos quince: sin fecha, no hay forma de saber."""
    from clipforge.worker.tasks.ingest import _is_new

    assert _is_new(video(published_at=None), datetime(2026, 9, 1, tzinfo=UTC)) is False
