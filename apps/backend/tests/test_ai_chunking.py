"""Troceado de la transcripción en ventanas solapadas."""

from __future__ import annotations

from itertools import pairwise

import pytest

from clipforge.services.ai.base import AnalysisSegment
from clipforge.services.ai.chunking import build_windows


def _segments(count: int, *, seconds: float = 10.0) -> list[AnalysisSegment]:
    return [
        AnalysisSegment(index=i, start=i * seconds, end=(i + 1) * seconds, text=f"s{i}")
        for i in range(count)
    ]


def test_short_transcript_fits_in_one_window() -> None:
    windows = build_windows(_segments(5), window_seconds=300, overlap_seconds=60)
    assert len(windows) == 1
    assert [s.index for s in windows[0].segments] == [0, 1, 2, 3, 4]
    assert windows[0].number == 1


def test_empty_transcript_produces_no_windows() -> None:
    assert build_windows([], window_seconds=300, overlap_seconds=60) == []


def test_windows_cover_every_segment() -> None:
    segments = _segments(60)  # 600 s
    windows = build_windows(segments, window_seconds=120, overlap_seconds=30)

    covered = {s.index for window in windows for s in window.segments}
    assert covered == {s.index for s in segments}


def test_consecutive_windows_overlap() -> None:
    """El solape es lo que evita perder un buen momento partido entre ventanas."""
    windows = build_windows(_segments(60), window_seconds=120, overlap_seconds=30)

    assert len(windows) > 1
    for previous, current in pairwise(windows):
        shared = {s.index for s in previous.segments} & {s.index for s in current.segments}
        assert shared, "dos ventanas consecutivas deben compartir segmentos"


def test_windows_respect_the_requested_duration() -> None:
    windows = build_windows(_segments(60), window_seconds=120, overlap_seconds=30)
    # El último segmento puede sobresalir del límite, de ahí el margen.
    for window in windows:
        assert window.duration <= 120 + 10


def test_windows_are_numbered_in_order() -> None:
    windows = build_windows(_segments(60), window_seconds=120, overlap_seconds=30)
    assert [w.number for w in windows] == list(range(1, len(windows) + 1))


def test_segment_longer_than_the_window_is_not_dropped() -> None:
    """Un segmento gigante debe seguir analizándose, aunque no quepa."""
    segments = [
        AnalysisSegment(index=0, start=0.0, end=500.0, text="monólogo"),
        AnalysisSegment(index=1, start=500.0, end=510.0, text="siguiente"),
    ]
    windows = build_windows(segments, window_seconds=120, overlap_seconds=30)

    covered = {s.index for window in windows for s in window.segments}
    assert covered == {0, 1}


def test_zero_overlap_is_allowed() -> None:
    windows = build_windows(_segments(30), window_seconds=100, overlap_seconds=0)
    covered = {s.index for window in windows for s in window.segments}
    assert covered == set(range(30))


def test_unordered_input_is_sorted() -> None:
    segments = list(reversed(_segments(10)))
    windows = build_windows(segments, window_seconds=1000, overlap_seconds=0)
    assert [s.index for s in windows[0].segments] == list(range(10))


@pytest.mark.parametrize(
    ("window_seconds", "overlap_seconds"),
    [(0, 0), (-10, 0), (100, 100), (100, 150), (100, -1)],
)
def test_invalid_parameters_are_rejected(window_seconds: float, overlap_seconds: float) -> None:
    with pytest.raises(ValueError):
        build_windows(_segments(5), window_seconds=window_seconds, overlap_seconds=overlap_seconds)
