"""Conversión de la respuesta del modelo en candidatos con timestamps reales.

Aquí es donde se garantiza la regla del proyecto: el modelo propone índices
—de segmento en el análisis de texto, de bloque en el visual— y **el backend
calcula los tiempos**. Todo lo que llega del LLM se trata como no fiable:
índices inventados, rangos invertidos, puntuaciones fuera de rango, duraciones
absurdas. Se corrige o se descarta.
"""

from __future__ import annotations

from collections.abc import Sequence

from clipforge.core.logging import get_logger
from clipforge.db.models.enums import CandidateSource
from clipforge.services.ai.base import (
    AnalysisSegment,
    AnalysisWindow,
    ClipScores,
    ClipSuggestion,
)
from clipforge.services.ai.profiles import ProfileRules
from clipforge.services.ai.schema import (
    RawCandidateBase,
    RawClipCandidate,
    RawVisionCandidate,
)
from clipforge.services.signals.base import MomentBlock

logger = get_logger(__name__)

#: Longitud máxima del extracto que se guarda como contexto del candidato.
MAX_EXCERPT_CHARS = 1500


# --------------------------------------------------------------------- texto
def resolve_candidates(
    raw_candidates: Sequence[RawCandidateBase],
    window: AnalysisWindow,
    rules: ProfileRules,
) -> list[ClipSuggestion]:
    """Valida las propuestas del modelo contra los segmentos reales de la ventana."""
    by_index = {segment.index: segment for segment in window.segments}
    resolved: list[ClipSuggestion] = []

    for raw in raw_candidates:
        if not isinstance(raw, RawClipCandidate):
            continue
        suggestion = _resolve_one(raw, by_index, rules)
        if suggestion is not None:
            resolved.append(suggestion)

    return resolved


def _resolve_one(
    raw: RawClipCandidate, by_index: dict[int, AnalysisSegment], rules: ProfileRules
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

    span = _adjust_duration(start_index, end_index, by_index, rules)
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
        scores=clamp_scores(raw, rules),
        transcript_excerpt=" ".join(s.text.strip() for s in segments)[:MAX_EXCERPT_CHARS],
        source=CandidateSource.AI,
    )


def _adjust_duration(
    start_index: int,
    end_index: int,
    by_index: dict[int, AnalysisSegment],
    rules: ProfileRules,
) -> tuple[int, int] | None:
    """Ajusta el rango para que quepa en los límites de duración del perfil.

    Un rango algo largo se recorta por el final y uno algo corto se alarga: es
    preferible a descartar un buen momento por unos segundos de más o de menos.
    Si aun así no entra en los límites, se descarta.
    """
    ordered = sorted(i for i in by_index if start_index <= i <= end_index)
    if not ordered:
        return None

    minimum = rules.min_duration
    maximum = rules.max_duration

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


# -------------------------------------------------------------------- visión
def resolve_vision_candidates(
    raw_candidates: Sequence[RawCandidateBase],
    blocks: Sequence[MomentBlock],
    rules: ProfileRules,
) -> list[ClipSuggestion]:
    """Convierte propuestas sobre bloques en candidatos con tiempos reales."""
    resolved: list[ClipSuggestion] = []

    for raw in raw_candidates:
        if not isinstance(raw, RawVisionCandidate):
            continue

        # Los bloques se le presentan numerados desde 1.
        position = raw.block - 1
        if not 0 <= position < len(blocks):
            logger.warning("ai.candidate_rejected", reason="bloque inexistente", block=raw.block)
            continue

        title = raw.title.strip()
        if not title:
            logger.warning("ai.candidate_rejected", reason="sin título")
            continue

        span = _trim_block(blocks[position], raw.trim_start, raw.trim_end, rules)
        if span is None:
            continue
        start, end = span

        resolved.append(
            ClipSuggestion(
                start_segment=None,
                end_segment=None,
                start_time=start,
                end_time=end,
                title=title[:300],
                hook=raw.hook.strip()[:500] or None,
                reason=raw.reason.strip() or None,
                scores=clamp_scores(raw, rules),
                transcript_excerpt=None,
                source=CandidateSource.AI,
            )
        )

    return resolved


def _trim_block(
    block: MomentBlock, trim_start: int, trim_end: int, rules: ProfileRules
) -> tuple[float, float] | None:
    """Aplica los recortes que pide el modelo sin salirse del bloque.

    El recorte es una sugerencia, no una orden: si dejaría el clip por debajo
    del mínimo se aplica solo en parte. Un modelo pidiendo recortar 40 segundos
    de un bloque de 20 no debe producir un clip de duración negativa.
    """
    minimum = float(rules.min_duration)
    maximum = float(rules.max_duration)

    if block.duration <= 0:
        return None
    # Un bloque más corto que el mínimo solo puede aceptarse entero.
    if block.duration < minimum:
        return (block.start, block.end)

    latest_start = block.end - minimum
    start = min(max(block.start, block.start + max(0, trim_start)), latest_start)

    earliest_end = start + minimum
    end = max(min(block.end, block.end - max(0, trim_end)), earliest_end)

    if end - start > maximum:
        end = start + maximum

    return (start, end)


# --------------------------------------------------------------- puntuación
def clamp_scores(raw: RawCandidateBase, rules: ProfileRules) -> ClipScores:
    """Acota cada dimensión a su rango y la coloca en su columna.

    Los modelos se salen del rango con frecuencia, y la rúbrica visual usa
    nombres distintos ("payoff") sobre las mismas columnas ("curiosity"), así
    que la traducción tiene que pasar por el perfil.
    """
    columns: dict[str, float] = {}
    for dimension in rules.dimensions:
        value = raw.score_for(dimension.field_name)
        columns[dimension.column] = float(max(0, min(dimension.maximum, value)))

    return ClipScores(
        hook=columns.get("hook", 0.0),
        curiosity=columns.get("curiosity", 0.0),
        emotion=columns.get("emotion", 0.0),
        clarity=columns.get("clarity", 0.0),
        value=columns.get("value", 0.0),
        shareability=columns.get("shareability", 0.0),
        duration=columns.get("duration", 0.0),
    )
