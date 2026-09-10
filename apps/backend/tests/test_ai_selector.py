"""Orquestación completa del análisis, con un analizador de prueba.

El doble vive aquí y no en `services/`: la aplicación no lleva simulaciones,
pero probar la estrategia entera sin gastar tokens sí tiene sentido.
"""

from __future__ import annotations

import pytest

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.services.ai.base import (
    AnalysisContext,
    AnalysisSegment,
    AnalysisWindow,
    ClipAnalyzer,
    ClipScores,
    ClipSuggestion,
)
from clipforge.services.ai.selector import select_clips

CONTEXT = AnalysisContext(title="Un vídeo", author="Alguien", language="es")


class RecordingAnalyzer(ClipAnalyzer):
    """Propone un clip por ventana y registra las ventanas que ha visto."""

    provider = "test"

    def __init__(self, *, fail_on: set[int] | None = None) -> None:
        self.seen: list[AnalysisWindow] = []
        self.fail_on = fail_on or set()

    def analyze_window(
        self, window: AnalysisWindow, context: AnalysisContext
    ) -> list[ClipSuggestion]:
        self.seen.append(window)
        if window.number in self.fail_on:
            raise ExternalToolError(f"fallo simulado en la ventana {window.number}")

        first, last = window.segments[0], window.segments[-1]
        return [
            ClipSuggestion(
                start_segment=first.index,
                end_segment=last.index,
                start_time=first.start,
                end_time=last.end,
                title=f"Ventana {window.number}",
                hook=None,
                reason=None,
                scores=ClipScores(
                    hook=window.number,
                    curiosity=0,
                    emotion=0,
                    clarity=0,
                    value=0,
                    shareability=0,
                    duration=0,
                ),
            )
        ]


@pytest.fixture(autouse=True)
def analysis_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "analysis_chunk_seconds", 100)
    monkeypatch.setattr(settings, "analysis_chunk_overlap_seconds", 20)
    monkeypatch.setattr(settings, "max_clips_per_project", 3)


def _segments(count: int) -> list[AnalysisSegment]:
    return [
        AnalysisSegment(index=i, start=i * 10.0, end=(i + 1) * 10.0, text=f"s{i}")
        for i in range(count)
    ]


def test_every_window_is_analyzed() -> None:
    analyzer = RecordingAnalyzer()
    select_clips(_segments(60), CONTEXT, analyzer)

    assert len(analyzer.seen) > 1
    assert [w.number for w in analyzer.seen] == list(range(1, len(analyzer.seen) + 1))


def test_the_detector_fills_the_pool_not_the_project() -> None:
    """Detectar es proponer en bruto: quien recorta a cinco es el juez."""
    selected = select_clips(_segments(120), CONTEXT, RecordingAnalyzer())

    assert len(selected) <= settings.max_candidates_per_project
    assert len(selected) > settings.max_clips_per_project


def test_explicit_limit_overrides_the_setting() -> None:
    selected = select_clips(_segments(120), CONTEXT, RecordingAnalyzer(), limit=1)
    assert len(selected) == 1


def test_results_are_ordered_by_score() -> None:
    selected = select_clips(_segments(120), CONTEXT, RecordingAnalyzer())
    scores = [c.score for c in selected]
    assert scores == sorted(scores, reverse=True)


def test_empty_transcript_returns_nothing_without_calling_the_model() -> None:
    analyzer = RecordingAnalyzer()
    assert select_clips([], CONTEXT, analyzer) == []
    assert analyzer.seen == []


def test_one_failing_window_does_not_abort_the_analysis() -> None:
    """Un timeout suelto no debe tirar 40 minutos de trabajo."""
    analyzer = RecordingAnalyzer(fail_on={2})
    selected = select_clips(_segments(120), CONTEXT, analyzer)

    assert selected, "las demás ventanas deben seguir aportando candidatos"
    assert all(c.title != "Ventana 2" for c in selected)


def test_failure_in_every_window_is_propagated() -> None:
    total_windows = len(RecordingAnalyzer().seen) or 99
    analyzer = RecordingAnalyzer(fail_on=set(range(1, total_windows + 1)))

    with pytest.raises(ExternalToolError, match="todas las ventanas"):
        select_clips(_segments(120), CONTEXT, analyzer)


def test_analysis_is_deterministic() -> None:
    first = select_clips(_segments(120), CONTEXT, RecordingAnalyzer())
    second = select_clips(_segments(120), CONTEXT, RecordingAnalyzer())
    assert [c.title for c in first] == [c.title for c in second]
