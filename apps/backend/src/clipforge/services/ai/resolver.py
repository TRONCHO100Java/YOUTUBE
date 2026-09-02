"""Conversión de la respuesta del modelo en candidatos con timestamps reales.

Aquí es donde se garantiza la regla del proyecto: el modelo propone índices de
segmento y **el backend calcula los tiempos**. Todo lo que llega del LLM se
trata como no fiable — índices inventados, rangos invertidos, puntuaciones
fuera de rango, duraciones absurdas — y se corrige o se descarta.
"""

from __future__ import annotations

from collections.abc import Sequence

from clipforge.core.config import settings
from clipforge.core.logging import get_logger
from clipforge.services.ai.base import (
    AnalysisSegment,
    AnalysisWindow,
    ClipScores,
    ClipSuggestion,
)
from clipforge.services.ai.schema import RawClipCandidate

logger = get_logger(__name__)

#: Tope de cada dimensión, según el criterio de puntuación del proyecto.
SCORE_LIMITS: dict[str, int] = {
    "hook": 20,
    "curiosity": 20,
    "emotion": 15,
    "clarity": 15,
    "value": 15,
    "shareability": 10,
    "duration": 5,
}

#: Longitud máxima del extracto que se guarda como contexto del candidato.
MAX_EXCERPT_CHARS = 1500


def resolve_candidates(
    raw_candidates: Sequence[RawClipCandidate], window: AnalysisWindow
) -> list[ClipSuggestion]:
    """Valida las propuestas del modelo contra los segmentos reales de la ventana."""
    by_index = {segment.index: segment for segment in window.segments}
    resolved: list[ClipSuggestion] = []

    for raw in raw_candidates:
        suggestion = _resolve_one(raw, by_index)
        if suggestion is not None:
            resolved.append(suggestion)

    return resolved


def _resolve_one(
    raw: RawClipCandidate, by_index: dict[int, AnalysisSegment]
) -> ClipSuggestion | None:
    start_index, end_index = raw.start_segment, raw.end_segment

    # Un rango invertido es un descuido típico del modelo y se corrige solo.
    if start_index > end_index:
        start_index, end_index = end_index, start_index

    if start_index not in by_index or end_index not in by_index:
        logger.warning(
            "ai.candidate_rejected",
            reason="índices fuera de la ventana",
            start_segment=raw.start_segment,
            end_segment=raw.end_segment,
        )
        return None

    span = _adjust_duration(start_index, end_index, by_index)
    if span is None:
        return None
    start_index, end_index = span

    segments = [by_index[i] for i in sorted(by_index) if start_index <= i <= end_index]
    if not segments:
        return None

    title = raw.title.strip()
    if not title:
        logger.warning("ai.candidate_rejected", reason="sin título")
        return None

    return ClipSuggestion(
        start_segment=start_index,
        end_segment=end_index,
        start_time=segments[0].start,
        end_time=segments[-1].end,
        title=title[:300],
        hook=raw.hook.strip()[:500] or None,
        reason=raw.reason.strip() or None,
        scores=_clamp_scores(raw),
        transcript_excerpt=" ".join(s.text.strip() for s in segments)[:MAX_EXCERPT_CHARS],
    )


def _adjust_duration(
    start_index: int, end_index: int, by_index: dict[int, AnalysisSegment]
) -> tuple[int, int] | None:
    """Ajusta el rango para que quepa en los límites de duración configurados.

    Un rango algo largo se recorta por el final y uno algo corto se alarga: es
    preferible a descartar un buen momento por unos segundos de más o de menos.
    Si aun así no entra en los límites, se descarta.
    """
    ordered = sorted(i for i in by_index if start_index <= i <= end_index)
    if not ordered:
        return None

    minimum = settings.min_clip_duration
    maximum = settings.max_clip_duration

    def duration(first: int, last: int) -> float:
        return by_index[last].end - by_index[first].start

    # Demasiado largo: se recorta por el final, que es donde suele sobrar.
    while len(ordered) > 1 and duration(ordered[0], ordered[-1]) > maximum:
        ordered.pop()

    # Demasiado corto: se extiende con los segmentos siguientes disponibles.
    available = sorted(by_index)
    while duration(ordered[0], ordered[-1]) < minimum:
        position = available.index(ordered[-1])
        if position + 1 >= len(available):
            break
        candidate = available[position + 1]
        if duration(ordered[0], candidate) > maximum:
            break
        ordered.append(candidate)

    final = duration(ordered[0], ordered[-1])
    if not (minimum <= final <= maximum):
        logger.warning(
            "ai.candidate_rejected",
            reason="duración fuera de límites",
            duration=round(final, 1),
            min=minimum,
            max=maximum,
        )
        return None

    return ordered[0], ordered[-1]


def _clamp_scores(raw: RawClipCandidate) -> ClipScores:
    """Acota cada dimensión a su rango. Los modelos se salen con frecuencia."""
    return ClipScores(
        hook=_clamp(raw.hook_score, SCORE_LIMITS["hook"]),
        curiosity=_clamp(raw.curiosity_score, SCORE_LIMITS["curiosity"]),
        emotion=_clamp(raw.emotion_score, SCORE_LIMITS["emotion"]),
        clarity=_clamp(raw.clarity_score, SCORE_LIMITS["clarity"]),
        value=_clamp(raw.value_score, SCORE_LIMITS["value"]),
        shareability=_clamp(raw.shareability_score, SCORE_LIMITS["shareability"]),
        duration=_clamp(raw.duration_score, SCORE_LIMITS["duration"]),
    )


def _clamp(value: float, maximum: int) -> float:
    return float(max(0, min(maximum, value)))
