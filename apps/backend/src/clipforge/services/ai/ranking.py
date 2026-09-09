"""Deduplicación y ranking global de candidatos.

Las ventanas se solapan a propósito, así que el mismo momento aparece a menudo
en dos análisis con puntuaciones distintas. Aquí se colapsan esos duplicados y
se elige el top N final del proyecto.

Lógica pura y sin dependencias externas: se prueba sin API ni base de datos.
"""

from __future__ import annotations

from collections.abc import Sequence

from clipforge.services.ai.base import ClipSuggestion

#: Dos candidatos se consideran el mismo momento si comparten más de esta
#: fracción del más corto de los dos. Un valor bajo agrupa de más y se pierden
#: clips contiguos legítimos; uno alto deja pasar casi-duplicados.
DEFAULT_OVERLAP_THRESHOLD = 0.5


def overlap_ratio(a: ClipSuggestion, b: ClipSuggestion) -> float:
    """Solape temporal como fracción del candidato más corto (0..1)."""
    overlap = min(a.end_time, b.end_time) - max(a.start_time, b.start_time)
    if overlap <= 0:
        return 0.0
    shortest = min(a.duration, b.duration)
    if shortest <= 0:
        return 0.0
    return overlap / shortest


def deduplicate(
    candidates: Sequence[ClipSuggestion],
    *,
    threshold: float = DEFAULT_OVERLAP_THRESHOLD,
) -> list[ClipSuggestion]:
    """Colapsa candidatos solapados, quedándose con el mejor puntuado.

    Se recorre de mayor a menor puntuación, de modo que el que sobrevive a un
    grupo de duplicados es siempre el mejor valorado.
    """
    kept: list[ClipSuggestion] = []
    for candidate in sorted(candidates, key=_ranking_key, reverse=True):
        if any(overlap_ratio(candidate, existing) > threshold for existing in kept):
            continue
        kept.append(candidate)
    return kept


def rank(candidates: Sequence[ClipSuggestion]) -> list[ClipSuggestion]:
    """Ordena de mejor a peor."""
    return sorted(candidates, key=_ranking_key, reverse=True)


def select_top(
    candidates: Sequence[ClipSuggestion],
    *,
    limit: int,
    threshold: float = DEFAULT_OVERLAP_THRESHOLD,
) -> list[ClipSuggestion]:
    """Deduplica, ordena y devuelve como mucho `limit` candidatos."""
    if limit <= 0:
        return []
    return rank(deduplicate(candidates, threshold=threshold))[:limit]


def _ranking_key(candidate: ClipSuggestion) -> tuple[float, float, float]:
    """Puntuación primero; a igualdad, el gancho manda y luego el más temprano.

    El desempate importa: sin él el orden depende del orden de llegada de las
    ventanas y dos ejecuciones idénticas producen rankings distintos.
    """
    return (candidate.score, candidate.hook_score, -candidate.start_time)
