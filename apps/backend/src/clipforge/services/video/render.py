"""Render del clip vertical con ffmpeg.

Un único paso: buscar, recortar, escalar, quemar subtítulos y codificar. Cortar
primero a un fichero intermedio y volver a codificarlo después costaría el doble
de tiempo y una generación más de pérdida de calidad.
"""

from __future__ import annotations

from collections.abc import Sequence
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
    beats: Sequence[tuple[float, float]] | None = None,
    zoom: str | None = None,
    subtitles: Path | None = None,
    crop: CropFilter | None = None,
    encoder: EncoderProfile | None = None,
    outro: Path | None = None,
) -> RenderResult:
    """Extrae `[start, end)` del original y lo deja en vertical 9:16.

    Args:
        beats: tramos `(inicio, fin)` del original que se conservan, en
            tiempos absolutos. Con None —o con uno solo— el clip es el
            rango continuo de siempre y se usa el camino de siempre.
        zoom: filtro `zoompan` ya montado, o None para no acercar nada.
        subtitles: `.ass` a quemar. Si es None, el clip sale sin subtítulos.
        crop: ventana o plan de recorte. Si es None, se centra.
        outro: cierre del canal a pegar al final, o None. Va dentro de la
            misma pasada de ffmpeg: pegarlo después obligaría a recodificar
            el clip entero por segunda vez y a perder calidad por el camino.

    Raises:
        ExternalToolError: si el rango es inválido o ffmpeg falla.
    """
    cuts = [beat for beat in (beats or []) if beat[1] > beat[0]]
    duration = sum(b - a for a, b in cuts) if len(cuts) > 1 else end - start
    if duration <= 0:
        raise ExternalToolError(
            f"Rango de clip inválido: {start:.2f}-{end:.2f}",
            details={"start": start, "end": end},
        )
    if not source.is_file():
        raise ExternalToolError(f"No existe el vídeo de origen: {source}")
    # Un cierre que falta no puede tirar el render: el clip sin cierre sirve,
    # y perderlo entero por los últimos cuatro segundos sería desproporcionado.
    if outro is not None and not outro.is_file():
        logger.warning("render.outro_missing", outro=str(outro))
        outro = None

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
    # El acercamiento va ANTES de los subtítulos, y el orden no es un
    # detalle: al revés escalaría también el texto, que se vería crecer y
    # encoger con cada énfasis. El texto tiene que quedarse quieto.
    if zoom is not None:
        filters.append(zoom)
    if subtitles is not None:
        # Filtro `ass` en lugar de `subtitles`: el .ass ya trae su estilo y su
        # resolución declarada, así que no hace falta force_style y el resultado
        # no depende del lienzo que libass suponga.
        filters.append(f"ass={_escape_filter_arg(subtitles.name)}")

    audio_filters = build_audio_filters(duration)

    # Con más de un tramo hay que montar, y montar no cabe en `-vf`: hace
    # falta un filtergraph que recorte cada trozo y los concatene. Sigue
    # siendo UNA pasada de ffmpeg; lo que cambia es la forma del grafo.
    graph = _concat_graph(cuts, start, filters, audio_filters) if len(cuts) > 1 else None
    # Con cierre siempre hace falta grafo, aunque el clip sea de un solo tramo:
    # pegar un segundo vídeo no cabe en `-vf`, que solo ve una entrada.
    if outro is not None:
        graph = _outro_graph(graph, filters, audio_filters, fps=probed.fps)
    # -t abarca hasta el final del último tramo: dentro del grafo se tira lo
    # que sobra, pero ffmpeg tiene que haber decodificado hasta ahí.
    decode_span = (cuts[-1][1] - start) if len(cuts) > 1 else duration

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
        f"{decode_span:.3f}",
        "-i",
        str(source),
        # El cierre entra como segunda entrada. Va DESPUÉS del -t de la
        # primera: esos flags son posicionales y afectan a la entrada que
        # tienen detrás, así que colarlo antes recortaría el original.
        *(["-i", str(outro)] if outro is not None else []),
        *(
            [
                "-filter_complex",
                graph,
                "-map",
                "[vout]" if outro is not None else "[v]",
                "-map",
                "[aout]" if outro is not None else "[a]",
            ]
            if graph is not None
            else [
                "-vf",
                ",".join(filters),
                *(["-af", ",".join(audio_filters)] if audio_filters else []),
            ]
        ),
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
        beats=max(1, len(cuts)),
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


