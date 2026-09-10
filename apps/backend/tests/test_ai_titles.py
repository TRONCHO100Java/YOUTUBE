"""El titulado se cree lo justo de lo que devuelve el modelo.

La regla del proyecto —nada de lo que llega del LLM se da por bueno— aplica
aquí con más motivo que en el análisis: un título malo no se queda en un log,
se publica.
"""

from __future__ import annotations

import json

import pytest

from clipforge.core.errors import ExternalToolError
from clipforge.services.ai.base import AnalysisContext, ClipSuggestion
from clipforge.services.ai.titles import (
    MAX_DESCRIPTION_CHARS,
    MAX_HASHTAGS,
    SHORTS_TAG,
    choose_title,
    clean_description,
    clean_hashtags,
    clean_title,
    is_cliche,
    opening,
    parse_titles,
    publishable_variants,
    shouts,
    write_titles,
)

CONTEXT = AnalysisContext(title="Comedy compilation", author="Busy Fun Ltd")


def suggestion(
    title: str = "El salto del niño",
    *,
    hook: str | None = None,
    reason: str | None = "Un niño salta sobre un coche abandonado.",
) -> ClipSuggestion:
    return ClipSuggestion(
        start_segment=None,
        end_segment=None,
        start_time=10.0,
        end_time=35.0,
        title=title,
        hook=hook,
        reason=reason,
        scores=None,
        signal_score=50.0,
    )


def answer(*titles_per_clip: list[str]) -> str:
    """Respuesta del modelo con las variantes de cada clip, en orden.

    La descripción y las etiquetas van iguales para todos: los tests que
    miran los títulos no deben depender de ellas, y los que miran los
    metadatos las escriben aparte.
    """
    clips = [
        {
            "clip": number,
            "titles": titles,
            "description": "A farmer loses his footing and ends up in the water.",
            "hashtags": ["farmfails", "slapstick"],
        }
        for number, titles in enumerate(titles_per_clip, start=1)
    ]
    return json.dumps({"clips": clips})


# ------------------------------------------------------------------- limpieza
def test_the_quotes_a_model_wraps_the_title_in_are_not_part_of_the_title() -> None:
    assert clean_title('"He jumps on the car"') == "He jumps on the car"


def test_typographic_quotes_come_off_too() -> None:
    assert clean_title("“He jumps on the car”") == "He jumps on the car"


def test_a_leading_emoji_or_bullet_is_decoration_not_a_title() -> None:
    assert clean_title("\U0001f525 He jumps on the car") == "He jumps on the car"
    assert clean_title("1. He jumps on the car") == "He jumps on the car"


def test_the_full_stop_at_the_end_does_not_get_published() -> None:
    assert clean_title("He jumps on the car.") == "He jumps on the car"


def test_inner_whitespace_collapses() -> None:
    assert clean_title("He   jumps\non the car") == "He jumps on the car"


# --------------------------------------------------------------------- filtros
@pytest.mark.parametrize(
    "title",
    [
        "You won't believe what happens next",
        "This is what happened at the gym",
        "Must watch: the farmer slips",
        "Funny moment with the tractor",
    ],
)
def test_the_phrases_people_scroll_past_are_rejected(title: str) -> None:
    assert is_cliche(title) is True


def test_a_concrete_title_is_not_a_cliche() -> None:
    assert is_cliche("Kai Cenat meets the gym owner") is False


def test_shouting_is_not_a_title() -> None:
    assert shouts("THE FARMER SLIPS IN THE MUD") is True


def test_a_short_title_full_of_capitals_is_not_shouting() -> None:
    """Un título corto con siglas no puede confundirse con un grito."""
    assert shouts("NBA MVP") is False


def test_two_titles_share_an_opening_when_the_first_words_match() -> None:
    assert opening("The farmer slips in the mud") == opening("the farmer slips again")
    assert opening("The farmer slips") != opening("A farmer slips")


# ---------------------------------------------------------------- elección
def test_the_first_publishable_variant_wins() -> None:
    chosen = choose_title(
        ["Kai Cenat meets the gym owner", "Something else"],
        fallback="El salto",
        taken_openings=set(),
        max_chars=60,
    )
    assert chosen == "Kai Cenat meets the gym owner"


