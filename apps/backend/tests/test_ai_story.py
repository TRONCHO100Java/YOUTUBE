"""El montador decide cómo se cuenta el clip.

Todo lo que devuelve se acota antes de llegar al render: aquí se deciden
segundos y textos que acaban quemados en el vídeo, y una cifra mal interpretada
no se ve hasta que el MP4 ya existe.
"""

from __future__ import annotations

import json

from clipforge.core.errors import ExternalToolError
from clipforge.services.ai.base import AnalysisContext, ClipSuggestion
from clipforge.services.ai.story import (
    MAX_NOTE_CHARS,
    MAX_TIGHTEN_RATIO,
    NOTE_SECONDS,
    write_story,
)

CONTEXT = AnalysisContext(title="Among Us lobby", author="Kai Cenat")


def clip(duration: float = 40.0, excerpt: str = "lo que se dice") -> ClipSuggestion:
    return ClipSuggestion(
        start_segment=None,
        end_segment=None,
        start_time=100.0,
        end_time=100.0 + duration,
        title="Un momento",
        hook="Gancho del análisis",
        reason="Lo eligió el detector.",
        scores=None,
        transcript_excerpt=excerpt,
        signal_score=60.0,
    )


def answer(
    *,
    hook: str = "Kai realises what happened",
    start_at: float = 0.0,
    end_at: float = 40.0,
    payoff_at: float = 30.0,
    notes: list[dict[str, object]] | None = None,
) -> str:
    return json.dumps(
        {
            "hook": hook,
            "start_at": start_at,
            "end_at": end_at,
            "payoff_at": payoff_at,
            "notes": notes if notes is not None else [],
        }
    )


def told(**kwargs: object) -> object:
    story = write_story(clip(), CONTEXT, ask=lambda system, user: answer(**kwargs))  # type: ignore[arg-type]
    assert story is not None
    return story


# ------------------------------------------------------------------ entrada
def test_the_clip_can_start_later_than_the_detector_said() -> None:
    """Arrancar dos segundos antes de la frase buena regala los que deciden."""
    story = told(start_at=3.5)

    assert story.start_at == 3.5  # type: ignore[attr-defined]


def test_it_cannot_eat_half_the_clip() -> None:
    """Si quiere quitar la mitad, el que se equivocó fue quien eligió el momento."""
    story = told(start_at=30.0)

    assert story.start_at <= 40.0 * MAX_TIGHTEN_RATIO  # type: ignore[attr-defined]


def test_a_negative_start_is_not_a_start() -> None:
    story = told(start_at=-10.0)

    assert story.start_at == 0.0  # type: ignore[attr-defined]


def test_an_end_that_would_leave_nothing_is_ignored() -> None:
    """Un final de 4 s es el modelo confundiendo unidades, no una decisión."""
    story = told(end_at=4.0)

    assert story.end_at is None  # type: ignore[attr-defined]


def test_an_end_before_the_clip_ends_is_respected() -> None:
    story = told(end_at=32.0)

    assert story.end_at == 32.0  # type: ignore[attr-defined]


# -------------------------------------------------------------------- notas
def test_a_note_travels_with_its_second() -> None:
    story = told(notes=[{"text": "Silky knew he was cooked", "at": 12.0}])

    assert len(story.notes) == 1  # type: ignore[attr-defined]
    assert story.notes[0].at == 12.0  # type: ignore[attr-defined]


def test_a_note_never_covers_the_hook() -> None:
    """Pegadas, el ojo salta de una a otra y no se mira el vídeo."""
    story = told(notes=[{"text": "Contexto", "at": 0.5}])

    assert story.notes[0].at >= 3.0  # type: ignore[attr-defined]


def test_two_notes_on_top_of_each_other_become_one() -> None:
    story = told(notes=[{"text": "Primera", "at": 12.0}, {"text": "Segunda", "at": 12.5}])

    assert len(story.notes) == 1  # type: ignore[attr-defined]


