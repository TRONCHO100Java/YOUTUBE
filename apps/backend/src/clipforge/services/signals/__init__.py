"""Señales no verbales del vídeo: energía, cortes de plano y movimiento.

Existe porque el análisis de la FASE 4 solo sabe leer texto, y hay vídeos que
no hablan. Sobre una recopilación de comedia física sin diálogo, la
transcripción daba tres segmentos y quince caracteres; estas señales dan doce
tramos bien delimitados con diecisiete segundos de ffmpeg.
"""

from clipforge.services.signals.audio import find_peaks, measure_energy, speech_ratio
from clipforge.services.signals.base import (
    EnergyPeak,
    MomentBlock,
    SamplePoint,
    SignalTimeline,
)
from clipforge.services.signals.blocks import build_blocks, rank_blocks, segment_by_cuts
from clipforge.services.signals.motion import measure_motion
from clipforge.services.signals.scenes import detect_cuts
from clipforge.services.signals.timeline import build_timeline

__all__ = [
    "EnergyPeak",
    "MomentBlock",
    "SamplePoint",
    "SignalTimeline",
    "build_blocks",
    "build_timeline",
    "detect_cuts",
    "find_peaks",
    "measure_energy",
    "measure_motion",
    "rank_blocks",
    "segment_by_cuts",
    "speech_ratio",
]
