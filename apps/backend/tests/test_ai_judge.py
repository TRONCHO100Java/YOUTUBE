"""El juez elige, y lo que elige se publica.

Es la decisión más cara de equivocar del pipeline: por debajo de aquí solo hay
render. Todo lo que devuelve el modelo se acota, y ningún fallo suyo puede
dejar un proyecto sin clips.
"""

from __future__ import annotations

import json

from clipforge.core.errors import ExternalToolError
from clipforge.services.ai.base import AnalysisContext, ClipSuggestion
from clipforge.services.ai.judge import (
    CRITERIA,
    MAX_SCORE,
    MERITS,
    MIN_PUBLISHABLE,
    PENALTIES,
    Verdict,
    judge_candidates,
    parse_verdicts,
)

CONTEXT = AnalysisContext(title="Among Us lobby", author="Kai Cenat")


def candidate(start: float = 10.0, end: float = 40.0, title: str = "Un momento") -> ClipSuggestion:
    return ClipSuggestion(
        start_segment=None,
        end_segment=None,
        start_time=start,
        end_time=end,
        title=title,
        hook=None,
        reason="Lo eligió el detector.",
        scores=None,
        transcript_excerpt="lo que se dice",
        signal_score=50.0,
    )


def verdict(**scores: int) -> dict[str, int]:
    """Un veredicto completo, con ceros en lo que no se indique."""
    return {criterion.key: scores.get(criterion.key, 0) for criterion in CRITERIA}


def answer(*per_clip: dict[str, int]) -> str:
    clips = [
        {"clip": number, "reason": "porque sí", **scores}
        for number, scores in enumerate(per_clip, start=1)
    ]
    return json.dumps({"clips": clips})


def perfect() -> dict[str, int]:
    return verdict(**{c.key: c.maximum for c in MERITS})


# ------------------------------------------------------------------ la nota
def test_the_total_is_the_merits_minus_the_penalties() -> None:
    result = Verdict(scores=verdict(hook=18, payoff=15, dead_time=10), reason="")

    assert result.merit == 33
    assert result.penalty == 10
    assert result.total == 23.0


def test_a_flawless_clip_scores_a_hundred() -> None:
    assert Verdict(scores=perfect(), reason="").total == float(MAX_SCORE)
    assert MAX_SCORE == 100


def test_the_penalties_cannot_push_the_score_below_zero() -> None:
    result = Verdict(scores=verdict(hook=2, **{c.key: c.maximum for c in PENALTIES}), reason="")

    assert result.total == 0.0


def test_the_system_adds_up_not_the_model() -> None:
    """Los LLM se equivocan sumando y un total incoherente no se puede depurar."""
    content = answer({**perfect(), "total": 3})

    (result,) = parse_verdicts(content, offset=0, size=1).values()

    assert result.total == float(MAX_SCORE)


# ------------------------------------------------------------- la respuesta
def test_a_score_over_its_maximum_is_clamped() -> None:
    (result,) = parse_verdicts(answer(verdict(hook=999)), offset=0, size=1).values()

    assert result.scores["hook"] == 18


def test_a_negative_score_is_clamped_too() -> None:
    (result,) = parse_verdicts(answer(verdict(hook=-5)), offset=0, size=1).values()

    assert result.scores["hook"] == 0


def test_a_score_that_is_not_a_number_counts_as_zero() -> None:
    content = json.dumps({"clips": [{"clip": 1, "reason": "", **verdict(), "hook": "mucho"}]})

    (result,) = parse_verdicts(content, offset=0, size=1).values()

    assert result.scores["hook"] == 0


def test_a_clip_number_outside_the_batch_is_ignored() -> None:
    """El modelo numera dentro de su tanda; inventarse uno no puede colarse."""
    verdicts = parse_verdicts(answer(*[verdict()] * 3), offset=0, size=1)

    assert list(verdicts) == [0]


def test_the_batch_offset_lands_on_the_right_candidate() -> None:
    verdicts = parse_verdicts(answer(verdict(hook=10)), offset=10, size=5)

    assert list(verdicts) == [10]


def test_a_response_wrapped_in_a_code_fence_still_parses() -> None:
    fenced = f"```json\n{answer(verdict(hook=5))}\n```"

    assert list(parse_verdicts(fenced, offset=0, size=1)) == [0]