def test_a_variant_that_does_not_fit_gives_way_to_one_that_does() -> None:
    chosen = choose_title(
        ["x" * 80, "He lands on the roof"],
        fallback="El salto",
        taken_openings=set(),
        max_chars=60,
    )
    assert chosen == "He lands on the roof"


def test_a_cliche_gives_way_even_when_it_fits() -> None:
    chosen = choose_title(
        ["You won't believe this", "He lands on the roof"],
        fallback="El salto",
        taken_openings=set(),
        max_chars=60,
    )
    assert chosen == "He lands on the roof"


def test_the_title_never_repeats_the_text_already_burned_on_screen() -> None:
    chosen = choose_title(
        ["What a disaster", "The tractor takes him with it"],
        fallback="El salto",
        hook="What a disaster",
        taken_openings=set(),
        max_chars=60,
    )
    assert chosen == "The tractor takes him with it"


def test_a_repeated_opening_gives_way_to_a_different_one() -> None:
    chosen = choose_title(
        ["The farmer slips again", "He lands face first in the mud"],
        fallback="El salto",
        taken_openings={opening("The farmer slips in the mud")},
        max_chars=60,
    )
    assert chosen == "He lands face first in the mud"


def test_a_long_title_gets_cut_by_the_word_rather_than_thrown_away() -> None:
    """Un título correcto al que le sobra una subordinada se rescata."""
    long_title = "He lands on the roof of the car and the whole thing collapses"
    chosen = choose_title([long_title], fallback="El salto", taken_openings=set(), max_chars=30)

    assert chosen == "He lands on the roof of the"
    assert len(chosen) <= 30


def test_with_nothing_usable_the_analysis_title_stands() -> None:
    """Peor título, pero real: es la regla de no terminar con las manos vacías."""
    chosen = choose_title(
        ["", "   ", '""'],
        fallback="El salto del niño",
        taken_openings=set(),
        max_chars=60,
    )
    assert chosen == "El salto del niño"


# ------------------------------------------------------------------- respuesta
def test_a_response_wrapped_in_a_code_fence_still_parses() -> None:
    """Los modelos ponen el bloque de código pese al esquema."""
    fenced = f"```json{chr(10)}{answer(['He lands on the roof'])}{chr(10)}```"

    assert parse_titles(fenced)[1].titles == ["He lands on the roof"]


def test_a_response_that_is_not_the_agreed_shape_is_an_error() -> None:
    with pytest.raises(ExternalToolError):
        parse_titles('{"clips": [{"clip": 1}]}')


def test_a_response_that_is_not_even_json_is_an_error() -> None:
    with pytest.raises(ExternalToolError):
        parse_titles("Aquí tienes tus títulos:")


# -------------------------------------------------------------------- extremo
def test_the_clips_come_back_titled() -> None:
    clips = write_titles(
        [suggestion()],
        CONTEXT,
        ask=lambda system, user: answer(["He lands on the roof"]),
    )
    assert [clip.title for clip in clips] == ["He lands on the roof"]


def test_nothing_else_about_the_clip_changes() -> None:
    """Solo el título: los tiempos y el gancho incrustado se quedan como están."""
    original = suggestion(hook="What a disaster")
    (titled,) = write_titles(
        [original], CONTEXT, ask=lambda system, user: answer(["He lands on the roof"])
    )

    assert titled.start_time == original.start_time
    assert titled.end_time == original.end_time
    assert titled.hook == original.hook
    assert titled.score == original.score


def test_five_clips_do_not_end_up_with_five_versions_of_the_same_title() -> None:
    """El problema real: los cinco clips de un vídeo llamándose casi igual."""
    clips = write_titles(
        [suggestion("Uno"), suggestion("Dos"), suggestion("Tres")],
        CONTEXT,
        ask=lambda system, user: answer(
            ["The farmer slips in the mud"],
            ["The farmer slips again", "He drops the whole crate"],
            ["The farmer slips one more time", "The tractor rolls away"],
        ),
    )

    titles = [clip.title for clip in clips]
    assert titles == [
        "The farmer slips in the mud",
        "He drops the whole crate",
        "The tractor rolls away",
    ]


def test_a_clip_the_model_forgot_keeps_the_title_it_had() -> None:
    clips = write_titles(
        [suggestion("Uno"), suggestion("Dos")],
        CONTEXT,
        ask=lambda system, user: answer(["He lands on the roof"]),
    )
    assert [clip.title for clip in clips] == ["He lands on the roof", "Dos"]


