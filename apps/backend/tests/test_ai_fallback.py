"""Respaldo por señales y resolución de candidatos visuales.

El comportamiento que se prueba aquí es el que impide que vuelva a pasar lo del
vídeo de comedia: que el pipeline se quede sin nada que ofrecer y marque el
proyecto como fallido después de descargar 379 MB.
"""

from __future__ import annotations

import pytest

from clipforge.core.config import settings
from clipforge.db.models.enums import CandidateSource, ContentProfile
from clipforge.services.ai.profiles import rules_for
from clipforge.services.ai.resolver import resolve_vision_candidates
from clipforge.services.ai.schema import candidate_model
from clipforge.services.ai.selector import suggestions_from_signals
from clipforge.services.ai.vision_analyzer import context_size
from clipforge.services.signals.base import MomentBlock

RULES = rules_for(ContentProfile.VISUAL)


def _block(start: float, end: float, *, score: float = 50.0) -> MomentBlock:
    return MomentBlock(
        start=start,
        end=end,
        energy=0.7,
        motion=0.4,
        peaks=2,
        cut_rate=1.5,
        score=score,
    )


def _raw(block: int, **overrides: object):  # type: ignore[no-untyped-def]
    payload: dict[str, object] = {
        "block": block,
        "trim_start": 0,
        "trim_end": 0,
        "title": "Un gag",
        "hook": "Alguien resbala",
        "reason": "Remate claro",
        "setup_score": 15,
        "payoff_score": 20,
        "reaction_score": 12,
        "universality_score": 13,
        "pacing_score": 10,
        "duration_score": 8,
    }
    payload.update(overrides)
    return candidate_model(RULES, vision=True).model_validate(payload)


# ------------------------------------------------------------------ respaldo
def test_signal_blocks_become_candidates() -> None:
    blocks = [_block(0, 30, score=80), _block(30, 60, score=60)]

    suggestions = suggestions_from_signals(blocks, limit=5)

    assert len(suggestions) == 2
    assert suggestions[0].start_time == 0.0
    assert suggestions[0].score == 80.0


def test_signal_candidates_are_marked_as_such() -> None:
    """El usuario tiene que poder ver que nadie ha juzgado estos tramos."""
    [suggestion] = suggestions_from_signals([_block(0, 30)], limit=1)

    assert suggestion.source is CandidateSource.SIGNAL
    assert suggestion.scores is None  # sin desglose: nadie los ha valorado
    assert suggestion.start_segment is None  # no vienen de la transcripción
    assert "señales" in (suggestion.reason or "")


def test_signal_candidates_are_named_by_their_position() -> None:
    [suggestion] = suggestions_from_signals([_block(125.0, 155.0)], limit=1)

    assert suggestion.title == "Moment at 2:05"


def test_the_limit_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_clips_per_project", 3)
    blocks = [_block(float(i) * 30, float(i + 1) * 30) for i in range(10)]

    assert len(suggestions_from_signals(blocks)) == 3


def test_without_blocks_there_is_nothing_to_propose() -> None:
    assert suggestions_from_signals([]) == []


# -------------------------------------------------------------------- visión
def test_the_model_picks_a_block_and_we_derive_the_times() -> None:
    blocks = [_block(100.0, 140.0), _block(200.0, 230.0)]

    [candidate] = resolve_vision_candidates([_raw(2)], blocks, RULES)

    assert candidate.start_time == 200.0
    assert candidate.end_time == 230.0
    assert candidate.source is CandidateSource.AI


def test_trims_are_applied() -> None:
    blocks = [_block(100.0, 140.0)]

    [candidate] = resolve_vision_candidates([_raw(1, trim_start=5, trim_end=3)], blocks, RULES)

    assert candidate.start_time == 105.0
    assert candidate.end_time == 137.0


def test_an_absurd_trim_cannot_produce_a_negative_clip() -> None:
    """Un modelo pidiendo recortar 40 s de un bloque de 30 no debe romper nada."""
    blocks = [_block(100.0, 130.0)]

    [candidate] = resolve_vision_candidates([_raw(1, trim_start=40, trim_end=40)], blocks, RULES)

    assert candidate.end_time > candidate.start_time
    assert candidate.duration >= RULES.min_duration


def test_a_clip_longer_than_the_maximum_is_trimmed() -> None:
    blocks = [_block(0.0, 200.0)]

    [candidate] = resolve_vision_candidates([_raw(1)], blocks, RULES)

    assert candidate.duration <= RULES.max_duration


@pytest.mark.parametrize("block", [0, 3, -1, 99])
def test_an_invented_block_is_rejected(block: int) -> None:
    blocks = [_block(0.0, 30.0), _block(30.0, 60.0)]

    assert resolve_vision_candidates([_raw(block)], blocks, RULES) == []


def test_a_candidate_without_title_is_rejected() -> None:
    assert resolve_vision_candidates([_raw(1, title="  ")], [_block(0, 30)], RULES) == []


def test_the_visual_rubric_lands_in_the_right_columns() -> None:
    """`payoff` comparte columna con `curiosity`: la mezcla no debe perderse."""
    [candidate] = resolve_vision_candidates([_raw(1)], [_block(0.0, 30.0)], RULES)

    assert candidate.scores is not None
    assert candidate.scores.curiosity == 20  # payoff_score
    assert candidate.scores.hook == 15  # setup_score
    assert candidate.scores.shareability == 0  # la rúbrica visual no la usa
    assert candidate.score == 78  # 15+20+12+13+10+8


def test_scores_out_of_range_are_clamped_to_the_visual_maximum() -> None:
    """`payoff` llega a 25 y `setup` a 20: no se pueden acotar con el mismo tope."""
    [candidate] = resolve_vision_candidates(
        [_raw(1, payoff_score=99, setup_score=99)], [_block(0.0, 30.0)], RULES
    )

    assert candidate.scores is not None
    assert candidate.scores.curiosity == 25
    assert candidate.scores.hook == 20


# ------------------------------------------------------- contexto de visión
def test_the_context_grows_with_the_number_of_frames() -> None:
    """Quedarse corto de contexto no degrada nada: Ollama devuelve un 400 seco.

    Con el valor fijo de 16.384 que había, tres bloques de cinco fotogramas ya
    no cabían y el análisis visual fallaba entero sin decir por qué.
    """
    assert context_size(5) < context_size(15)
    assert context_size(15) > 16384


def test_the_context_has_a_ceiling() -> None:
    """Pasarse solo reserva memoria de más, pero no hace falta ser absurdo."""
    assert context_size(1000) == context_size(10_000)