def test_a_note_too_long_to_read_at_a_glance_gets_cut() -> None:
    story = told(notes=[{"text": "palabra " * 30, "at": 12.0}])

    assert len(story.notes[0].text) <= MAX_NOTE_CHARS  # type: ignore[attr-defined]


def test_an_empty_note_is_not_a_note() -> None:
    story = told(notes=[{"text": "   ", "at": 12.0}])

    assert story.notes == ()  # type: ignore[attr-defined]


def test_a_note_that_would_fall_off_the_end_is_dropped() -> None:
    story = told(notes=[{"text": "Tarde", "at": 39.9}])

    assert all(note.at + NOTE_SECONDS <= 40.0 for note in story.notes)  # type: ignore[attr-defined]


def test_no_notes_is_a_valid_answer() -> None:
    """Si el clip se entiende solo, poner una por rellenar es ruido."""
    story = told(notes=[])

    assert story.notes == ()  # type: ignore[attr-defined]


# ------------------------------------------------------------------- gancho
def test_the_hook_comes_back_clean() -> None:
    story = told(hook='  "Kai realises what happened"  ')

    assert story.hook == "Kai realises what happened"  # type: ignore[attr-defined]


# ------------------------------------------------------------------ fallos
def test_a_clip_without_transcript_is_left_alone() -> None:
    """El montador no ve el vídeo: sin texto no tiene nada que estructurar."""

    def explode(system: str, user: str) -> str:  # pragma: no cover - no debe llamarse
        raise AssertionError("no hay nada que montar")

    assert write_story(clip(excerpt=""), CONTEXT, ask=explode) is None


def test_a_failed_call_leaves_the_clip_as_it_was() -> None:
    def broken(system: str, user: str) -> str:
        raise ExternalToolError("el montador no responde")

    assert write_story(clip(), CONTEXT, ask=broken) is None


def test_an_answer_that_is_not_the_agreed_shape_is_not_fatal() -> None:
    assert write_story(clip(), CONTEXT, ask=lambda s, u: '{"otra": "cosa"}') is None


def test_the_story_serialises_for_storage() -> None:
    story = told(notes=[{"text": "Contexto", "at": 12.0}])
    stored = story.as_dict()  # type: ignore[attr-defined]

    assert stored["hook"] == "Kai realises what happened"
    assert stored["notes"] == [{"text": "Contexto", "at": 12.0}]


# ------------------------------------------------ no empeorar lo que ya había
def test_a_description_instead_of_a_hook_is_rejected() -> None:
    """Medido sobre clips reales: un modelo pequeño devuelve descripciones.

    Descartarla deja el gancho del análisis, que en un clip hablado es una cita
    textual de lo que se dice, y casi siempre es mejor.
    """
    story = told(hook="Kai Cenat's intense training montage reveals a powerful message")

    assert story.hook is None  # type: ignore[attr-defined]


def test_a_real_hook_survives() -> None:
    story = told(hook="Silky knew he was cooked")

    assert story.hook == "Silky knew he was cooked"  # type: ignore[attr-defined]


def test_a_note_that_only_names_the_obvious_is_noise() -> None:
    """Poner "Kai Cenat" encima de un vídeo de Kai Cenat no explica nada."""
    story = write_story(
        clip(),
        AnalysisContext(title="Kai Cenat trains hard", author="Kai Cenat"),
        ask=lambda system, user: answer(notes=[{"text": "Kai Cenat", "at": 12.0}]),
    )

    assert story is not None
    assert story.notes == ()


def test_a_note_that_explains_something_survives() -> None:
    story = write_story(
        clip(),
        AnalysisContext(title="Kai Cenat trains hard", author="Kai Cenat"),
        ask=lambda system, user: answer(
            notes=[{"text": "His mentor pushes him harder", "at": 12.0}]
        ),
    )

    assert story is not None
    assert story.notes[0].text == "His mentor pushes him harder"
