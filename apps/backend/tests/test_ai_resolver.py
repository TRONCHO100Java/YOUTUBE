"""Validación de las propuestas del LLM contra segmentos reales.

Es la frontera que garantiza que el modelo no puede inventarse un timestamp:
solo elige índices, y aquí se comprueban contra la transcripción de verdad.
"""

from __future__ import annotations

import pytest

from clipforge.core.config import settings
from clipforge.db.models.enums import ContentProfile
from clipforge.services.ai.base import AnalysisSegment, AnalysisWindow
from clipforge.services.ai.profiles import rules_for
from clipforge.services.ai.resolver import resolve_candidates
from clipforge.services.ai.schema import candidate_model


@pytest.fixture(autouse=True)
def clip_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Límites fijos: los tests no deben depender del .env de la máquina."""
    monkeypatch.setattr(settings, "min_clip_duration", 20)
    monkeypatch.setattr(settings, "max_clip_duration", 90)
    # `rules_for` lee los ajustes en cada llamada, así que basta con parchearlos.


def _window(count: int = 20, *, seconds: float = 10.0) -> AnalysisWindow:
    return AnalysisWindow(
        number=1,
        segments=[
            AnalysisSegment(index=i, start=i * seconds, end=(i + 1) * seconds, text=f"texto {i}")
            for i in range(count)
        ],
    )


def _rules():  # type: ignore[no-untyped-def]
    return rules_for(ContentProfile.TALKING)


def _raw(start: int, end: int, **overrides: object):  # type: ignore[no-untyped-def]
    payload: dict[str, object] = {
        "start_segment": start,
        "end_segment": end,
        "title": "Un título",
        "hook": "Un gancho",
        "reason": "Un motivo",
        "hook_score": 15,
        "curiosity_score": 15,
        "emotion_score": 10,
        "clarity_score": 10,
        "value_score": 10,
        "shareability_score": 5,
        "duration_score": 3,
    }
    payload.update(overrides)
    return candidate_model(_rules()).model_validate(payload)


def test_timestamps_come_from_the_segments_not_the_model() -> None:
    window = _window()
    [candidate] = resolve_candidates([_raw(2, 5)], window, _rules())

    assert candidate.start_time == 20.0  # inicio del segmento 2
    assert candidate.end_time == 60.0  # fin del segmento 5
    assert candidate.start_segment == 2
    assert candidate.end_segment == 5


def test_scores_are_summed_by_us() -> None:
    [candidate] = resolve_candidates([_raw(0, 4)], _window(), _rules())
    assert candidate.score == 15 + 15 + 10 + 10 + 10 + 5 + 3


def test_excerpt_is_built_from_the_real_text() -> None:
    [candidate] = resolve_candidates([_raw(1, 3)], _window(), _rules())
    assert candidate.transcript_excerpt == "texto 1 texto 2 texto 3"


def test_inverted_range_is_repaired() -> None:
    [candidate] = resolve_candidates([_raw(6, 2)], _window(), _rules())
    assert (candidate.start_segment, candidate.end_segment) == (2, 6)


@pytest.mark.parametrize(("start", "end"), [(99, 100), (-3, 2), (0, 999)])
def test_invented_indices_are_rejected(start: int, end: int) -> None:
    assert resolve_candidates([_raw(start, end)], _window(), _rules()) == []


def test_scores_out_of_range_are_clamped() -> None:
    [candidate] = resolve_candidates(
        [_raw(0, 4, hook_score=99, curiosity_score=-5, duration_score=50)],
        _window(),
        _rules(),
    )
    assert candidate.scores.hook == 20
    assert candidate.scores.curiosity == 0
    assert candidate.scores.duration == 5


def test_too_long_a_clip_is_trimmed_from_the_end() -> None:
    """Recortar es mejor que descartar un buen momento por pasarse de largo."""
    [candidate] = resolve_candidates([_raw(0, 19)], _window(), _rules())  # 200 s propuestos

    assert candidate.duration <= 90
    assert candidate.start_segment == 0


def test_too_short_a_clip_is_extended() -> None:
    [candidate] = resolve_candidates([_raw(3, 3)], _window(), _rules())  # 10 s propuestos

    assert candidate.duration >= 20
    assert candidate.start_segment == 3


def test_clip_that_cannot_reach_the_minimum_is_rejected() -> None:
    """Sin segmentos que añadir, un clip demasiado corto no se puede salvar."""
    tiny = AnalysisWindow(
        number=1,
        segments=[AnalysisSegment(index=0, start=0.0, end=5.0, text="hola")],
    )
    assert resolve_candidates([_raw(0, 0)], tiny, _rules()) == []


def test_candidate_without_title_is_rejected() -> None:
    assert resolve_candidates([_raw(0, 4, title="   ")], _window(), _rules()) == []


def test_valid_and_invalid_candidates_are_processed_independently() -> None:
    resolved = resolve_candidates([_raw(0, 4), _raw(500, 600), _raw(6, 10)], _window(), _rules())
    assert len(resolved) == 2