def test_a_failure_writing_titles_never_costs_the_clips() -> None:
    """Los clips ya están: un fallo aquí se registra y se sigue."""

    def broken(system: str, user: str) -> str:
        raise ExternalToolError("Ollama no responde")

    clips = write_titles([suggestion()], CONTEXT, ask=broken)
    assert [clip.title for clip in clips] == ["El salto del niño"]


def test_no_clips_means_no_call_at_all() -> None:
    def explode(system: str, user: str) -> str:  # pragma: no cover - no debe llamarse
        raise AssertionError("no hay nada que titular")

    assert write_titles([], CONTEXT, ask=explode) == []


# ------------------------------------------------------------------ metadatos
def test_the_description_comes_back_in_one_clean_line() -> None:
    assert clean_description("  Two   lines\nof description  ") == "Two lines of description"


def test_an_empty_description_is_no_description() -> None:
    assert clean_description("   ") is None


def test_a_description_longer_than_the_box_shows_gets_cut_by_the_word() -> None:
    text = "palabra " * 200
    cleaned = clean_description(text)

    assert cleaned is not None
    assert len(cleaned) <= MAX_DESCRIPTION_CHARS
    assert not cleaned.endswith("pala")


def test_shorts_is_always_the_first_hashtag() -> None:
    """Es la etiqueta que decide que el vídeo entre en el carrusel."""
    assert clean_hashtags(["farmfails"])[0] == SHORTS_TAG


def test_a_hashtag_is_one_word_without_the_hash() -> None:
    assert clean_hashtags(["#Kai Cenat!"]) == (SHORTS_TAG, "KaiCenat")


def test_accents_survive_a_hashtag() -> None:
    assert clean_hashtags(["Peñíscola"]) == (SHORTS_TAG, "Peñíscola")


def test_the_model_repeating_shorts_does_not_duplicate_it() -> None:
    assert clean_hashtags(["shorts", "Shorts", "#SHORTS"]) == (SHORTS_TAG,)


def test_the_hashtag_list_stops_before_it_looks_like_spam() -> None:
    many = [f"tag{index}" for index in range(20)]
    assert len(clean_hashtags(many)) == MAX_HASHTAGS


def test_the_clip_carries_its_description_and_hashtags() -> None:
    (clip,) = write_titles(
        [suggestion()], CONTEXT, ask=lambda system, user: answer(["He lands on the roof"])
    )

    assert clip.description == "A farmer loses his footing and ends up in the water."
    assert clip.hashtags == (SHORTS_TAG, "farmfails", "slapstick")


def test_the_titles_not_chosen_are_kept_to_swap_later() -> None:
    """La llamada ya está pagada: cambiar de título debe ser un clic, no otra."""
    (clip,) = write_titles(
        [suggestion()],
        CONTEXT,
        ask=lambda system, user: answer(
            ["He lands on the roof", "The car gives way under him", "Why did he jump"]
        ),
    )

    assert clip.title == "He lands on the roof"
    assert clip.title_variants == ("The car gives way under him", "Why did he jump")


def test_a_variant_that_would_be_rejected_is_not_offered_either() -> None:
    """Las alternativas del editor pasan el mismo filtro que el título elegido."""
    (clip,) = write_titles(
        [suggestion()],
        CONTEXT,
        ask=lambda system, user: answer(
            ["He lands on the roof", "You won't believe this", "THE CAR GIVES WAY"]
        ),
    )

    assert clip.title == "He lands on the roof"
    assert clip.title_variants == ()


def test_a_variant_that_only_needed_trimming_is_still_offered() -> None:
    """Un título correcto al que le sobra una subordinada no se tira."""
    long_variant = "The car gives way under him and the whole roof folds in on itself right away"
    (clip,) = write_titles(
        [suggestion()],
        CONTEXT,
        ask=lambda system, user: answer(["He lands on the roof", long_variant]),
    )

    (offered,) = clip.title_variants
    assert len(offered) <= 60
    assert long_variant.startswith(offered)


def test_the_variants_that_come_back_fit_and_are_ordered_by_preference() -> None:
    variants = publishable_variants(
        ["A title that is far too long to publish anywhere at all, really", "Short one"],
        max_chars=30,
    )

    assert variants[0] == "Short one"
    assert all(len(variant) <= 30 for variant in variants)
