"""Render del clip vertical con ffmpeg.

Un único paso: buscar, recortar, escalar, quemar subtítulos y codificar. Cortar
primero a un fichero intermedio y volver a codificarlo después costaría el doble
de tiempo y una generación más de pérdida de calidad.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.video.binaries import run_tool
from clipforge.services.video.crop import CropWindow, center_crop
from clipforge.services.video.encoder import EncoderProfile, resolve_encoder
from clipforge.services.video.probe import probe_video

logger = get_logger(__name__)

#: Un clip de 90 s no debería tardar más que esto ni en el peor de los casos.
RENDER_TIMEOUT_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class RenderResult:
    """Clip final, con lo que hace falta para guardarlo en base de datos."""

    path: Path
    width: int
    height: int
    duration: float
    filesize_bytes: int
    encoder: str
    has_burned_subtitles: bool


def render_vertical_clip(
    source: Path,
    destination: Path,
    *,
    start: float,
    end: float,
    subtitles: Path | None = None,
    crop: CropWindow | None = None,
    encoder: EncoderProfile | None = None,
) -> RenderResult:
    """Extrae `[start, end)` del original y lo deja en vertical 9:16.

    Args:
        subtitles: `.ass` a quemar. Si es None, el clip sale sin subtítulos.
        crop: ventana de recorte. Si es None, se centra (la FASE 6 pasará aquí
            la ventana calculada sobre la cara detectada).

    Raises:
        ExternalToolError: si el rango es inválido o ffmpeg falla.
    """
    duration = end - start
    if duration <= 0:
        raise ExternalToolError(
            f"Rango de clip inválido: {start:.2f}-{end:.2f}",
            details={"start": start, "end": end},
        )
    if not source.is_file():
        raise ExternalToolError(f"No existe el vídeo de origen: {source}")

    probed = probe_video(source)
    window = crop or center_crop(
        probed.width, probed.height, settings.output_width, settings.output_height
    )
    profile = encoder or resolve_encoder()
    destination.parent.mkdir(parents=True, exist_ok=True)

    filters = [
        window.to_filter(),
        f"scale={settings.output_width}:{settings.output_height}:flags=lanczos",
        # Sin esto algunos reproductores aplican una relación de aspecto heredada
        # del original y el clip sale deformado.
        "setsar=1",
    ]
    if subtitles is not None:
        # Filtro `ass` en lugar de `subtitles`: el .ass ya trae su estilo y su
        # resolución declarada, así que no hace falta force_style y el resultado
        # no depende del lienzo que libass suponga.
        filters.append(f"ass={_escape_filter_arg(subtitles.name)}")

    command = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        # -ss antes de -i busca por el índice del contenedor (rápido); como
        # después se recodifica, el corte sigue siendo exacto al fotograma.
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source),
        "-vf",
        ",".join(filters),
        *profile.args,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ac",
        "2",
        # faststart mueve el índice al principio: sin él el navegador tiene que
        # descargar el fichero entero antes de empezar a reproducir.
        "-movflags",
        "+faststart",
        str(destination),
    ]

    run_tool(
        command,
        tool_name="ffmpeg",
        timeout=RENDER_TIMEOUT_SECONDS,
        # El filtro `subtitles` trata `:` y `\` como sintaxis propia, así que una
        # ruta absoluta de Windows lo rompe. Se ejecuta desde la carpeta del .srt
        # y se le pasa solo el nombre.
        cwd=subtitles.parent if subtitles is not None else None,
    )

    if not destination.is_file() or destination.stat().st_size == 0:
        raise ExternalToolError(f"ffmpeg no ha generado el clip: {destination.name}")

    result = probe_video(destination)
    logger.info(
        "render.clip_finished",
        clip=destination.name,
        encoder=profile.name,
        resolution=f"{result.width}x{result.height}",
        duration=round(result.duration, 2),
        size_mb=round(destination.stat().st_size / 1_048_576, 1),
        subtitles=subtitles is not None,
    )

    return RenderResult(
        path=destination,
        width=result.width,
        height=result.height,
        duration=result.duration,
        filesize_bytes=destination.stat().st_size,
        encoder=profile.name,
        has_burned_subtitles=subtitles is not None,
    )


def _escape_filter_arg(value: str) -> str:
    """Escapa los caracteres que el parser de filtros de ffmpeg interpreta."""
    return value.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
