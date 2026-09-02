"""Modelo de datos de la transcripción."""

from __future__ import annotations

from clipforge.services.transcribe.base import Segment, TranscriptionResult, Word


def _segment(index: int, start: float, end: float, text: str) -> Segment:
    return Segment(index=index, start=start, end=end, text=text)


def test_full_text_joins_segments_and_trims() -> None:
    result = TranscriptionResult(
        language="es",
        language_probability=0.99,
        duration=10.0,
        model_name="large-v3",
        segments=[
            _segment(0, 0.0, 2.0, "  Hola, "),
            _segment(1, 2.0, 4.0, "esto es una prueba.  "),
        ],
    )
    assert result.full_text == "Hola, esto es una prueba."


def test_full_text_ignores_empty_segments() -> None:
    result = TranscriptionResult(
        language="es",
        language_probability=None,
        duration=None,
        model_name="tiny",
        segments=[
            _segment(0, 0.0, 1.0, "Uno"),
            _segment(1, 1.0, 2.0, "   "),
            _segment(2, 2.0, 3.0, "Dos"),
        ],
    )
    assert result.full_text == "Uno Dos"


def test_full_text_of_empty_transcription_is_empty() -> None:
    result = TranscriptionResult(
        language=None, language_probability=None, duration=None, model_name="tiny", segments=[]
    )
    assert result.full_text == ""


def test_segment_duration() -> None:
    assert _segment(0, 12.5, 18.25, "x").duration == 5.75


def test_word_serialization_rounds_and_keeps_nulls() -> None:
    assert Word(word="hola", start=1.23456, end=1.98765, probability=0.987654).to_dict() == {
        "word": "hola",
        "start": 1.235,
        "end": 1.988,
        "probability": 0.988,
    }
    assert Word(word="x", start=0.0, end=0.1).to_dict()["probability"] is None
