"""Extracción de la pista de audio con ffmpeg.

Se genera WAV PCM de 16 kHz mono, que es exactamente el formato de entrada de
Whisper: así el modelo no tiene que remuestrear y el fichero sirve tal cual para
futuras pasadas (re-transcribir, detectar silencios) sin volver a tocar el vídeo.
"""

from __future__ import annotations

from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.video.binaries import run_tool

logger = get_logger(__name__)

#: Formato que espera Whisper.
SAMPLE_RATE = 16_000
CHANNELS = 1

#: Margen amplio: extraer audio es rápido, pero un vídeo de 4 h no es raro.
EXTRACTION_TIMEOUT_SECONDS = 30 * 60


def extract_audio(video_path: Path, destination: Path) -> Path:
    """Extrae el audio de `video_path` a `destination` (WAV 16 kHz mono).

    Raises:
        ExternalToolError: si el vídeo no existe, no tiene audio o ffmpeg falla.
    """
    if not video_path.is_file():
        raise ExternalToolError(f"No existe el vídeo de origen: {video_path}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    run_tool(
        [
            settings.ffmpeg_path,
            "-y",  # sobreescribe: permite reintentar un proyecto sin residuos
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vn",  # descarta el vídeo
            "-ac",
            str(CHANNELS),
            "-ar",
            str(SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ],
        tool_name="ffmpeg",
        timeout=EXTRACTION_TIMEOUT_SECONDS,
    )

    if not destination.is_file() or destination.stat().st_size == 0:
        raise ExternalToolError(
            "ffmpeg terminó sin generar audio: "
            f"¿el vídeo tiene pista de sonido? ({video_path.name})"
        )

    logger.info(
        "audio.extracted",
        source=video_path.name,
        size_mb=round(destination.stat().st_size / 1_048_576, 1),
    )
    return destination
