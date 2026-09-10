"""El cierre que se pega al final de cada clip.

Existe por dos razones distintas. La primera es de marca: un clip que acaba
con el nombre del canal y una llamada a suscribirse parece **del canal**, no un
trozo del video de otro. La segunda es de politica: YouTube mira si aportas
algo propio, y un cierre pegado no es lo que te salva, pero cuenta.

Se fabrica a partir de una plantilla y no desde cero. Recrear la animacion del
logo con filtros seria dibujar a mano algo que ya existe, y quedaria peor; lo
unico que cambia de un canal a otro es el nombre, asi que se tapa el que trae
la plantilla y se escribe el nuevo encima.

Eso funciona porque el fondo de esa franja es negro puro: comprobado sobre la
plantilla, la banda del nombre no tiene ni degradado ni logo detras, asi que un
rectangulo negro es indistinguible del fondo. Si algun dia la plantilla cambia
por una con fondo degradado, esto hay que replantearlo, no ajustarlo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.errors import ClipForgeError, ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.video.binaries import run_tool
from clipforge.services.video.probe import probe_video

logger = get_logger(__name__)

#: Fuente del texto. Arial Bold es la del sistema que mas se parece a la de la
#: plantilla; usar otra haria que el nombre nuevo cantase al lado del resto.
FONT_PATH = Path("C:/Windows/Fonts/arialbd.ttf")

#: Franja que ocupa el nombre en la plantilla, medida sobre ella. Se tapa
#: entera y se vuelve a escribir centrada.
HANDLE_TOP = 1487
HANDLE_HEIGHT = 66
HANDLE_SIZE = 46

#: Franja de la linea roja de debajo ("NEW CLIPS EVERY DAY"). Solo se toca si
#: el canal quiere decir otra cosa; si no, se deja la de la plantilla.
TAGLINE_TOP = 1560
TAGLINE_HEIGHT = 50
TAGLINE_SIZE = 38

BUILD_TIMEOUT_SECONDS = 120

#: Lo que hay que escapar dentro de un `drawtext`: el filtro parte el texto por
#: los dos puntos y trata la barra invertida como escape.
_ESCAPES = {"\\": r"\\", ":": r"\:", "'": r"\'", "%": r"\%"}


@dataclass(frozen=True, slots=True)
class OutroText:
    """Lo que distingue el cierre de un canal del de otro."""

    #: El nombre con arroba: "@ClipRushViralRush".
    handle: str
    #: La linea roja. None deja la que trae la plantilla.
    tagline: str | None = None


def outro_template() -> Path:
    """La plantilla compartida de la que salen todos los cierres.

    Una sola para todos los canales: el fondo y la animacion son los
    mismos, y tener una copia por canal solo multiplicaria el sitio que
    ocupa y los sitios donde cambiarla el dia que se rehaga.
    """
    return settings.storage_path / "outros" / "template.mp4"


def outro_path_for(channel_id: uuid.UUID) -> Path:
    """Donde vive el cierre ya construido de un canal.

    Por id y no por nombre: renombrar el canal no puede dejar huerfano el
    fichero ni, peor, hacer que dos canales se pisen el suyo.
    """
    return settings.storage_path / "outros" / f"{channel_id}.mp4"


def build_outro(template: Path, destination: Path, text: OutroText) -> Path:
    """Escribe el cierre de un canal a partir de la plantilla.

    Una sola pasada de ffmpeg y una sola recodificacion: son menos de cuatro
    segundos de video, asi que no compensa complicarlo.
    """
    handle = text.handle.strip()
    if not handle:
        raise ClipForgeError("El cierre necesita un nombre de canal")
    if not template.is_file():
        raise ClipForgeError(f"No existe la plantilla de cierre: {template}")
    if not FONT_PATH.is_file():
        raise ClipForgeError(f"No se encuentra la fuente {FONT_PATH.name}")

    destination.parent.mkdir(parents=True, exist_ok=True)

    filters = [
        _cover(HANDLE_TOP, HANDLE_HEIGHT),
        _write(handle, top=HANDLE_TOP, size=HANDLE_SIZE, color="white"),
    ]
    if text.tagline is not None and text.tagline.strip():
        filters.append(_cover(TAGLINE_TOP, TAGLINE_HEIGHT))
        filters.append(
            _write(text.tagline.strip(), top=TAGLINE_TOP, size=TAGLINE_SIZE, color="red")
        )

    command = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(template),
        "-vf",
        ",".join(filters),
        "-c:v",
        # libx264 y no NVENC: son cuatro segundos, se hace una vez por canal y
        # asi el cierre sale igual en una maquina sin tarjeta.
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(destination),
    ]

    run_tool(command, tool_name="ffmpeg", timeout=BUILD_TIMEOUT_SECONDS)

    if not destination.is_file() or destination.stat().st_size == 0:
        raise ExternalToolError(f"ffmpeg no ha generado el cierre: {destination.name}")

    result = probe_video(destination)
    logger.info(
        "outro.built",
        outro=destination.name,
        handle=handle,
        duration=round(result.duration, 2),
    )
    return destination


def _cover(top: int, height: int) -> str:
    """Tapa una franja de la plantilla con negro."""
    return f"drawbox=x=0:y={top}:w=iw:h={height}:color=black:t=fill"


def _write(text: str, *, top: int, size: int, color: str) -> str:
    """Escribe una linea centrada en horizontal dentro de su franja."""
    return (
        f"drawtext=fontfile='{_font()}'"
        f":text='{escape_text(text)}'"
        f":fontcolor={color}:fontsize={size}"
        ":x=(w-text_w)/2"
        f":y={top}+({size}/6)"
    )


def _font() -> str:
    """La ruta de la fuente tal y como la entiende `drawtext`.

    En Windows la ruta lleva dos puntos tras la letra de unidad, y `drawtext`
    los usa para separar sus propios argumentos: sin escaparlos, el filtro
    entiende que `C` es un parametro y falla.
    """
    return str(FONT_PATH).replace("\\", "/").replace(":", r"\:")


def escape_text(value: str) -> str:
    """Deja un texto listo para meterlo dentro de `drawtext`."""
    return "".join(_ESCAPES.get(char, char) for char in value)
