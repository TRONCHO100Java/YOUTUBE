"""Troceado de la transcripción en ventanas analizables.

Un vídeo de una hora no cabe cómodamente en una sola llamada, y aunque cupiera
el modelo pierde precisión sobre un contexto enorme. Se parte en ventanas
temporales con solapamiento para que un buen momento a caballo entre dos
ventanas siga apareciendo entero en al menos una de ellas.

Es lógica pura y sin dependencias: se puede probar sin API ni base de datos.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from clipforge.services.ai.base import AnalysisSegment, AnalysisWindow


def build_windows(
    segments: Sequence[AnalysisSegment],
    *,
    window_seconds: float,
    overlap_seconds: float,
) -> list[AnalysisWindow]:
    """Reparte los segmentos en ventanas solapadas.

    Args:
        segments: segmentos ordenados por tiempo.
        window_seconds: duración objetivo de cada ventana.
        overlap_seconds: solapamiento entre ventanas consecutivas.

    Raises:
        ValueError: si la ventana no es positiva o el solapamiento la iguala o
            supera (produciría ventanas infinitas sin avanzar).
    """
    if window_seconds <= 0:
        raise ValueError("window_seconds debe ser positivo")
    if overlap_seconds < 0:
        raise ValueError("overlap_seconds no puede ser negativo")
    if overlap_seconds >= window_seconds:
        raise ValueError("overlap_seconds debe ser menor que window_seconds")

    ordered = sorted(segments, key=lambda s: (s.start, s.index))
    if not ordered:
        return []

    step = window_seconds - overlap_seconds
    windows: list[AnalysisWindow] = []
    cursor = 0
    number = 1

    while cursor < len(ordered):
        window_start = ordered[cursor].start
        limit = window_start + window_seconds

        end = cursor
        while end < len(ordered) and ordered[end].start < limit:
            end += 1
        # Una ventana siempre contiene al menos un segmento: un segmento más
        # largo que la ventana entera no puede quedar fuera del análisis.
        end = max(end, cursor + 1)

        windows.append(AnalysisWindow(number=number, segments=list(ordered[cursor:end])))
        number += 1

        if end >= len(ordered):
            break

        # El siguiente arranque se busca por tiempo, no por número de segmentos:
        # así el solapamiento real es el pedido, con segmentos de cualquier duración.
        next_start_time = window_start + step
        next_cursor = cursor + 1
        while next_cursor < len(ordered) and ordered[next_cursor].start < next_start_time:
            next_cursor += 1
        cursor = next_cursor

    return windows


def to_analysis_segments(rows: Iterable[object]) -> list[AnalysisSegment]:
    """Adapta filas de `TranscriptSegment` al modelo que consume el análisis."""
    return [
        AnalysisSegment(
            index=row.index,  # type: ignore[attr-defined]
            start=float(row.start_time),  # type: ignore[attr-defined]
            end=float(row.end_time),  # type: ignore[attr-defined]
            text=row.text,  # type: ignore[attr-defined]
        )
        for row in rows
    ]
