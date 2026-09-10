"""El montaje del clip y la traducción de tiempos.

Aquí se decide dónde cae cada cosa cuando el clip deja de ser el original
recortado. Si esto se equivoca, los subtítulos y los rótulos aparecen donde no
toca y el clip se ve peor que sin editar.
"""

from __future__ import annotations

from clipforge.services.edit import Beat, EditPlan, TrimRules, Word, plan_trim
from clipforge.services.edit.trim import words_from_segments


def speech(*spans: tuple[float, float]) -> list[Word]:
    """Palabras que ocupan cada tramo indicado."""
    return [Word(start=start, end=end, text="x") for start, end in spans]


# ------------------------------------------------------------------- el plan
def test_a_clip_with_nothing_removed_is_the_clip_of_always() -> None:
    plan = EditPlan.single(10.0, 40.0)

    assert plan.is_continuous is True
    assert plan.duration == 30.0
    assert plan.removed == 0.0


def test_the_output_lasts_what_the_beats_last() -> None:
    plan = EditPlan.of([Beat(10.0, 20.0), Beat(25.0, 30.0)])

    assert plan.duration == 15.0
    assert plan.source_duration == 20.0
    assert plan.removed == 5.0


def test_two_beats_a_hair_apart_are_really_one() -> None:
    """Un corte de dos centésimas no es montaje: es un parpadeo."""
    plan = EditPlan.of([Beat(10.0, 20.0), Beat(20.02, 30.0)])

    assert len(plan.beats) == 1
    assert plan.is_continuous is True


def test_the_beats_come_out_in_order_however_they_went_in() -> None:
    plan = EditPlan.of([Beat(25.0, 30.0), Beat(10.0, 20.0)])

    assert [beat.start for beat in plan.beats] == [10.0, 25.0]


def test_an_empty_beat_does_not_survive() -> None:
    plan = EditPlan.of([Beat(10.0, 10.0), Beat(12.0, 15.0)])

    assert len(plan.beats) == 1


# ---------------------------------------------------------------- los tiempos
def test_an_instant_before_any_cut_keeps_its_place() -> None:
    plan = EditPlan.of([Beat(10.0, 20.0), Beat(25.0, 30.0)])

    assert plan.map_time(15.0) == 5.0


def test_an_instant_after_a_cut_se_adelanta_lo_que_se_quito() -> None:
    """Es la razón de existir de todo esto: cinco segundos menos por delante."""
    plan = EditPlan.of([Beat(10.0, 20.0), Beat(25.0, 30.0)])

    assert plan.map_time(27.0) == 12.0


def test_an_instant_inside_a_cut_no_existe_en_el_clip() -> None:
    """Devolver el más cercano fingiría una precisión que no se tiene."""
    plan = EditPlan.of([Beat(10.0, 20.0), Beat(25.0, 30.0)])

    assert plan.map_time(22.0) is None


def test_a_span_crossing_a_cut_comes_back_in_pieces() -> None:
    """Un subtítulo de cuatro segundos puede salir partido en dos."""
    plan = EditPlan.of([Beat(10.0, 20.0), Beat(25.0, 30.0)])

    pieces = plan.spans_for(18.0, 27.0)

    assert len(pieces) == 2
    assert pieces[0][:2] == (18.0, 20.0)
    assert pieces[1][:2] == (25.0, 27.0)


# ------------------------------------------------------------------ el corte
def test_a_long_pause_between_words_gets_cut() -> None:
    plan = plan_trim(speech((10.0, 20.0), (24.0, 30.0)), start=10.0, end=30.0)

    assert plan.is_continuous is False
    assert plan.duration < 20.0


def test_the_pauses_of_normal_speech_no_se_tocan() -> None:
    """Quitar cada respiración hace que el montaje suene a robot."""
    plan = plan_trim(speech((10.0, 12.0), (12.2, 14.0), (14.25, 16.0)), start=10.0, end=16.0)

    assert plan.is_continuous is True


def test_the_cut_leaves_room_around_the_words() -> None:
    """Sin margen se come la consonante inicial y suena atropellado."""
    # Sin tope: lo que se mide aquí es dónde cae el corte, no cuánto quita.
    rules = TrimRules(min_gap=0.5, padding=0.2, min_beat=0.1, max_removed_ratio=0.9)
    plan = plan_trim(speech((10.0, 11.0), (14.0, 15.0)), start=10.0, end=15.0, rules=rules)

    assert plan.beats[0].end == 11.2
    assert plan.beats[1].start == 13.8


def test_dead_air_at_the_start_is_the_worst_kind() -> None:
    """Son los segundos en los que se decide si alguien se queda."""
    plan = plan_trim(speech((13.0, 18.0)), start=10.0, end=18.0)

    assert plan.source_start > 10.0


def test_dead_air_at_the_end_also_goes() -> None:
    plan = plan_trim(speech((10.0, 14.0)), start=10.0, end=20.0)

    assert plan.source_end < 20.0


def test_a_clip_that_is_half_silence_is_left_alone() -> None:
    """El problema entonces es la selección del momento, no el montaje."""
    plan = plan_trim(speech((10.0, 11.0), (25.0, 26.0)), start=10.0, end=26.0)

    assert plan.is_continuous is True


def test_a_sliver_between_two_cuts_is_dropped_whole() -> None:
    """Mejor perder tres décimas que dejar un pestañeo entre dos cortes."""
    rules = TrimRules(min_gap=0.5, padding=0.05, min_beat=0.5, max_removed_ratio=0.9)
    plan = plan_trim(
        speech((10.0, 11.0), (12.0, 12.2), (13.0, 15.0)), start=10.0, end=15.0, rules=rules
    )

    assert all(beat.duration >= 0.5 for beat in plan.beats)


def test_a_clip_without_words_is_not_touched() -> None:
    """Sin saber dónde está el silencio, adivinarlo es peor que no cortar."""
    plan = plan_trim([], start=10.0, end=40.0)

    assert plan.is_continuous is True
    assert plan.duration == 30.0


def test_words_from_another_part_of_the_video_do_not_count() -> None:
    plan = plan_trim(speech((100.0, 105.0)), start=10.0, end=20.0)

    assert plan.is_continuous is True


# --------------------------------------------------- lo que devuelve Whisper
def test_the_words_whisper_gives_are_read() -> None:
    words = words_from_segments(
        [{"start": 1.0, "end": 1.4, "word": " Kai"}, {"start": 1.4, "end": 1.9, "word": " Cenat"}]
    )

    assert [word.text for word in words] == ["Kai", "Cenat"]


def test_a_word_without_times_is_skipped() -> None:
    """Una sola bastaría para colocar un corte donde no toca."""
    words = words_from_segments(
        [{"word": "sin tiempos"}, {"start": 1.0, "end": 1.4, "word": "buena"}]
    )

    assert len(words) == 1


def test_a_word_that_ends_before_it_starts_is_skipped() -> None:
    assert words_from_segments([{"start": 5.0, "end": 4.0, "word": "rota"}]) == []
