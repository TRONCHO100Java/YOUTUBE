"""Orquestación del análisis: transcripción completa → mejores clips.

Encadena troceado → análisis por ventana → deduplicación → ranking global. Se
mantiene separado de los clientes de cada proveedor para poder probar la
estrategia entera con un analizador de prueba, sin gastar tokens.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.ai.base import (
    AnalysisContext,
    AnalysisSegment,
    ClipAnalyzer,
    ClipSuggestion,
)
from clipforge.services.ai.chunking import build_windows
from clipforge.services.ai.ranking import select_top

logger = get_logger(__name__)


def select_clips(
    segments: Sequence[AnalysisSegment],
    context: AnalysisContext,
    analyzer: ClipAnalyzer,
    *,
    limit: int | None = None,
) -> list[ClipSuggestion]:
    """Analiza la transcripción entera y devuelve los mejores momentos.

    El fallo de una ventana no aborta el proyecto: se registra y se sigue con
    las demás, porque un único timeout no debería tirar 40 minutos de análisis.
    Solo se propaga el error si fallan todas.

    Raises:
        ExternalToolError: si ninguna ventana se ha podido analizar.
    """
    if not segments:
        return []

    windows = build_windows(
        segments,
        window_seconds=settings.analysis_chunk_seconds,
        overlap_seconds=settings.analysis_chunk_overlap_seconds,
    )
    logger.info(
        "ai.analysis_started",
        provider=analyzer.provider,
        segments=len(segments),
        windows=len(windows),
    )

    collected: list[ClipSuggestion] = []
    failures: list[str] = []
    started = time.perf_counter()

    for window in windows:
        try:
            collected.extend(analyzer.analyze_window(window, context))
        except ExternalToolError as exc:
            logger.warning("ai.window_failed", window=window.number, error=exc.message)
            failures.append(exc.message)

    if failures and len(failures) == len(windows):
        raise ExternalToolError(
            "El análisis con IA ha fallado en todas las ventanas",
            details={"first_error": failures[0], "windows": len(windows)},
        )

    selected = select_top(collected, limit=limit or settings.max_clips_per_project)
    logger.info(
        "ai.analysis_finished",
        proposed=len(collected),
        selected=len(selected),
        failed_windows=len(failures),
        seconds=round(time.perf_counter() - started, 1),
        top_score=selected[0].score if selected else None,
    )
    return selected
