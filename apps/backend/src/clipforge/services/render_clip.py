"""Render de un candidato suelto, sin depender del pipeline completo.

Antes, renderizar solo ocurría dentro de `process_project`: para conseguir un
MP4 había que volver a pasar por descarga, transcripción y análisis. Eso hacía
imposible que el usuario recortara un clip a mano, y también reintentar un
único clip fallido sin rehacer el proyecto entero.

Aquí no se toca la base de datos, igual que en el resto de `services/`: la
capa que sabe de SQL es el worker. Esto recibe rutas y números y devuelve un
fichero.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.core.storage import ProjectStorage, StorageArea
from clipforge.services.edit import EditPlan, TrimRules, Word, plan_trim
from clipforge.services.subtitles import (
    HookStyle,
    SourceSegment,
    SubtitleCue,
    build_cues,
    write_ass,
    write_srt,
)
from clipforge.services.video.crop import CropWindow, center_crop_within
from clipforge.services.video.encoder import EncoderProfile, resolve_encoder
from clipforge.services.video.framing import CropPlan, FocusSource, build_track, plan_crop
from clipforge.services.video.letterbox import detect_content_window
from clipforge.services.video.probe import probe_video
from clipforge.services.video.render import render_vertical_clip

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ClipRenderPlan:
    """Lo mínimo que identifica un clip a generar."""

    candidate_id: uuid.UUID
    rank: int
    start: float
    end: float
    #: Frase que se escribe arriba en los primeros segundos. En un clip sin
    #: diálogo es lo único escrito que lleva.
    hook: str | None = None
    #: Encuadre corregido a mano, en píxeles del original. Con None manda el
    #: automático.
    crop_x: int | None = None

    @property
    def stem(self) -> str:
        """Nombre base del fichero. Lleva el rango para que dos versiones de un
        mismo candidato no se pisen: al mover la entrada o la salida en el
        editor, el clip anterior sigue reproduciéndose mientras se genera el nuevo.
        """
        return f"clip_{self.rank:02d}_{self.candidate_id.hex[:8]}"


@dataclass(frozen=True, slots=True)
class RenderSetup:
    """Lo que se calcula una vez por proyecto y se reutiliza en cada clip.

    La comprobación de NVENC cuesta cerca de un segundo y la detección de
    letterbox analiza fotogramas: hacerlo por clip multiplicaría el tiempo de
    render sin cambiar el resultado.

    El **encuadre no está aquí a propósito**: depende de dónde esté el sujeto, y
    eso cambia de un clip a otro. Lo que se comparte es `content`, la zona del
    fotograma que tiene imagen de verdad, sin las barras negras incrustadas.
    """

    source: Path
    storage: ProjectStorage
    segments: list[SourceSegment]
    #: Tiempos por palabra de toda la transcripción. Es lo que permite
    #: saber dónde hay silencio sin volver a analizar el audio: Whisper ya
    #: los midió y hasta ahora no los usaba nadie.
    words: list[Word]
    encoder: EncoderProfile
    #: Región con imagen real del original, ya sin letterbox.
    content: CropWindow
    #: Dimensiones del original, para traducir coordenadas del análisis.
    source_width: int
    source_height: int
    burn_subtitles: bool
    #: Si en este perfil de contenido tiene sentido quitar los silencios.
    trim_silences: bool = True


@dataclass(frozen=True, slots=True)
class RenderedClip:
    """Resultado del render, listo para que el worker lo guarde."""

    path: Path
    subtitle_path: Path | None
    duration: float
    width: int
    height: int
    filesize_bytes: int
    has_burned_subtitles: bool
    encoder: str
    cues: int
    has_hook: bool
    crop_x: int
    crop_width: int


def build_setup(
    project_id: uuid.UUID,
    source: Path,
    segments: list[SourceSegment],
    *,
    burn_subtitles: bool,
    sample_at: float = 0.0,
    words: list[Word] | None = None,
    trim_silences: bool = True,
) -> RenderSetup:
    """Prepara encoder y encuadre para todos los clips de un proyecto.

    Raises:
        ExternalToolError: si el vídeo de origen no existe o ffprobe falla.
    """
    if not source.is_file():
        raise ExternalToolError(f"No existe el vídeo de origen: {source}")

    encoder = resolve_encoder()
    probed = probe_video(source)
    content = detect_content_window(source, probed.width, probed.height, start=sample_at)

    logger.info(
        "render.setup_ready",
        encoder=encoder.name,
        source=f"{probed.width}x{probed.height}",
        content=content.to_filter(),
        smart_crop=settings.smart_crop,
        burn_subtitles=burn_subtitles,
        trim_silences=trim_silences and settings.smart_trimming,
    )
    return RenderSetup(
        source=source,
        storage=ProjectStorage(project_id),
        segments=segments,
        words=words or [],
        encoder=encoder,
        content=content,
        source_width=probed.width,
        source_height=probed.height,
        burn_subtitles=burn_subtitles,
        trim_silences=trim_silences,
    )


def plan_framing(plan: ClipRenderPlan, setup: RenderSetup) -> CropPlan:
    """Decide dónde cae la ventana vertical de ESTE clip.

    Con `SMART_CROP` desactivado se centra, que es lo que se hacía antes de la
    FASE 13. Con él activado se sigue al sujeto: primero por sus caras y, si no
    hay ninguna reconocible, por dónde está el movimiento.
    """
    centered = center_crop_within(setup.content, settings.output_width, settings.output_height)

    # La corrección del usuario gana siempre. Si ha movido el encuadre a mano es
    # porque el automático se equivocó, y volver a calcularlo en cada render le
    # desharía el trabajo delante de las narices.
    if plan.crop_x is not None:
        lowest = setup.content.x
        highest = setup.content.x + setup.content.width - centered.width
        fixed = max(lowest, min(highest, plan.crop_x))
        fixed -= fixed % 2
        logger.info("render.manual_framing", x=fixed, requested=plan.crop_x)
        return CropPlan(
            window=CropWindow(x=fixed, y=centered.y, width=centered.width, height=centered.height),
            source=FocusSource.MANUAL,
        )

    if not settings.smart_crop:
        return CropPlan(window=centered)

    track = build_track(
        setup.source,
        start=plan.start,
        end=plan.end,
        source_width=setup.source_width,
        source_height=setup.source_height,
        window_width=centered.width,
    )
    return plan_crop(
        track,
        setup.content,
        target_width=settings.output_width,
        target_height=settings.output_height,
    )


def plan_edit(plan: ClipRenderPlan, setup: RenderSetup) -> EditPlan:
    """Decide qué tramos del original se quedan en el clip.

    Con `SMART_TRIMMING` apagado, o sin palabras que mirar, devuelve el
    plan de siempre: un rango continuo. Es el mismo camino que el código
    llevaba recorriendo desde la fase 5, así que apagar el interruptor
    devuelve el comportamiento anterior exacto.
    """
    if not settings.smart_trimming or not setup.trim_silences or not setup.words:
        return EditPlan.single(plan.start, plan.end)

    return plan_trim(
        setup.words,
        start=plan.start,
        end=plan.end,
        rules=TrimRules(
            min_gap=settings.trim_min_gap_seconds,
            padding=settings.trim_padding_seconds,
            min_beat=settings.trim_min_beat_seconds,
            max_removed_ratio=settings.trim_max_removed_ratio,
        ),
    )


def build_plan_cues(edit: EditPlan, setup: RenderSetup) -> list[SubtitleCue]:
    """Subtítulos del clip, ya en tiempos del MONTAJE y no del original.

    Se construyen tramo a tramo y se desplazan: cada uno empieza donde
    acaba el anterior en el clip final. Sin esto, quitar cuatro segundos
    de silencio dejaría todos los subtítulos posteriores cuatro segundos
    por detrás de lo que se oye — que es peor que no ponerlos.
    """
    cues: list[SubtitleCue] = []
    elapsed = 0.0

    for beat, _ in edit.offsets():
        for cue in build_cues(setup.segments, beat.start, beat.end):
            cues.append(
                replace(
                    cue,
                    start=round(cue.start + elapsed, 3),
                    end=round(cue.end + elapsed, 3),
                )
            )
        elapsed += beat.duration

    return cues


def render_clip(plan: ClipRenderPlan, setup: RenderSetup) -> RenderedClip:
    """Genera el .srt y el .mp4 de un candidato.

    Raises:
        ExternalToolError: si el rango es inválido o ffmpeg falla.
    """
    framing = plan_framing(plan, setup)
    edit = plan_edit(plan, setup)
    cues = build_plan_cues(edit, setup)

    # Dos ficheros con el mismo contenido y distinto propósito: el .srt es el
    # que se entrega para publicar el clip, el .ass es el que se incrusta.
    subtitle_path = (
        write_srt(cues, setup.storage.path_for(StorageArea.SUBTITLES, f"{plan.stem}.srt"))
        if cues
        else None
    )

    # El gancho es independiente de los subtítulos: un clip visual no lleva
    # subtítulos —no hay nada que subtitular— y es justo el que más necesita
    # una frase escrita, porque si no se publica mudo y sin contexto.
    burned_cues = cues if setup.burn_subtitles else []
    hook = plan.hook.strip() if settings.hook_overlay and plan.hook else None
    burn_path = (
        write_ass(
            burned_cues,
            setup.storage.path_for(StorageArea.TEMP, f"{plan.stem}.ass"),
            settings.output_width,
            settings.output_height,
            hook=hook,
            hook_seconds=settings.hook_overlay_seconds,
            hook_style=HookStyle(
                size=settings.hook_font_size, line_length=settings.hook_line_length
            ),
        )
        if burned_cues or hook
        else None
    )

    result = render_vertical_clip(
        setup.source,
        setup.storage.path_for(StorageArea.CLIPS, f"{plan.stem}.mp4"),
        start=edit.source_start,
        end=edit.source_end,
        beats=[(beat.start, beat.end) for beat in edit.beats],
        # Sin subtítulos quemados el .srt sigue quedando en disco, para poder
        # publicar el clip limpio y subirlos aparte.
        subtitles=burn_path,
        crop=framing,
        encoder=setup.encoder,
    )
    setup.storage.assert_within_root(result.path)

    return RenderedClip(
        path=result.path,
        subtitle_path=subtitle_path,
        duration=result.duration,
        width=result.width,
        height=result.height,
        filesize_bytes=result.filesize_bytes,
        # El render solo sabe que ha quemado un .ass; qué llevaba dentro lo
        # sabemos aquí, y es lo que interesa registrar.
        has_burned_subtitles=bool(burned_cues) and result.has_burned_subtitles,
        encoder=result.encoder,
        cues=len(cues),
        has_hook=hook is not None,
        crop_x=framing.window.x,
        crop_width=framing.window.width,
    )
