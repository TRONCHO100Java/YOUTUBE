"""Reintentos del analizador de Ollama.

Un modelo local devuelve de vez en cuando una respuesta inservible. Sin
reintento se pierde la ventana entera —y con ella varios minutos de vídeo—,
que es exactamente lo que se observó en la primera prueba real.
"""

from __future__ import annotations

import pytest

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.db.models.enums import ContentProfile
from clipforge.services.ai.base import AnalysisContext, AnalysisSegment, AnalysisWindow
from clipforge.services.ai.ollama_analyzer import OllamaClipAnalyzer
from clipforge.services.ai.profiles import rules_for
from clipforge.services.ai.schema import candidate_model

CONTEXT = AnalysisContext(language="es")

WINDOW = AnalysisWindow(
    number=1,
    segments=[
        AnalysisSegment(index=i, start=i * 10.0, end=(i + 1) * 10.0, text=f"texto {i}")
        for i in range(10)
    ],
)


@pytest.fixture(autouse=True)
def fast_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin esperas reales y con límites de clip fijos."""
    monkeypatch.setattr("clipforge.services.ai.ollama_analyzer.RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(settings, "ai_max_retries", 3)
    monkeypatch.setattr(settings, "min_clip_duration", 20)
    monkeypatch.setattr(settings, "max_clip_duration", 90)


def _candidate():  # type: ignore[no-untyped-def]
    return candidate_model(rules_for(ContentProfile.TALKING)).model_validate(
        {
            "start_segment": 0,
            "end_segment": 4,
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
    )


class _Attempts:
    """Falla las primeras `failures` llamadas y luego responde bien."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def __call__(self, window: AnalysisWindow, context: AnalysisContext, rules: object):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls <= self.failures:
            raise ExternalToolError("La IA no ha devuelto JSON válido")
        return [_candidate()]


def test_succeeds_without_retrying_when_the_model_responds_well(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = _Attempts(failures=0)
    analyzer = OllamaClipAnalyzer()
    monkeypatch.setattr(analyzer, "_request_candidates", attempts)

    assert len(analyzer.analyze_window(WINDOW, CONTEXT)) == 1
    assert attempts.calls == 1


def test_recovers_from_an_intermittent_bad_response(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = _Attempts(failures=2)
    analyzer = OllamaClipAnalyzer()
    monkeypatch.setattr(analyzer, "_request_candidates", attempts)

    assert len(analyzer.analyze_window(WINDOW, CONTEXT)) == 1
    assert attempts.calls == 3


def test_gives_up_after_the_configured_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = _Attempts(failures=99)
    analyzer = OllamaClipAnalyzer()
    monkeypatch.setattr(analyzer, "_request_candidates", attempts)

    with pytest.raises(ExternalToolError, match="JSON válido"):
        analyzer.analyze_window(WINDOW, CONTEXT)

    assert attempts.calls == settings.ai_max_retries


def test_a_single_attempt_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_max_retries", 1)
    attempts = _Attempts(failures=99)
    analyzer = OllamaClipAnalyzer()
    monkeypatch.setattr(analyzer, "_request_candidates", attempts)

    with pytest.raises(ExternalToolError):
        analyzer.analyze_window(WINDOW, CONTEXT)

    assert attempts.calls == 1
