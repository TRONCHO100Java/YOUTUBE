"""La miniatura de un clip.

Sin ella la lista es una fila de rectangulos negros: la etiqueta `<video>` no
pinta nada hasta que alguien le da al play, y con veinte clips en pantalla no
se distingue uno de otro sin leer el titulo.

Cargar los veinte videos para que el navegador saque el primer fotograma
tampoco vale: son treinta megas cada uno. Una imagen de veinte kilos hace el
mismo trabajo.

Se saca UNA vez y se guarda al lado del clip. Generarla en cada peticion
costaria un ffmpeg por miniatura y por recarga de pagina.
"""

from __future__ import annotations

from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.video.binaries import run_tool

logger = get_logger(__name__)

#: Ancho de la miniatura. Se pinta a unos 90 px en la lista, asi que 320
#: sobra para pantallas de mucha densidad sin acercarse al peso de un video.
THUMB_WIDTH = 320

#: Segundo del que se saca. No el cero: el primer fotograma de un clip suele
#: pillar el final del plano anterior o un fundido, y sale gris.
THUMB_AT_SECONDS = 1.0

THUMB_TIMEOUT_SECONDS = 30


def thumbnail_path(clip_file: Path) -> Path:
    """Donde vive la miniatura de un clip: a su lado y con su nombre.

    Asi se borra con el, sin tener que acordarse de limpiarla aparte.
    """
    return clip_file.with_suffix(".jpg")


def ensure_thumbnail(clip_file: Path, *, at_seconds: float = THUMB_AT_SECONDS) -> Path:
    """Devuelve la miniatura del clip, generandola si no estaba.

    Raises:
        ExternalToolError: si el clip no existe o ffmpeg no saca nada.
    """
    if not clip_file.is_file():
        raise ExternalToolError(f"No existe el clip: {clip_file.name}")

    destination = thumbnail_path(clip_file)
    if destination.is_file() and destination.stat().st_size > 0:
        return destination

    command = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        # -ss antes de -i: busca por el indice en vez de decodificar hasta ahi.
        # Para un fotograma suelto es la diferencia entre instantaneo y no.
        "-ss",
        f"{at_seconds:.3f}",
        "-i",
        str(clip_file),
        "-frames:v",
        "1",
        "-vf",
        f"scale={THUMB_WIDTH}:-2",
        "-q:v",
        "4",
        str(destination),
    ]
    run_tool(command, tool_name="ffmpeg", timeout=THUMB_TIMEOUT_SECONDS)

    if not destination.is_file() or destination.stat().st_size == 0:
        # Un clip mas corto que el punto de corte deja a ffmpeg sin fotograma
        # que sacar. Se reintenta desde el principio antes de darlo por malo.
        if at_seconds > 0:
            return ensure_thumbnail(clip_file, at_seconds=0.0)
        raise ExternalToolError(f"ffmpeg no ha generado la miniatura de {clip_file.name}")

    logger.info("thumbnail.built", clip=clip_file.name)
    return destination
