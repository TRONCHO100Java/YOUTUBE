"""Orquestación de las señales: vídeo y audio → línea de tiempo completa.

Es el equivalente de `selector.py` para la parte no verbal. Encadena las tres
medidas, construye los bloques y devuelve un objeto único que se guarda en
`projects.signals` y consumen tanto el análisis como el editor del frontend.

Ninguna medida es obligatoria: si falla la de movimiento, los bloques se
puntúan solo con audio; si falla la de cortes, el vídeo se reparte en tramos
regulares. Lo único que no se puede perder es la propia línea de tiempo.
"""

from __future__ import annotations

import time
from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.logging import get_logger
from clipforge.services.signals.audio import find_peaks, measure_energy
from clipforge.services.signals.base import SignalTimeline, downsample
from clipforge.services.signals.blocks import build_blocks, rank_blocks, segment_by_cuts
from clipforge.services.signals.motion import measure_motion
from clipforge.services.signals.scenes import detect_cuts

logger = get_logger(__name__)

#: Tope de puntos que se guardan de cada curva. Con 900 la línea de tiempo se
#: dibuja fluida a cualquier ancho de pantalla y el JSON no pasa de unos cientos
#: de kilobytes ni en un vídeo de dos horas.
CURVE_POINT_LIMIT = 900


def build_timeline(
    video_path: Path,
    audio_path: Path | None,
    *,
    duration: float,
    min_block_seconds: float,
    max_block_seconds: float,
    target_block_seconds: float,
) -> SignalTimeline:
    """Mide las tres señales del vídeo y devuelve sus bloques ya ordenados."""
    started = time.perf_counter()

    energy = measure_energy(audio_path) if audio_path and audio_path.is_file() else []
    peaks = find_peaks(energy, min_gap_seconds=settings.signal_peak_min_gap_seconds)
    cuts = detect_cuts(video_path)
    motion = measure_motion(video_path) if settings.signal_measure_motion else []

    spans = segment_by_cuts(
        cuts,
        duration,
        min_duration=min_block_seconds,
        max_duration=max_block_seconds,
    )
    blocks = rank_blocks(
        build_blocks(
            spans,
            energy=energy,
            motion=motion,
            peaks=peaks,
            cuts=cuts,
            target_duration=target_block_seconds,
        )
    )

    timeline = SignalTimeline(
        duration=duration,
        energy=downsample(energy, CURVE_POINT_LIMIT),
        peaks=peaks,
        cuts=cuts,
        motion=downsample(motion, CURVE_POINT_LIMIT),
        blocks=blocks,
    )

    logger.info(
        "signals.timeline_built",
        seconds=round(time.perf_counter() - started, 1),
        energy_samples=len(energy),
        peaks=len(peaks),
        cuts=len(cuts),
        motion_samples=len(motion),
        blocks=len(blocks),
        best_score=blocks[0].score if blocks else None,
    )
    return timeline