def _outro_graph(
    graph: str | None,
    video_filters: Sequence[str],
    audio_filters: Sequence[str],
    *,
    fps: float,
) -> str:
    """Añade el cierre del canal al final del clip, en la misma pasada.

    El `concat` de ffmpeg exige que los dos trozos coincidan en tamaño, en
    relación de aspecto, en formato de píxel y en frecuencia de muestreo. El
    cierre viene de una plantilla suya —otro tamaño de audio, otros fps— así
    que se le fuerza a la forma del clip antes de pegarlo. Sin eso, `concat`
    falla o, peor, cuela un cierre con el sonido a destiempo.

    Los fps se igualan a los del original y no a un número fijo para no
    cambiar de paso el ritmo de los clips que no llevan cierre.
    """
    parts = [graph] if graph is not None else []
    if graph is None:
        # Sin montaje previo, el clip principal todavía es la entrada cruda.
        parts.append(f"[0:v]{','.join(video_filters)}[v]")
        parts.append(f"[0:a]{','.join(audio_filters)}[a]" if audio_filters else "[0:a]anull[a]")

    shared_audio = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    parts.append(
        f"[1:v]scale={settings.output_width}:{settings.output_height}:flags=lanczos,"
        f"setsar=1,fps={fps:.5f},format=yuv420p[ov]"
    )
    parts.append(f"[1:a]{shared_audio}[oa]")
    # También al clip: el original puede venir a 96 kHz y el cierre a 44,1, y
    # `concat` no remuestrea por su cuenta.
    parts.append("[v]format=yuv420p[mv]")
    parts.append(f"[a]{shared_audio}[ma]")
    parts.append("[mv][ma][ov][oa]concat=n=2:v=1:a=1[vout][aout]")

    return ";".join(parts)


def _concat_graph(
    cuts: Sequence[tuple[float, float]],
    seek: float,
    video_filters: Sequence[str],
    audio_filters: Sequence[str],
) -> str:
    """Filtergraph que recorta cada tramo, los concatena y monta el clip.

    Los tiempos van **relativos al punto de búsqueda**: con `-ss` antes de
    `-i`, ffmpeg reescribe las marcas de tiempo para que empiecen en cero, así
    que usar los absolutos del original cortaría en el sitio equivocado.

    El recorte, el escalado y los subtítulos se aplican DESPUÉS de concatenar
    y no tramo a tramo: son los mismos para todo el clip, y hacerlo antes
    multiplicaría el trabajo por el número de tramos sin cambiar el resultado.
    """
    parts: list[str] = []
    labels: list[str] = []

    for index, (cut_start, cut_end) in enumerate(cuts):
        begin = max(0.0, cut_start - seek)
        finish = max(begin, cut_end - seek)
        # setpts/asetpts a cero: cada trozo tiene que empezar en su propio
        # origen o `concat` los apila conservando los huecos que acabamos de
        # quitar, que es justo lo contrario de lo que se busca.
        parts.append(f"[0:v]trim=start={begin:.3f}:end={finish:.3f},setpts=PTS-STARTPTS[v{index}]")
        parts.append(
            f"[0:a]atrim=start={begin:.3f}:end={finish:.3f},asetpts=PTS-STARTPTS[a{index}]"
        )
        labels.append(f"[v{index}][a{index}]")

    parts.append(f"{''.join(labels)}concat=n={len(cuts)}:v=1:a=1[vcat][acat]")
    parts.append(f"[vcat]{','.join(video_filters)}[v]")
    parts.append(f"[acat]{','.join(audio_filters)}[a]" if audio_filters else "[acat]anull[a]")

    return ";".join(parts)


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
