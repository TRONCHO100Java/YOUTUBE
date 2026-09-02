"""Deduplicación y ranking global de candidatos."""

from __future__ import annotations

from clipforge.services.ai.base import ClipScores, ClipSuggestion
from clipforge.services.ai.ranking import (
    deduplicate,
    overlap_ratio,
    rank,
    select_top,
)


def _suggestion(
    start: float, end: float, *, hook: float = 10, total_extra: float = 0
) -> ClipSuggestion:
    scores = ClipScores(
        hook=hook,
        curiosity=total_extra,
        emotion=0,
        clarity=0,
        value=0,
        shareability=0,
        duration=0,
    )
    return ClipSuggestion(
        start_segment=int(start),
        end_segment=int(end),
        start_time=start,
        end_time=end,
        title=f"clip {start}-{end}",
        hook=None,
        reason=None,
        scores=scores,
    )


def test_scores_sum_to_the_total() -> None:
    scores = ClipScores(
        hook=19, curiosity=18, emotion=16, clarity=14, value=14, shareability=8, duration=3
    )
    assert scores.total == 92


def test_total_is_capped_at_100() -> None:
    scores = ClipScores(
        hook=20, curiosity=20, emotion=15, clarity=15, value=15, shareability=10, duration=5
    )
    assert scores.total == 100


def test_overlap_ratio_is_relative_to_the_shorter_clip() -> None:
    long_clip = _suggestion(0, 100)
    short_clip = _suggestion(90, 110)
    # Solapan 10 s; el más corto dura 20 s → 0.5
    assert overlap_ratio(long_clip, short_clip) == 0.5


def test_disjoint_clips_do_not_overlap() -> None:
    assert overlap_ratio(_suggestion(0, 30), _suggestion(60, 90)) == 0.0


def test_touching_clips_do_not_overlap() -> None:
    assert overlap_ratio(_suggestion(0, 30), _suggestion(30, 60)) == 0.0


def test_deduplicate_keeps_the_best_of_two_overlapping_clips() -> None:
    weak = _suggestion(0, 40, total_extra=1)
    strong = _suggestion(5, 45, total_extra=15)

    kept = deduplicate([weak, strong])

    assert len(kept) == 1
    assert kept[0] is strong


def test_deduplicate_keeps_adjacent_distinct_clips() -> None:
    kept = deduplicate([_suggestion(0, 40), _suggestion(45, 85)])
    assert len(kept) == 2


def test_ranking_is_by_score_descending() -> None:
    low = _suggestion(0, 40, total_extra=2)
    high = _suggestion(100, 140, total_extra=18)

    assert [c.score for c in rank([low, high])] == [high.score, low.score]


def test_ties_break_deterministically_by_hook_then_time() -> None:
    """Sin desempate, dos ejecuciones iguales darían rankings distintos."""
    early_weak_hook = _suggestion(0, 40, hook=5, total_extra=10)
    late_strong_hook = _suggestion(200, 240, hook=15, total_extra=0)
    assert early_weak_hook.score == late_strong_hook.score

    ordered = rank([early_weak_hook, late_strong_hook])
    assert ordered[0] is late_strong_hook

    # Y el orden no depende del orden de entrada.
    assert rank([late_strong_hook, early_weak_hook]) == ordered


def test_select_top_deduplicates_ranks_and_limits() -> None:
    candidates = [
        _suggestion(0, 40, total_extra=20),
        _suggestion(3, 43, total_extra=5),  # duplicado del anterior
        _suggestion(100, 140, total_extra=15),
        _suggestion(200, 240, total_extra=10),
    ]

    selected = select_top(candidates, limit=2)

    assert len(selected) == 2
    assert [c.start_time for c in selected] == [0, 100]


def test_select_top_with_zero_limit_returns_nothing() -> None:
    assert select_top([_suggestion(0, 40)], limit=0) == []


def test_select_top_of_empty_input_is_empty() -> None:
    assert select_top([], limit=5) == []
