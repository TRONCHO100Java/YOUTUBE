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
from clipforge.services.video.crop import CropFilter, center_crop
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
    crop: CropFilter | None = None,
    encoder: EncoderProfile | None = None,
) -> RenderResult:
    """Extrae `[start, end)` del original y lo deja en vertical 9:16.

    Args:
        subtitles: `.ass` a quemar. Si es None, el clip sale sin subtítulos.
        crop: ventana o plan de recorte. Si es None, se centra.

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

    audio_filters = build_audio_filters(duration)

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
        *(["-af", ",".join(audio_filters)] if audio_filters else []),
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
        audio=",".join(audio_filters) or "sin tratar",
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


def build_audio_filters(duration: float) -> list[str]:
    """Cadena de filtros de audio del clip.

    Dos tratamientos que no se ven pero se notan en cuanto se publica:

    **Volumen.** Un clip sacado de un pódcast bien masterizado y otro de un
    vídeo grabado con el móvil se llevan quince decibelios. Las plataformas
    normalizan al reproducir, pero lo hacen bajando el que se pasa, así que un
    clip flojo se queda flojo. `loudnorm` lo deja en el objetivo estándar de
    audio social (-14 LUFS) con un techo de pico que evita el recorte.

    **Entrada y salida.** Cortar en seco a mitad de una forma de onda produce un
    chasquido audible. Ochenta milisegundos de entrada lo eliminan sin que se
    perciba como un fundido; la salida es más larga porque un corte brusco al
    final se oye como un fallo de reproducción.

    El vídeo NO se funde a negro: los primeros fotogramas son justo donde se
    decide si alguien sigue mirando, y empezar en negro los regala.
    """
    filters: list[str] = []

    if settings.audio_normalize:
        filters.append(
            f"loudnorm=I={settings.audio_target_lufs}:TP={settings.audio_true_peak}:LRA=11"
        )

    fade_in = settings.audio_fade_in_seconds
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")

    fade_out = min(settings.audio_fade_out_seconds, duration / 4)
    if fade_out > 0:
        filters.append(f"afade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f}")

    return filters


def _escape_filter_arg(value: str) -> str:
    """Escapa los caracteres que el parser de filtros de ffmpeg interpreta."""
    return value.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
