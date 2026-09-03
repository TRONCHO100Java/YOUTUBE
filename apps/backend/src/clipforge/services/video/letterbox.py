"""Detección del letterbox incrustado en el vídeo de origen.

Muchos vídeos de YouTube llevan barras negras quemadas en la imagen (montaje
"cinematográfico"). Si se recorta la altura completa, esas barras acaban dentro
del clip vertical y desperdician una cuarta parte del encuadre.

`ffmpeg` trae `cropdetect`, que analiza unos fotogramas y propone la región con
contenido real. Se ejecuta una vez por proyecto, no por clip.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.logging import get_logger
from clipforge.services.video.binaries import run_tool
from clipforge.services.video.crop import CropWindow

logger = get_logger(__name__)

DETECT_TIMEOUT_SECONDS = 120

#: Fotogramas a analizar. Suficientes para no dejarse engañar por un fundido a
#: negro, y lo bastante pocos para que el análisis dure un instante.
SAMPLE_FRAMES = 120

#: Si la región detectada conserva menos de esto, es que el muestreo cayó en una
#: escena oscura: se descarta y se usa el fotograma completo.
MIN_CONTENT_RATIO = 0.5

_CROP_LINE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def detect_content_window(
    video: Path, source_width: int, source_height: int, *, start: float = 0.0
) -> CropWindow:
    """Devuelve la región con imagen real, sin las barras negras incrustadas.

    Ante cualquier duda devuelve el fotograma completo: recortar de más
    estropearía el encuadre, y no recortar solo deja unas barras.
    """
    full = CropWindow(x=0, y=0, width=source_width, height=source_height)

    command = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video),
        "-vf",
        # limit=24 tolera negros no puros (compresión); round=2 mantiene las
        # dimensiones pares que exige H.264.
        "cropdetect=limit=24:round=2",
        "-frames:v",
        str(SAMPLE_FRAMES),
        "-f",
        "null",
        "-",
    ]

    try:
        # cropdetect escribe en stderr con nivel `info`, así que aquí no se puede
        # silenciar el log como en el resto de llamadas a ffmpeg.
        completed = run_tool(command, tool_name="ffmpeg", timeout=DETECT_TIMEOUT_SECONDS)
    except Exception as exc:  # la detección nunca debe romper el render
        logger.warning("letterbox.detection_failed", error=str(exc))
        return full

    matches = _CROP_LINE.findall(completed.stderr or "")
    if not matches:
        return full

    # La propuesta más repetida a lo largo del muestreo es la fiable.
    width, height, x, y = (int(value) for value in Counter(matches).most_common(1)[0][0])
    detected = CropWindow(x=x, y=y, width=width, height=height)

    area_ratio = (width * height) / (source_width * source_height)
    if area_ratio < MIN_CONTENT_RATIO:
        logger.warning("letterbox.detection_discarded", ratio=round(area_ratio, 2))
        return full

    if detected == full:
        return full

    logger.info(
        "letterbox.detected",
        source=f"{source_width}x{source_height}",
        content=f"{width}x{height}+{x}+{y}",
    )
    return detected
