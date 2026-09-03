"""Generación de subtítulos recortados a la ventana de un clip."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from clipforge.services.subtitles import SourceSegment, build_cues, render_srt, write_srt
from clipforge.services.subtitles.srt import (
    MAX_CHARS_PER_LINE,
    MAX_LINES,
    split_into_lines,
    wrap_text,
)


def _segments() -> list[SourceSegment]:
    return [
        SourceSegment(start=0.0, end=10.0, text="Antes del clip"),
        SourceSegment(start=10.0, end=14.0, text="Primera frase"),
        SourceSegment(start=14.0, end=18.0, text="Segunda frase"),
        SourceSegment(start=18.0, end=25.0, text="Tercera frase"),
        SourceSegment(start=40.0, end=45.0, text="Despues del clip"),
    ]


def test_only_segments_inside_the_window_are_kept() -> None:
    cues = build_cues(_segments(), 10.0, 25.0)
    assert [cue.text for cue in cues] == ["Primera frase", "Segunda frase", "Tercera frase"]


def test_times_are_relative_to_the_clip_start() -> None:
    """Un subtítulo con tiempos absolutos aparecería fuera del clip."""
    cues = build_cues(_segments(), 10.0, 25.0)

    assert cues[0].start == 0.0
    assert cues[0].end == 4.0
    assert cues[1].start == 4.0


def test_partially_overlapping_segments_are_trimmed_not_dropped() -> None:
    """Perder la primera frase es peor que un subtítulo entrando a medias."""
    cues = build_cues(_segments(), 12.0, 20.0)

    assert cues, "el segmento que empieza antes del clip debe conservarse"
    assert cues[0].start == 0.0
    assert cues[0].text == "Primera frase"


def test_segments_outside_the_window_are_excluded() -> None:
    cues = build_cues(_segments(), 10.0, 25.0)
    assert all("del clip" not in cue.text for cue in cues)


def test_empty_window_produces_no_cues() -> None:
    assert build_cues(_segments(), 30.0, 35.0) == []


def test_blank_segments_are_ignored() -> None:
    segments = [SourceSegment(start=0.0, end=5.0, text="   ")]
    assert build_cues(segments, 0.0, 5.0) == []


def test_cues_never_overlap() -> None:
    """Dos subtítulos superpuestos se pisan en pantalla."""
    segments = [
        SourceSegment(start=0.0, end=6.0, text="Uno"),
        SourceSegment(start=3.0, end=9.0, text="Dos"),
        SourceSegment(start=5.0, end=12.0, text="Tres"),
    ]
    cues = build_cues(segments, 0.0, 12.0)

    for previous, current in pairwise(cues):
        assert current.start >= previous.end


def test_very_short_cues_are_dropped() -> None:
    """Un subtítulo de una décima parpadea y no se lee."""
    segments = [SourceSegment(start=0.0, end=0.2, text="Fugaz")]
    assert build_cues(segments, 0.0, 10.0) == []


def test_lines_stay_short_enough_to_read_on_mobile() -> None:
    wrapped = wrap_text("Esta es una frase bastante larga que no cabe en una sola linea corta")

    lines = wrapped.split("\n")
    assert len(lines) <= 2
    assert all(line for line in lines)


def test_short_text_is_not_wrapped() -> None:
    assert wrap_text("Hola mundo") == "Hola mundo"
    assert len("Hola mundo") <= MAX_CHARS_PER_LINE


def test_srt_format_is_valid() -> None:
    cues = build_cues(_segments(), 10.0, 25.0)
    content = render_srt(cues)

    assert content.startswith("1\n")
    assert "00:00:00,000 --> 00:00:04,000" in content
    assert "-->" in content


def test_srt_timestamps_include_hours() -> None:
    segments = [SourceSegment(start=0.0, end=4000.0, text="Muy tarde")]
    content = render_srt(build_cues(segments, 3661.0, 3700.0))
    assert "00:00:00,000 --> " in content


def test_written_file_is_utf8() -> None:
    """libass necesita UTF-8; en cp1252 los acentos salen rotos."""
    cues = build_cues([SourceSegment(start=0.0, end=5.0, text="Acción y ñandú")], 0.0, 5.0)
    destination = Path.cwd() / "unused.srt"
    written = write_srt(cues, destination)
    try:
        assert "Acción y ñandú" in written.read_text(encoding="utf-8")
    finally:
        written.unlink()


def test_write_creates_missing_directories(tmp_path: Path) -> None:
    cues = build_cues([SourceSegment(start=0.0, end=5.0, text="Hola")], 0.0, 5.0)
    destination = tmp_path / "nueva" / "carpeta" / "clip.srt"

    assert write_srt(cues, destination).is_file()


@pytest.mark.parametrize("clip_start", [0.0, 10.0, 123.456])
def test_first_cue_never_starts_before_zero(clip_start: float) -> None:
    segments = [SourceSegment(start=clip_start - 5, end=clip_start + 5, text="Texto")]
    cues = build_cues(segments, clip_start, clip_start + 10)

    assert cues[0].start >= 0.0


LONG_SEGMENT = (
    "Sigue adelante y sigue luchando, no permitas que el miedo al fracaso "
    "y el atractivo de ir a lo seguro en la vida te atrape para siempre"
)


def test_a_long_segment_becomes_several_cues_over_time() -> None:
    """Apilado en dos líneas, el texto tapaba medio vídeo."""
    cues = build_cues([SourceSegment(start=0.0, end=12.0, text=LONG_SEGMENT)], 0.0, 12.0)

    assert len(cues) > 1
    for previous, current in pairwise(cues):
        assert current.start >= previous.end


def test_every_line_fits_the_mobile_width() -> None:
    cues = build_cues([SourceSegment(start=0.0, end=12.0, text=LONG_SEGMENT)], 0.0, 12.0)

    for cue in cues:
        lines = cue.text.splitlines()
        assert len(lines) <= MAX_LINES
        assert all(len(line) <= MAX_CHARS_PER_LINE for line in lines), cue.text


def test_split_keeps_the_words_in_order() -> None:
    chunks = split_into_lines(LONG_SEGMENT)
    assert " ".join(chunks) == LONG_SEGMENT


def test_split_leaves_short_text_alone() -> None:
    assert split_into_lines("Hola mundo") == ["Hola mundo"]


def test_cues_stay_inside_the_segment_window() -> None:
    cues = build_cues([SourceSegment(start=5.0, end=17.0, text=LONG_SEGMENT)], 5.0, 17.0)

    assert cues[0].start >= 0.0
    assert cues[-1].end <= 12.0
