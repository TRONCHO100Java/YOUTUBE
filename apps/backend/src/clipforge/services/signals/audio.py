"""Curva de energía del audio y detección de sus picos.

En un vídeo sin diálogo, el volumen es la mejor pista barata de dónde está el
remate: un golpe, una caída, una risa o un acento musical dejan un máximo local
claro. Medirlo cuesta un par de segundos de ffmpeg sobre el WAV que el pipeline
ya extrae para Whisper.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.logging import get_logger
from clipforge.services.signals.base import (
    EnergyPeak,
    SamplePoint,
    normalize,
    parse_metadata_stream,
)
from clipforge.services.video.binaries import run_tool

logger = get_logger(__name__)

ENERGY_TIMEOUT_SECONDS = 10 * 60

#: Frecuencia a la que ffmpeg remuestrea antes de medir. La energía no necesita
#: fidelidad: 8 kHz mide igual de bien y va más rápido.
ANALYSIS_SAMPLE_RATE = 8000


def measure_energy(audio_path: Path, *, interval_seconds: float | None = None) -> list[SamplePoint]:
    """Devuelve el nivel RMS en dB cada `interval_seconds`.

    Raises:
        ExternalToolError: si ffmpeg falla o no está instalado.
    """
    interval = interval_seconds or settings.signal_energy_interval_seconds
    samples_per_window = max(1, int(ANALYSIS_SAMPLE_RATE * interval))

    with tempfile.TemporaryDirectory(prefix="clipforge-energy-") as tmp:
        workdir = Path(tmp)
        command = [
            settings.ffmpeg_path,
            "-hide_banner",
            "-v",
            "error",
            "-i",
            str(audio_path),
            "-af",
            (
                f"aresample={ANALYSIS_SAMPLE_RATE},"
                f"asetnsamples={samples_per_window},"
                "astats=metadata=1:reset=1,"
                "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=energy.txt"
            ),
            "-f",
            "null",
            "-",
        ]
        # Igual que en el render: el parser de filtros de ffmpeg trata `:` como
        # sintaxis propia, así que una ruta absoluta de Windows lo rompe. Se
        # ejecuta desde el directorio de trabajo y se le pasa solo el nombre.
        run_tool(command, tool_name="ffmpeg", timeout=ENERGY_TIMEOUT_SECONDS, cwd=workdir)

        report = workdir / "energy.txt"
        if not report.is_file():
            logger.warning("signals.energy_empty", audio=audio_path.name)
            return []
        points = parse_metadata_stream(report.read_text(encoding="utf-8", errors="replace"))

    logger.info("signals.energy_measured", samples=len(points), interval=interval)
    return points


def find_peaks(
    points: list[SamplePoint],
    *,
    percentile: float = 0.90,
    min_gap_seconds: float = 8.0,
) -> list[EnergyPeak]:
    """Máximos locales por encima del percentil dado, separados entre sí.

    El umbral es relativo al propio vídeo y no un valor absoluto en dB: la
    comedia de este tipo viene con el audio muy comprimido (siete decibelios de
    rango en el vídeo con el que se diseñó esto), y cualquier corte fijo o los
    marcaría todos o ninguno.

    `min_gap_seconds` colapsa las ráfagas: una carcajada larga produce cinco
    máximos consecutivos que son un único momento.
    """
    if not points:
        return []

    values = sorted(point.value for point in points)
    threshold = values[min(len(values) - 1, int(len(values) * percentile))]
    floor = values[len(values) // 2]  # mediana: el nivel de fondo del vídeo
    ceiling = values[-1]

    # Radio de la ventana en muestras a partir del hueco temporal pedido.
    span = _sample_interval(points)
    radius = max(1, round(min_gap_seconds / 2 / span)) if span > 0 else 1

    peaks: list[EnergyPeak] = []
    for index, point in enumerate(points):
        if point.value < threshold:
            continue
        window = points[max(0, index - radius) : index + radius + 1]
        if point.value < max(sample.value for sample in window):
            continue
        # Empate dentro de la ventana: se queda el primero, que es donde
        # empieza el sonido. Marcar el final de una carcajada corta el gag.
        if peaks and point.time - peaks[-1].time < min_gap_seconds:
            if point.value <= peaks[-1].level:
                continue
            peaks.pop()
        peaks.append(
            EnergyPeak(
                time=point.time,
                level=point.value,
                prominence=normalize(point.value, floor, ceiling),
            )
        )

    logger.info("signals.peaks_found", peaks=len(peaks), threshold=round(threshold, 1))
    return peaks


def speech_ratio(speech_seconds: float, total_seconds: float) -> float:
    """Fracción del vídeo que contiene habla real, entre 0 y 1.

    Es el dato que decide el perfil de contenido. En el vídeo de comedia con el
    que se diseñó esto vale 0,009: 4,5 segundos de "habla" (alucinada) sobre
    519 de vídeo.
    """
    if total_seconds <= 0:
        return 0.0
    return max(0.0, min(1.0, speech_seconds / total_seconds))


def _sample_interval(points: list[SamplePoint]) -> float:
    """Separación típica entre muestras, para traducir segundos a índices."""
    if len(points) < 2:
        return 0.0
    return (points[-1].time - points[0].time) / (len(points) - 1)
