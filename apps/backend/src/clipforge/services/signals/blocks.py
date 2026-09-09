"""Construcción y puntuación de bloques candidatos a partir de las señales.

Lógica pura: recibe listas de números y devuelve tramos. Ni ffmpeg, ni base de
datos, ni IA, así que se puede probar entera sin GPU y sin tokens — igual que
`chunking.py` y `ranking.py`.

La idea es sencilla: los cortes de plano parten el vídeo, los tramos demasiado
cortos se fusionan con sus vecinos y los demasiado largos se reparten. Lo que
queda son tramos con sentido propio, que después se ordenan por lo que ocurre
dentro de ellos.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from clipforge.services.signals.base import (
    EnergyPeak,
    MomentBlock,
    SamplePoint,
    normalize,
)

#: Peso de cada señal en la puntuación del bloque.
#:
#: La energía manda porque es la que mejor marca el remate, y el movimiento la
#: acompaña porque en comedia física ambos coinciden. La densidad de cortes
#: pesa poco: distingue un montaje ágil de un plano fijo, pero un plano fijo
#: puede ser graciosísimo. El ajuste de duración es un desempate, no un criterio.
WEIGHT_ENERGY = 0.40
WEIGHT_MOTION = 0.25
WEIGHT_PEAKS = 0.20
WEIGHT_DURATION = 0.15

#: A partir de este número de picos por minuto, el bloque ya puntúa al máximo
#: en esa dimensión. Más picos no lo hacen más gracioso, solo más ruidoso.
PEAKS_PER_MINUTE_SATURATION = 6.0


def segment_by_cuts(
    cuts: Sequence[float],
    duration: float,
    *,
    min_duration: float,
    max_duration: float,
) -> list[tuple[float, float]]:
    """Reparte el vídeo en tramos publicables usando los cortes como fronteras.

    Tres pasos, en orden:

    1. Los cortes definen los tramos crudos.
    2. Los tramos por debajo del mínimo se acumulan con los siguientes hasta
       llegar a él. Es lo que agrupa una ráfaga de planos rápidos en un gag.
    3. Los tramos por encima del máximo se reparten en partes iguales, de forma
       que ninguna quede corta.

    Raises:
        ValueError: si el mínimo no es menor que el máximo.
    """
    if min_duration <= 0 or max_duration < min_duration:
        raise ValueError("min_duration debe ser positivo y no mayor que max_duration")
    if duration <= 0:
        return []

    boundaries = [0.0, *sorted(c for c in cuts if 0.0 < c < duration), duration]
    raw = [(a, b) for a, b in pairwise(boundaries) if b - a > 0]
    if not raw:
        return []

    merged = _merge_short(raw, min_duration)

    spans: list[tuple[float, float]] = []
    for start, end in merged:
        spans.extend(_split_long(start, end, max_duration))
    return spans


def build_blocks(
    spans: Sequence[tuple[float, float]],
    *,
    energy: Sequence[SamplePoint] = (),
    motion: Sequence[SamplePoint] = (),
    peaks: Sequence[EnergyPeak] = (),
    cuts: Sequence[float] = (),
    target_duration: float,
) -> list[MomentBlock]:
    """Puntúa cada tramo con lo que ocurre dentro, de mejor a peor.

    Las señales se normalizan **contra el propio vídeo**, no contra valores
    absolutos: un vídeo con el audio muy comprimido y otro con mucho rango
    dinámico se puntúan cada uno en su propia escala, y comparar bloques de
    vídeos distintos no tiene sentido de todas formas.
    """
    if not spans:
        return []

    raw_energy = [_mean_in_range(energy, start, end) for start, end in spans]
    raw_motion = [_mean_in_range(motion, start, end) for start, end in spans]
    energy_low, energy_high = _range(raw_energy)
    motion_low, motion_high = _range(raw_motion)

    blocks: list[MomentBlock] = []
    for index, (start, end) in enumerate(spans):
        span_duration = end - start
        minutes = max(span_duration / 60.0, 1e-6)

        peak_count = sum(1 for peak in peaks if start <= peak.time < end)
        cut_count = sum(1 for cut in cuts if start < cut < end)

        energy_norm = normalize(raw_energy[index], energy_low, energy_high)
        motion_norm = normalize(raw_motion[index], motion_low, motion_high)
        peaks_norm = min(1.0, (peak_count / minutes) / PEAKS_PER_MINUTE_SATURATION)
        duration_norm = duration_fit(span_duration, target_duration)

        score = 100.0 * (
            WEIGHT_ENERGY * energy_norm
            + WEIGHT_MOTION * motion_norm
            + WEIGHT_PEAKS * peaks_norm
            + WEIGHT_DURATION * duration_norm
        )

        blocks.append(
            MomentBlock(
                start=start,
                end=end,
                energy=energy_norm,
                motion=motion_norm,
                peaks=peak_count,
                cut_rate=cut_count / minutes,
                score=round(score, 2),
            )
        )

    return blocks


def rank_blocks(blocks: Sequence[MomentBlock], *, limit: int | None = None) -> list[MomentBlock]:
    """Ordena de mejor a peor. A igualdad, gana el más temprano del vídeo.

    El desempate no es cosmético: sin él, dos ejecuciones sobre el mismo vídeo
    devuelven órdenes distintos y comparar resultados se vuelve imposible.
    """
    ordered = sorted(blocks, key=lambda block: (-block.score, block.start))
    return ordered[:limit] if limit is not None else ordered


def duration_fit(span_duration: float, target: float) -> float:
    """1 en la duración ideal, decayendo hacia 0 al alejarse de ella."""
    if target <= 0:
        return 0.0
    return max(0.0, 1.0 - abs(span_duration - target) / target)


# ------------------------------------------------------------------- internos
def _merge_short(
    spans: Sequence[tuple[float, float]], min_duration: float
) -> list[tuple[float, float]]:
    """Acumula tramos consecutivos hasta que cada grupo llega al mínimo."""
    merged: list[tuple[float, float]] = []
    open_start: float | None = None

    for start, end in spans:
        if open_start is None:
            open_start = start
        if end - open_start >= min_duration:
            merged.append((open_start, end))
            open_start = None

    # Cola por debajo del mínimo: se pega al bloque anterior en vez de
    # descartarla, porque suele contener el final del último gag.
    if open_start is not None:
        tail_end = spans[-1][1]
        if merged:
            merged[-1] = (merged[-1][0], tail_end)
        else:
            merged.append((open_start, tail_end))

    return merged


def _split_long(start: float, end: float, max_duration: float) -> list[tuple[float, float]]:
    """Parte un tramo largo en trozos iguales, todos por debajo del máximo."""
    total = end - start
    if total <= max_duration:
        return [(start, end)]

    parts = math.ceil(total / max_duration)
    size = total / parts
    return [(start + index * size, start + (index + 1) * size) for index in range(parts)]


def _mean_in_range(points: Sequence[SamplePoint], start: float, end: float) -> float:
    """Valor medio de una serie dentro de un tramo.

    Un tramo sin muestras devuelve el mínimo de la serie, no cero: en una curva
    de decibelios el cero es un valor altísimo y colaría un bloque vacío como
    el más ruidoso del vídeo.
    """
    inside = [point.value for point in points if start <= point.time < end]
    if inside:
        return sum(inside) / len(inside)
    return min((point.value for point in points), default=0.0)


def _range(values: Sequence[float]) -> tuple[float, float]:
    """Extremos de una serie, tolerando que esté vacía o sea constante."""
    if not values:
        return 0.0, 0.0
    return min(values), max(values)
