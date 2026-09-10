"""Las etiquetas existen para agrupar, así que se normalizan al guardarlas."""

from __future__ import annotations

import json

from clipforge.core.errors import ExternalToolError
from clipforge.services.ai.base import AnalysisContext, ClipSuggestion
from clipforge.services.ai.prompts_tagging import MOMENT_KINDS
from clipforge.services.ai.tagging import MAX_PEOPLE, normalize, tag_clips

CONTEXT = AnalysisContext(title="Among Us lobby", author="Kai Cenat")


def clip(title: str = "Un momento") -> ClipSuggestion:
    return ClipSuggestion(
        start_segment=None,
        end_segment=None,
        start_time=10.0,
        end_time=40.0,
        title=title,
        hook=None,
        reason="Lo eligió el detector.",
        scores=None,
        transcript_excerpt="lo que se dice",
        signal_score=60.0,
    )


def answer(*per_clip: dict[str, object]) -> str:
    clips = [
        {
            "clip": number,
            "niche": "streamers",
            "people": ["Kai Cenat"],
            "topics": ["among us"],
            "kind": "reaccion",
            **overrides,
        }
        for number, overrides in enumerate(per_clip, start=1)
    ]
    return json.dumps({"clips": clips})


# ---------------------------------------------------------------- normalizar
def test_the_same_name_written_three_ways_is_one_tag() -> None:
    """Su único uso es agrupar: tienen que caer en el mismo montón."""
    assert normalize("Kai Cenat") == normalize("kai cenat") == normalize("Kai-Cenat")


def test_accents_do_not_split_a_group() -> None:
    assert normalize("Motivación") == "motivacion"


def test_an_empty_tag_stays_empty() -> None:
    assert normalize("   ") == ""


def test_a_tag_keeps_its_inner_space() -> None:
    """Un nombre de dos palabras se lee mejor así que pegado."""
    assert normalize("Among Us") == "among us"


# ---------------------------------------------------------------- etiquetar
def test_a_clip_comes_back_tagged() -> None:
    (tag,) = tag_clips([clip()], CONTEXT, ask=lambda s, u: answer({}))

    assert tag.niche == "streamers"
    assert tag.people == ("kai cenat",)
    assert tag.kind == "reaccion"


def test_a_made_up_kind_of_moment_is_dropped() -> None:
    """El vocabulario es cerrado: si cada clip inventa el suyo, no agrupan."""
    (tag,) = tag_clips([clip()], CONTEXT, ask=lambda s, u: answer({"kind": "comedy gold"}))

    assert tag.kind is None


def test_every_allowed_kind_survives() -> None:
    for kind in MOMENT_KINDS:
        (tag,) = tag_clips([clip()], CONTEXT, ask=lambda s, u, k=kind: answer({"kind": k}))
        assert tag.kind == kind


def test_a_crowd_of_names_gets_cut() -> None:
    """Más de tres nombres no identifica: diluye."""
    many = [f"persona {index}" for index in range(10)]
    (tag,) = tag_clips([clip()], CONTEXT, ask=lambda s, u: answer({"people": many}))

    assert len(tag.people) <= MAX_PEOPLE


def test_the_same_name_twice_counts_once() -> None:
    (tag,) = tag_clips(
        [clip()], CONTEXT, ask=lambda s, u: answer({"people": ["Kai Cenat", "kai cenat"]})
    )

    assert tag.people == ("kai cenat",)


def test_each_clip_gets_its_own_topics() -> None:
    tags = tag_clips(
        [clip("Uno"), clip("Dos")],
        CONTEXT,
        ask=lambda s, u: answer({"topics": ["among us"]}, {"topics": ["gimnasio"]}),
    )

    assert [tag.topics for tag in tags] == [("among us",), ("gimnasio",)]


def test_a_clip_the_model_forgot_comes_back_empty() -> None:
    tags = tag_clips([clip("Uno"), clip("Dos")], CONTEXT, ask=lambda s, u: answer({}))

    assert tags[1].is_empty is True


# ------------------------------------------------------------------ fallos
def test_a_failure_is_not_fatal() -> None:
    """Sin etiquetas el clip se publica igual; solo no se reparte solo."""

    def broken(system: str, user: str) -> str:
        raise ExternalToolError("el etiquetador no responde")

    tags = tag_clips([clip()], CONTEXT, ask=broken)

    assert len(tags) == 1
    assert tags[0].is_empty is True


def test_an_answer_of_another_shape_is_not_fatal_either() -> None:
    tags = tag_clips([clip()], CONTEXT, ask=lambda s, u: '{"etiquetas": []}')

    assert tags[0].is_empty is True


def test_nothing_to_tag_is_not_a_call() -> None:
    def explode(system: str, user: str) -> str:  # pragma: no cover - no debe llamarse
        raise AssertionError("no hay nada que etiquetar")

    assert tag_clips([], CONTEXT, ask=explode) == []


# ------------------------------------------------------- un canal, un nicho
def test_the_whole_project_shares_one_niche() -> None:
    """Un nicho por clip no sirve para repartir: los cinco van al mismo canal."""
    tags = tag_clips(
        [clip("Uno"), clip("Dos"), clip("Tres")],
        CONTEXT,
        ask=lambda s, u: answer({"niche": "fail"}, {"niche": "gag"}, {"niche": "gag"}),
    )

    assert {tag.niche for tag in tags} == {"gag"}


def test_the_kind_of_moment_does_keep_varying() -> None:
    """Ahí sí está la diferencia que el modelo veía, y se respeta."""
    tags = tag_clips(
        [clip("Uno"), clip("Dos")],
        CONTEXT,
        ask=lambda s, u: answer({"kind": "fail"}, {"kind": "gag"}),
    )

    assert [tag.kind for tag in tags] == ["fail", "gag"]
