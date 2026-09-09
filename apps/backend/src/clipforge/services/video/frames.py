"""Extracción de fotogramas sueltos para el análisis visual.

Un modelo con visión no puede ver un MP4: hay que enseñarle imágenes. De cada
bloque candidato se sacan unos pocos fotogramas repartidos por su duración, que
es suficiente para reconocer si hay una situación con remate dentro.

Se escalan a un ancho modesto a propósito: el coste de un modelo de visión
crece con el número de píxeles, y para decidir "aquí alguien se cae con una
bandeja" no hacen falta 1080 líneas.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.logging import get_logger
from clipforge.services.video.binaries import run_tool

logger = get_logger(__name__)

FRAME_TIMEOUT_SECONDS = 120

#: Ancho al que se escalan los fotogramas antes de enviarlos.
FRAME_WIDTH = 512

#: Calidad JPEG de ffmpeg (2 = casi sin pérdida, 31 = pésima). 5 mantiene los
#: detalles de una cara y deja el fichero en unas decenas de kilobytes.
JPEG_QUALITY = 5


@dataclass(frozen=True, slots=True)
class Frame:
    """Un fotograma extraído, con el instante del que procede."""

    time: float
    path: Path

    def to_base64(self) -> str:
        """Contenido en base64, que es como lo aceptan los tres proveedores."""
        return base64.b64encode(self.path.read_bytes()).decode("ascii")


def frame_times(start: float, end: float, count: int) -> list[float]:
    """Instantes repartidos por el tramo, sin caer justo en los extremos.

    Los bordes se evitan a propósito: el primer y el último fotograma de un
    plano suelen ser una transición o un fundido, y no describen la escena.
    """
    if count <= 0 or end <= start:
        return []
    span = end - start
    return [start + span * (index + 0.5) / count for index in range(count)]


def extract_frames(
    video: Path,
    destination: Path,
    *,
    start: float,
    end: float,
    count: int | None = None,
    prefix: str = "frame",
) -> list[Frame]:
    """Saca `count` fotogramas repartidos entre `start` y `end`.

    Un fotograma que falle se omite en lugar de tumbar la extracción: con que
    salgan la mayoría, el bloque sigue siendo analizable.
    """
    total = count or settings.vision_frames_per_block
    destination.mkdir(parents=True, exist_ok=True)

    frames: list[Frame] = []
    for index, moment in enumerate(frame_times(start, end, total)):
        output = destination / f"{prefix}_{index:02d}.jpg"
        command = [
            settings.ffmpeg_path,
            "-hide_banner",
            "-v",
            "error",
            "-y",
            # -ss antes de -i busca por el índice del contenedor: instantáneo
            # incluso en un fichero de varios gigabytes.
            "-ss",
            f"{moment:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            f"scale={FRAME_WIDTH}:-2",
            "-q:v",
            str(JPEG_QUALITY),
            str(output),
        ]
        try:
            run_tool(command, tool_name="ffmpeg", timeout=FRAME_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("frames.extraction_failed", time=round(moment, 1), error=str(exc))
            continue

        if output.is_file() and output.stat().st_size > 0:
            frames.append(Frame(time=moment, path=output))

    return frames
