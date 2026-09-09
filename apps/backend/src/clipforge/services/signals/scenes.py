"""Detección de cortes de plano.

Los cortes son el esqueleto del vídeo: en una recopilación de sketches marcan
dónde empieza y acaba cada gag. Son la señal que convierte "ocho minutos y
medio de vídeo" en "doce tramos con sentido propio", sin que haga falta
entender nada de lo que ocurre dentro.

El análisis se hace sobre una copia escalada a 320 px de ancho. El detector
compara histogramas, así que la resolución no le aporta precisión y sí le
cuesta tiempo: a 320 px va a unas 35 veces el tiempo real.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.logging import get_logger
from clipforge.services.video.binaries import run_tool

logger = get_logger(__name__)

SCENE_TIMEOUT_SECONDS = 30 * 60

#: Ancho al que se escala antes de analizar.
ANALYSIS_WIDTH = 320

_TIME_LINE = re.compile(r"pts_time:\s*([0-9.]+)")


def detect_cuts(video_path: Path, *, threshold: float | None = None) -> list[float]:
    """Instantes (en segundos) en los que cambia el plano.

    Nunca propaga un fallo: quedarse sin cortes degrada la calidad de los
    bloques, pero que la detección tumbe el proyecto entero sería mucho peor.
    """
    limit = threshold if threshold is not None else settings.signal_scene_threshold

    with tempfile.TemporaryDirectory(prefix="clipforge-scenes-") as tmp:
        workdir = Path(tmp)
        command = [
            settings.ffmpeg_path,
            "-hide_banner",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-vf",
            (
                f"scale={ANALYSIS_WIDTH}:-2,"
                f"select='gt(scene,{limit})',"
                "metadata=print:file=scenes.txt"
            ),
            "-an",
            "-f",
            "null",
            "-",
        ]
        try:
            run_tool(command, tool_name="ffmpeg", timeout=SCENE_TIMEOUT_SECONDS, cwd=workdir)
        except Exception as exc:
            logger.warning("signals.scene_detection_failed", error=str(exc))
            return []

        report = workdir / "scenes.txt"
        if not report.is_file():
            return []
        text = report.read_text(encoding="utf-8", errors="replace")

    cuts = sorted({float(match) for match in _TIME_LINE.findall(text)})
    logger.info("signals.cuts_detected", cuts=len(cuts), threshold=limit)
    return cuts
