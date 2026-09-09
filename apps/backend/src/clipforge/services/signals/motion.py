"""Medida de movimiento: cuánta acción física hay en cada instante.

Distingue lo que la energía del audio no puede: dos personas quietas hablando
frente a alguien resbalando con una bandeja. En comedia física el remate casi
siempre coincide con un máximo de movimiento, y a menudo llega una fracción de
segundo antes que el golpe sonoro.

Se calcula como el brillo medio de la diferencia entre fotogramas consecutivos:
si nada se mueve, la diferencia es negra y el valor cae a cero.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.logging import get_logger
from clipforge.services.signals.base import SamplePoint, parse_metadata_stream
from clipforge.services.video.binaries import run_tool

logger = get_logger(__name__)

MOTION_TIMEOUT_SECONDS = 30 * 60

#: Ancho de análisis. Igual que en la detección de cortes, la resolución no
#: mejora la medida: un plano tiene el mismo movimiento relativo a 160 px.
ANALYSIS_WIDTH = 160

#: Fotogramas por segundo a los que se muestrea. A 4 fps la curva sigue
#: describiendo bien un gag y se procesan siete veces menos fotogramas.
ANALYSIS_FPS = 4


def measure_motion(video_path: Path) -> list[SamplePoint]:
    """Devuelve la intensidad de movimiento a lo largo del vídeo (0..255).

    Como la detección de cortes, degrada en silencio: sin curva de movimiento
    los bloques se puntúan solo con audio, que sigue siendo utilizable.
    """
    with tempfile.TemporaryDirectory(prefix="clipforge-motion-") as tmp:
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
                f"fps={ANALYSIS_FPS},"
                # tblend en modo diferencia deja negro lo que no ha cambiado;
                # signalstats mide entonces el brillo medio de ese residuo.
                "tblend=all_mode=difference,"
                "signalstats,"
                "metadata=print:key=lavfi.signalstats.YAVG:file=motion.txt"
            ),
            "-an",
            "-f",
            "null",
            "-",
        ]
        try:
            run_tool(command, tool_name="ffmpeg", timeout=MOTION_TIMEOUT_SECONDS, cwd=workdir)
        except Exception as exc:
            logger.warning("signals.motion_failed", error=str(exc))
            return []

        report = workdir / "motion.txt"
        if not report.is_file():
            return []
        points = parse_metadata_stream(report.read_text(encoding="utf-8", errors="replace"))

    logger.info("signals.motion_measured", samples=len(points))
    return points
