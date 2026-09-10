"""Orquestación del análisis: transcripción o señales → mejores clips.

Tres estrategias, en orden de preferencia:

1. **Texto.** Trocea la transcripción, la analiza por ventanas y deduplica.
   Es lo que funciona con un pódcast o una entrevista.
2. **Visión.** Enseña fotogramas de los bloques con más señal a un modelo
   multimodal. Es lo que hace falta cuando el vídeo no habla.
3. **Señales a secas.** Convierte los propios bloques en candidatos, sin que
   ninguna IA los juzgue. No es tan bueno, pero **nunca devuelve una lista
   vacía**, y eso vale más que la alternativa: hasta ahora, un análisis sin
   resultados marcaba el proyecto como fallido y tiraba la descarga entera.

Se mantiene separado de los clientes de cada proveedor para poder probar la
estrategia con un analizador de prueba, sin gastar tokens.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.db.models.enums import CandidateSource
from clipforge.services.ai.base import (
    AnalysisContext,
    AnalysisSegment,
    BlockAnalyzer,
    ClipAnalyzer,
    ClipSuggestion,
)
from clipforge.services.ai.chunking import build_windows
from clipforge.services.ai.prompts import timestamp
from clipforge.services.ai.ranking import select_top
from clipforge.services.signals.base import MomentBlock

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
        profile=context.profile.value,
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


def select_clips_from_blocks(
    blocks: Sequence[MomentBlock],
    context: AnalysisContext,
    analyzer: BlockAnalyzer,
    *,
    video_path: Path,
    workdir: Path,
    limit: int | None = None,
) -> list[ClipSuggestion]:
    """Analiza con visión los bloques mejor puntuados por las señales.

    No se le enseñan todos: en un vídeo largo pueden salir cientos, y mirarlos
    todos multiplica el coste sin mejorar el resultado. Los bloques llegan ya
    ordenados por señal, así que quedarse con la cabeza es quedarse con lo que
    más ruido y movimiento tiene.

    Raises:
        ExternalToolError: si el proveedor de visión falla.
    """
    if not blocks:
        return []

    shortlist = list(blocks[: settings.vision_max_blocks])
    logger.info(
        "ai.vision_started",
        provider=analyzer.provider,
        blocks=len(shortlist),
        of_total=len(blocks),
    )

    suggestions = analyzer.analyze_blocks(
        shortlist, context, video_path=video_path, workdir=workdir
    )
    selected = select_top(suggestions, limit=limit or settings.max_clips_per_project)

    logger.info(
        "ai.vision_finished",
        proposed=len(suggestions),
        selected=len(selected),
        top_score=selected[0].score if selected else None,
    )
    return selected


def suggestions_from_signals(
    blocks: Sequence[MomentBlock], *, limit: int | None = None
) -> list[ClipSuggestion]:
    """Convierte bloques en candidatos sin pasar por ninguna IA.

    Es la red de seguridad del pipeline. Los candidatos que salen de aquí no
    llevan título de verdad ni justificación —nadie los ha mirado— así que se
    nombran por su posición en el vídeo y se marcan como `SIGNAL` para que el
    frontend pueda decir con honestidad de dónde salen.
    """
    top = list(blocks[: limit or settings.max_clips_per_project])
    if not top:
        return []

    logger.info("ai.signal_fallback", candidates=len(top), best_score=top[0].score)
    return [
        ClipSuggestion(
            start_segment=None,
            end_segment=None,
            start_time=block.start,
            end_time=block.end,
            title=f"Moment at {timestamp(block.start)}",
            hook=None,
            reason=(
                f"Detectado por señales: {block.peaks} picos de sonido, "
                f"volumen {block.energy:.2f} y movimiento {block.motion:.2f} "
                "sobre el resto del vídeo. Nadie lo ha visto todavía."
            ),
            scores=None,
            transcript_excerpt=None,
            source=CandidateSource.SIGNAL,
            signal_score=block.score,
        )
        for block in top
    ]
