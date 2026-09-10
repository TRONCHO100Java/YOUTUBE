"""Las palabras clave las escribe una persona con prisa: hay que limpiarlas."""

from __future__ import annotations

from clipforge.services.ai.keywords import MAX_TERM_LENGTH, MAX_TERMS, parse_keywords


def test_nothing_written_is_no_keywords() -> None:
    assert parse_keywords(None) == ()
    assert parse_keywords("") == ()
    assert parse_keywords("   ,  ,\n") == ()


def test_commas_line_breaks_and_semicolons_all_separate() -> None:
    assert parse_keywords("kai cenat, speed;\namong us") == ("kai cenat", "speed", "among us")


def test_proper_nouns_keep_the_capitals_they_were_written_with() -> None:
    """Un nombre propio va al título tal cual: así es como se busca."""
    assert parse_keywords("Kai Cenat") == ("Kai Cenat",)


def test_the_same_term_twice_only_counts_once() -> None:
    assert parse_keywords("Speed, speed, SPEED") == ("Speed",)


def test_inner_whitespace_collapses() -> None:
    assert parse_keywords("  kai    cenat  ") == ("kai cenat",)


def test_a_phrase_gets_cut_to_a_keyword() -> None:
    long_term = "a" * (MAX_TERM_LENGTH + 20)
    assert parse_keywords(long_term) == ("a" * MAX_TERM_LENGTH,)


def test_the_list_stops_where_the_model_would_stop_prioritising() -> None:
    raw = ", ".join(f"term{index}" for index in range(MAX_TERMS + 5))
    assert len(parse_keywords(raw)) == MAX_TERMS