def test_something_that_is_not_the_agreed_shape_is_an_error() -> None:
    try:
        parse_verdicts('{"veredictos": []}', offset=0, size=1)
    except ExternalToolError:
        return
    raise AssertionError("debería haber fallado")


# ------------------------------------------------------------------ elegir
def test_the_best_judged_clip_wins_even_if_the_detector_disagreed() -> None:
    """Es la razón de existir del juez: quien propone no compara."""
    pool = [candidate(title="El que gustaba antes"), candidate(50, 80, "El bueno de verdad")]

    chosen = judge_candidates(
        pool,
        CONTEXT,
        limit=1,
        ask=lambda system, user: answer(verdict(hook=5), perfect()),
    )

    assert chosen[0].title == "El bueno de verdad"


def test_the_judge_replaces_the_score_and_keeps_the_breakdown() -> None:
    (chosen,) = judge_candidates(
        [candidate()], CONTEXT, limit=1, ask=lambda system, user: answer(perfect())
    )

    assert chosen.score == float(MAX_SCORE)
    assert chosen.judge_scores is not None
    assert chosen.judge_scores["hook"] == 18


def test_a_clip_below_the_bar_is_not_published() -> None:
    """Publicar cinco cosas mediocres hace más daño que publicar dos buenas."""
    pool = [candidate(title="Bueno"), candidate(50, 80, "Flojo")]

    chosen = judge_candidates(
        pool,
        CONTEXT,
        limit=5,
        ask=lambda system, user: answer(perfect(), verdict(hook=2)),
    )

    assert [clip.title for clip in chosen] == ["Bueno"]


def test_when_nothing_reaches_the_bar_se_publica_lo_mejor_que_haya() -> None:
    """Un clip mediocre es peor que uno bueno y mejor que ninguno."""
    chosen = judge_candidates(
        [candidate(title="Regular"), candidate(50, 80, "Peor")],
        CONTEXT,
        limit=1,
        ask=lambda system, user: answer(verdict(hook=10), verdict(hook=1)),
    )

    assert [clip.title for clip in chosen] == ["Regular"]
    assert chosen[0].score < MIN_PUBLISHABLE


def test_a_failed_judge_falls_back_to_what_the_detector_said() -> None:
    def broken(system: str, user: str) -> str:
        raise ExternalToolError("el juez no responde")

    pool = [candidate(title="Primero"), candidate(50, 80, "Segundo")]
    chosen = judge_candidates(pool, CONTEXT, limit=2, ask=broken)

    assert [clip.title for clip in chosen] == ["Primero", "Segundo"]


def test_an_empty_verdict_also_falls_back() -> None:
    chosen = judge_candidates(
        [candidate()], CONTEXT, limit=1, ask=lambda system, user: json.dumps({"clips": []})
    )

    assert len(chosen) == 1


def test_a_candidate_the_judge_skipped_keeps_the_detector_score() -> None:
    pool = [candidate(title="Juzgado"), candidate(50, 80, "Olvidado")]

    chosen = judge_candidates(pool, CONTEXT, limit=2, ask=lambda system, user: answer(perfect()))

    assert chosen[0].title == "Juzgado"
    assert chosen[1].judge_scores is None


def test_nothing_to_judge_is_not_a_call() -> None:
    def explode(system: str, user: str) -> str:  # pragma: no cover - no debe llamarse
        raise AssertionError("no hay nada que juzgar")

    assert judge_candidates([], CONTEXT, limit=5, ask=explode) == []


# ------------------------------------------------------------- los pesos
def test_controversy_still_counts_but_no_longer_rules() -> None:
    """Se queda porque de ahí salen los clips que la gente comenta.

    Con 7 puntos mandaba sobre el humor y el mejor clip de un vídeo de risas
    acabó siendo una acusación. Baja, no desaparece.
    """
    weights = {criterion.key: criterion.maximum for criterion in MERITS}

    assert weights["controversy"] > 0
    assert weights["controversy"] < weights["humor"]


def test_the_rubric_still_adds_up_to_a_hundred() -> None:
    """Tocar un peso sin tocar otro descuadraría la nota en silencio."""
    assert MAX_SCORE == 100
