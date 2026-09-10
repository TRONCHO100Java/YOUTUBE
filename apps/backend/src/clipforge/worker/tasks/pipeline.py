"""Pipeline de procesamiento de un proyecto.

La tarea es autocontenida: recibe solo el id del proyecto y obtiene todo lo
demás de PostgreSQL. Así puede ejecutarse en cualquier worker (esta máquina,
otra GPU o RunPod) sin estado compartido más allá de la base de datos.

Cada etapa deja el estado del proyecto actualizado en una transacción corta,
de modo que el frontend puede seguir el progreso por polling. El trabajo pesado
(descarga, ffmpeg, Whisper) ocurre SIEMPRE fuera de transacción: puede durar
minutos y no debe mantener ocupada una conexión de PostgreSQL.

Principio que gobierna las etapas de análisis: **el proyecto nunca termina en
FAILED por no haber encontrado nada.** Si la IA no propone clips, se guardan
los bloques que salen de las señales y el proyecto queda en `NEEDS_REVIEW`,
con el vídeo en disco y la línea de tiempo lista para que el usuario recorte a
mano. Tirar una descarga de cientos de megas porque un modelo no supo qué decir
era la peor forma posible de gestionar la duda.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from clipforge.core.config import settings
from clipforge.core.errors import ClipForgeError, ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.core.storage import (
    ProjectStorage,
    StorageArea,
    absolute_from_storage,
    relative_to_storage,
)
from clipforge.db.models import (
    CandidateSource,
    CandidateStatus,
    ClipCandidate,
    ContentProfile,
    GeneratedClip,
    Project,
    ProjectStatus,
    Transcript,
    TranscriptSegment,
)
from clipforge.db.session import sync_session_scope
from clipforge.services.ai import (
    AnalysisContext,
    ClipSuggestion,
    detect_profile,
    get_analyzer,
    get_block_analyzer,
    parse_keywords,
    rules_for,
    select_clips,
    select_clips_from_blocks,
    suggestions_from_signals,
    write_titles,
)
from clipforge.services.ai.chunking import to_analysis_segments
from clipforge.services.download.base import VideoDownloader
from clipforge.services.download.ytdlp import YtDlpDownloader
from clipforge.services.export import ClipExport, SourceCredit, export_project
from clipforge.services.render_clip import ClipRenderPlan, RenderSetup, build_setup, render_clip
from clipforge.services.signals import SignalTimeline, build_timeline
from clipforge.services.source.urls import validate_source_url
from clipforge.services.subtitles import SourceSegment
from clipforge.services.transcribe.base import Transcriber, TranscriptionResult
from clipforge.services.transcribe.whisper import FasterWhisperTranscriber
from clipforge.services.video.audio import extract_audio
from clipforge.services.video.probe import probe_video
from clipforge.worker.celery_app import celery_app

logger = get_logger(__name__)

AUDIO_FILENAME = "audio.wav"


@celery_app.task(name="clipforge.pipeline.process_project", bind=True)
def process_project(self: Any, project_id: str) -> dict[str, Any]:
    """Procesa un proyecto de principio a fin.

    FASE 2: descarga y metadatos. FASE 3: audio y transcripción.
    FASE 7: señales no verbales. FASE 4/8/9: detección de momentos según el
    perfil de contenido. FASE 5: recorte y render 9:16.
    """
    pid = uuid.UUID(project_id)
    log = logger.bind(project_id=project_id, task_id=self.request.id)

    if _is_stale(pid, self.request.id, log):
        return {"project_id": project_id, "status": "SKIPPED", "reason": "stale"}

    try:
        _download_stage(pid, log)
        _transcribe_stage(pid, log)
        _signals_stage(pid, log)
        renderable = _analyze_stage(pid, log)
        if renderable:
            _render_stage(pid, log)
    except ClipForgeError as exc:
        # Error esperado (fuente no disponible, ffmpeg, Whisper sin GPU):
        # el mensaje es apto para enseñárselo al usuario.
        log.warning("pipeline.failed", code=exc.code, error=exc.message)
        _update(pid, status=ProjectStatus.FAILED, error_message=exc.message)
        return {"project_id": project_id, "status": ProjectStatus.FAILED, "error": exc.message}
    except Exception as exc:
        log.error("pipeline.crashed", exc_info=exc)
        _update(pid, status=ProjectStatus.FAILED, error_message=f"Error inesperado: {exc}")
        raise

    status = ProjectStatus.COMPLETED if renderable else ProjectStatus.NEEDS_REVIEW
    _update(pid, status=status)
    # Sin clips no hay proyecto terminado, sino uno a medias que el usuario va a
    # abrir en el editor: el vídeo original tiene que seguir ahí pase lo que
    # pase con KEEP_SOURCE_VIDEO.
    _cleanup(pid, log, keep_source=None if renderable else True)
    log.info("pipeline.completed", status=status.value)
    return {"project_id": project_id, "status": status}


def _task_is_stale(owner_task_id: str | None, task_id: str | None) -> bool:
    """¿A esta tarea la ha sustituido otra sobre el mismo proyecto?

    Reencolar un proyecto cuya tarea seguía en la cola deja dos mensajes para
    el mismo vídeo, y el worker haría el trabajo entero dos veces seguidas.
    `revoke` no lo resuelve: con `--pool=solo` el worker no lee los mensajes
    de control mientras está trabajando, así que la cancelación puede llegar
    después de que haya sacado la tarea.

    La base de datos sí es fiable. El proyecto guarda el id de SU tarea, la
    última que se encoló; cualquier otra que despierte con un id distinto
    llega tarde y no debe rehacer nada.
    """
    # Sin id de tarea es una llamada directa (tests, consola): no hay dueño
    # con quien comparar y el trabajo es justo el que se ha pedido.
    if task_id is None or owner_task_id is None:
        return False
    return owner_task_id != str(task_id)


def _is_stale(project_id: uuid.UUID, task_id: str | None, log: Any) -> bool:
    """Comprueba contra la base de datos si esta tarea sigue siendo la vigente."""
    with sync_session_scope() as session:
        project = session.get(Project, project_id)
        owner = project.task_id if project is not None else None

    if not _task_is_stale(owner, task_id):
        return False

    log.info("pipeline.stale_task", owner_task_id=owner)
    return True


# --------------------------------------------------------------------- descarga
def _download_stage(
    project_id: uuid.UUID, log: Any, downloader: VideoDownloader | None = None
) -> None:
    """Descarga el vídeo de origen y guarda sus metadatos reales."""
    with sync_session_scope() as session:
        project = _require(session, project_id)
        if not project.source_url:
            raise ClipForgeError("El proyecto no tiene URL de origen")
        source_url = project.source_url
        existing = project.source_video_path
        project.status = ProjectStatus.DOWNLOADING
        project.error_message = None

    # En un reintento el vídeo suele seguir en disco: volver a bajar cientos de
    # megas para repetir solo la transcripción no tiene sentido.
    if existing and absolute_from_storage(existing).is_file():
        log.info("pipeline.download_skipped", reason="el video ya esta descargado")
        return

    ref = validate_source_url(source_url)
    storage = ProjectStorage(project_id)
    storage.ensure_layout()

    log.info("pipeline.download_started", video_id=ref.video_id)
    result = (downloader or YtDlpDownloader()).download(ref, storage.area(StorageArea.SOURCE))
    storage.assert_within_root(result.video_path)

    probed = probe_video(result.video_path)
    log.info(
        "pipeline.download_finished",
        duration=round(probed.duration, 1),
        resolution=f"{probed.width}x{probed.height}",
        has_audio=probed.has_audio,
    )
    if not probed.has_audio:
        raise ClipForgeError("El vídeo no tiene pista de audio, no se puede procesar")

    _update(
        project_id,
        title=result.metadata.title,
        author=result.metadata.author,
        thumbnail_url=result.metadata.thumbnail_url,
        # La duración fiable es la del fichero, no la anunciada por la fuente.
        duration=probed.duration,
        source_video_path=relative_to_storage(result.video_path),
    )


# ---------------------------------------------------------------- transcripción
def _transcribe_stage(
    project_id: uuid.UUID, log: Any, transcriber: Transcriber | None = None
) -> None:
    """Extrae el audio, lo transcribe y decide el perfil de contenido.

    Una transcripción vacía o casi vacía ya **no** es un error. Un vídeo puede
    no tener una sola palabra utilizable y seguir siendo perfectamente
    recortable: simplemente hay que juzgarlo por otra cosa.
    """
    with sync_session_scope() as session:
        project = _require(session, project_id)
        if not project.source_video_path:
            raise ClipForgeError("El proyecto no tiene vídeo descargado")
        video_relative = project.source_video_path
        video_duration = project.duration or 0.0
        project.status = ProjectStatus.TRANSCRIBING

    storage = ProjectStorage(project_id)
    video_path = absolute_from_storage(video_relative)
    audio_path = storage.path_for(StorageArea.AUDIO, AUDIO_FILENAME)

    log.info("pipeline.audio_extraction_started")
    extract_audio(video_path, audio_path)

    log.info("pipeline.transcription_started")
    result = (transcriber or FasterWhisperTranscriber()).transcribe(audio_path)

    speech_seconds = sum(segment.end - segment.start for segment in result.segments)
    ratio = speech_seconds / video_duration if video_duration > 0 else 0.0
    profile = detect_profile(
        speech_seconds=speech_seconds,
        text_characters=len(result.full_text),
        video_duration=video_duration,
    )

    # Por debajo del umbral de utilidad, lo que hay no es habla: es Whisper
    # alucinando sobre música. Pasárselo al analizador solo sirve para que
    # juzgue basura, así que los segmentos se descartan y se conserva la fila
    # de transcripción como registro de que se intentó.
    usable = ratio >= settings.min_usable_speech_ratio
    if not usable and result.segments:
        log.warning(
            "pipeline.transcript_discarded",
            reason="proporcion de habla por debajo del minimo utilizable",
            speech_ratio=round(ratio, 4),
            minimum=settings.min_usable_speech_ratio,
            sample=result.full_text[:60],
        )

    _save_transcript(
        project_id,
        result,
        relative_to_storage(audio_path),
        profile=profile,
        speech_ratio=ratio,
        keep_segments=usable,
    )
    log.info(
        "pipeline.transcription_finished",
        language=result.language,
        segments=len(result.segments) if usable else 0,
        characters=len(result.full_text),
        speech_ratio=round(ratio, 4),
        profile=profile.value,
    )


def _save_transcript(
    project_id: uuid.UUID,
    result: TranscriptionResult,
    audio_relative: str,
    *,
    profile: ContentProfile,
    speech_ratio: float,
    keep_segments: bool,
) -> None:
    """Reemplaza la transcripción del proyecto por la recién generada."""
    with sync_session_scope() as session:
        project = _require(session, project_id)
        # Un reintento debe dejar una sola transcripción: se borra la anterior
        # y la cascada se lleva sus segmentos.
        session.execute(delete(Transcript).where(Transcript.project_id == project_id))
        session.flush()

        transcript = Transcript(
            project_id=project_id,
            language=result.language,
            language_probability=result.language_probability,
            full_text=result.full_text if keep_segments else "",
            model_name=result.model_name,
            duration=result.duration,
        )
        session.add(transcript)
        session.flush()  # necesitamos el id para los segmentos

        if keep_segments:
            session.add_all(
                TranscriptSegment(
                    transcript_id=transcript.id,
                    index=segment.index,
                    start_time=segment.start,
                    end_time=segment.end,
                    text=segment.text,
                    words=[word.to_dict() for word in segment.words] or None,
                )
                for segment in result.segments
            )

        project.audio_path = audio_relative
        project.content_profile = profile
        project.speech_ratio = speech_ratio


# -------------------------------------------------------------------- señales
def _signals_stage(project_id: uuid.UUID, log: Any) -> None:
    """Mide energía, cortes de plano y movimiento, y los guarda.

    Se ejecuta en todos los proyectos, no solo en los visuales: la línea de
    tiempo que produce es también lo que hace utilizable el editor manual, y
    sobre un vídeo de nueve minutos cuesta diecisiete segundos.

    Nunca tumba el pipeline. Sin señales el análisis de texto sigue funcionando
    igual que antes de que existiera esta etapa.
    """
    if not settings.signals_enabled:
        return

    with sync_session_scope() as session:
        project = _require(session, project_id)
        if not project.source_video_path:
            return
        video_relative = project.source_video_path
        audio_relative = project.audio_path
        duration = project.duration or 0.0
        profile = project.content_profile or ContentProfile.TALKING
        rules = rules_for(profile)
        existing = project.signals

    if duration <= 0:
        return

    # Un reproceso no cambia el vídeo, así que tampoco cambian sus señales:
    # medirlas otra vez son 35 segundos tirados. Solo se rehacen si el perfil
    # cambió —los bloques dependen de sus duraciones— o si no las había.
    if existing is not None and _signals_are_current(existing, duration, rules):
        log.info("pipeline.signals_reused", blocks=len(existing.get("blocks", [])))
        return

    log.info("pipeline.signals_started")
    try:
        timeline = build_timeline(
            absolute_from_storage(video_relative),
            absolute_from_storage(audio_relative) if audio_relative else None,
            duration=duration,
            min_block_seconds=rules.min_duration,
            max_block_seconds=rules.max_duration,
            target_block_seconds=rules.target_duration,
        )
    except ClipForgeError as exc:
        log.warning("pipeline.signals_failed", error=exc.message)
        return

    payload = timeline.to_dict()
    # El perfil se guarda con las señales para saber con qué duraciones se
    # construyeron los bloques.
    payload["profile"] = profile.value
    _update(project_id, signals=payload)
    log.info("pipeline.signals_finished", blocks=len(timeline.blocks), peaks=len(timeline.peaks))


def _signals_are_current(signals: dict[str, Any] | None, duration: float, rules: Any) -> bool:
    """Decide si las señales guardadas siguen sirviendo.

    Se comprueban las dos cosas de las que dependen: la duración del vídeo (si
    cambia es que el fichero es otro) y el perfil (decide el tamaño de los
    bloques). Todo lo demás es determinista sobre el mismo fichero.
    """
    if not signals or not signals.get("blocks"):
        return False
    if signals.get("profile") != rules.profile.value:
        return False
    return abs(float(signals.get("duration", 0.0)) - duration) < 1.0


# ------------------------------------------------------------------- análisis IA
def _analyze_stage(project_id: uuid.UUID, log: Any) -> bool:
    """Detecta los mejores momentos y los guarda como candidatos puntuados.

    Devuelve `True` si hay candidatos que renderizar. Cuando devuelve `False`
    el proyecto acaba en `NEEDS_REVIEW`: no es un fallo, es que hace falta que
    alguien mire.
    """
    with sync_session_scope() as session:
        project = _require(session, project_id)
        transcript = session.execute(
            select(Transcript).where(Transcript.project_id == project_id)
        ).scalar_one_or_none()

        rows = (
            list(
                session.execute(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.transcript_id == transcript.id)
                    .order_by(TranscriptSegment.index)
                ).scalars()
            )
            if transcript is not None
            else []
        )
        segments = to_analysis_segments(rows)
        profile = project.content_profile or ContentProfile.TALKING
        context = AnalysisContext(
            title=project.title,
            author=project.author,
            language=transcript.language if transcript else None,
            profile=profile,
            duration=project.duration,
            keywords=parse_keywords(project.keywords),
        )
        timeline = SignalTimeline.from_dict(project.signals) if project.signals else None
        video_relative = project.source_video_path
        project.status = ProjectStatus.ANALYZING

    blocks = timeline.blocks if timeline else []
    log.info(
        "pipeline.analysis_started",
        profile=profile.value,
        segments=len(segments),
        blocks=len(blocks),
    )

    suggestions = _run_analysis(
        profile=profile,
        segments=segments,
        blocks=blocks,
        context=context,
        video_relative=video_relative,
        project_id=project_id,
        log=log,
    )

    if suggestions:
        # El titulado va aquí y no antes: solo tiene sentido sobre los clips
        # que han sobrevivido al ranking, que son los que se van a publicar.
        # Y va antes de guardar para que el título bueno sea el primero que
        # ve el usuario, sin un parpadeo con el título viejo por medio.
        suggestions = write_titles(suggestions, context)
        _save_candidates(project_id, suggestions, status=CandidateStatus.SELECTED)
        log.info(
            "pipeline.analysis_finished",
            candidates=len(suggestions),
            best_score=suggestions[0].score,
        )
        return True

    # Nada que renderizar. En lugar de fallar, se dejan los mejores bloques como
    # propuestas sin juzgar para que el editor manual tenga por dónde empezar.
    fallback = suggestions_from_signals(blocks)
    if fallback:
        _save_candidates(project_id, fallback, status=CandidateStatus.PENDING)
    log.info("pipeline.analysis_needs_review", proposals=len(fallback))
    _update(
        project_id,
        error_message=(
            "La IA no ha encontrado ningún momento claro. Se han marcado "
            f"{len(fallback)} tramos con más ritmo para que los revises y "
            "recortes a mano."
            if fallback
            else "La IA no ha encontrado ningún momento claro. Puedes recortar "
            "los clips a mano en el editor."
        ),
    )
    return False


def _run_analysis(
    *,
    profile: ContentProfile,
    segments: list[Any],
    blocks: list[Any],
    context: AnalysisContext,
    video_relative: str | None,
    project_id: uuid.UUID,
    log: Any,
) -> list[ClipSuggestion]:
    """Elige la estrategia según el perfil y la ejecuta, tolerando su fallo.

    Un error del proveedor de IA aquí no debe tumbar el proyecto: se registra y
    se devuelve la lista vacía, que el llamante convierte en `NEEDS_REVIEW`.
    """
    try:
        if profile is ContentProfile.VISUAL:
            if not settings.ai_vision_enabled:
                log.info("pipeline.vision_disabled")
                return []
            if not blocks or not video_relative:
                log.warning("pipeline.vision_skipped", reason="sin bloques o sin video")
                return []

            with tempfile.TemporaryDirectory(prefix="clipforge-vision-") as tmp:
                return select_clips_from_blocks(
                    blocks,
                    context,
                    get_block_analyzer(),
                    video_path=absolute_from_storage(video_relative),
                    workdir=Path(tmp),
                )

        if not segments:
            log.warning("pipeline.text_analysis_skipped", reason="transcripcion sin segmentos")
            return []
        return select_clips(segments, context, get_analyzer())

    except ExternalToolError as exc:
        log.warning("pipeline.analysis_provider_failed", error=exc.message)
        return []


def _save_candidates(
    project_id: uuid.UUID, suggestions: list[ClipSuggestion], *, status: CandidateStatus
) -> None:
    """Reemplaza los candidatos generados por los recién seleccionados.

    Solo borra lo que produjo la máquina. Los candidatos manuales sobreviven a
    un reprocesado: son trabajo del usuario y perderlos porque ha pulsado
    "regenerar" sería imperdonable.
    """
    with sync_session_scope() as session:
        _require(session, project_id)
        session.execute(
            delete(ClipCandidate)
            .where(ClipCandidate.project_id == project_id)
            .where(ClipCandidate.source != CandidateSource.MANUAL)
        )
        session.flush()

        # Los manuales que ya existían conservan su sitio en la numeración.
        taken = set(
            session.execute(
                select(ClipCandidate.rank).where(ClipCandidate.project_id == project_id)
            ).scalars()
        )

        position = 0
        for item in suggestions:
            position += 1
            while position in taken:
                position += 1
            session.add(
                ClipCandidate(
                    project_id=project_id,
                    start_time=item.start_time,
                    end_time=item.end_time,
                    start_segment_index=item.start_segment,
                    end_segment_index=item.end_segment,
                    title=item.title,
                    hook=item.hook,
                    reason=item.reason,
                    transcript_excerpt=item.transcript_excerpt,
                    # Listas vacías a NULL: "no hay variantes" y "hay una
                    # lista de cero variantes" son lo mismo, y NULL lo dice
                    # sin obligar a nadie a mirar dentro.
                    title_variants=list(item.title_variants) or None,
                    description=item.description,
                    hashtags=list(item.hashtags) or None,
                    score=item.score,
                    hook_score=item.scores.hook if item.scores else None,
                    curiosity_score=item.scores.curiosity if item.scores else None,
                    emotion_score=item.scores.emotion if item.scores else None,
                    clarity_score=item.scores.clarity if item.scores else None,
                    value_score=item.scores.value if item.scores else None,
                    shareability_score=item.scores.shareability if item.scores else None,
                    duration_score=item.scores.duration if item.scores else None,
                    status=status,
                    source=item.source,
                    rank=position,
                )
            )


# ----------------------------------------------------------------------- render
def _render_stage(project_id: uuid.UUID, log: Any) -> None:
    """Recorta cada candidato seleccionado y lo renderiza en vertical 9:16."""
    with sync_session_scope() as session:
        project = _require(session, project_id)
        if not project.source_video_path:
            raise ClipForgeError("El proyecto no tiene vídeo de origen que recortar")
        video_relative = project.source_video_path
        burn = rules_for(project.content_profile or ContentProfile.TALKING).burn_subtitles

        candidates = list(
            session.execute(
                select(ClipCandidate)
                .where(ClipCandidate.project_id == project_id)
                .where(ClipCandidate.status == CandidateStatus.SELECTED)
                .order_by(ClipCandidate.rank, ClipCandidate.score.desc())
            ).scalars()
        )
        plans = [
            ClipRenderPlan(
                candidate_id=candidate.id,
                rank=candidate.rank or position,
                start=candidate.start_time,
                end=candidate.end_time,
                hook=candidate.hook,
                crop_x=candidate.crop_x,
            )
            for position, candidate in enumerate(candidates, start=1)
        ]
        segments = subtitle_segments(session, project_id)
        project.status = ProjectStatus.GENERATING_CLIPS

    if not plans:
        raise ClipForgeError("No hay candidatos que renderizar")

    setup = build_setup(
        project_id,
        absolute_from_storage(video_relative),
        segments,
        burn_subtitles=burn,
        sample_at=plans[0].start,
    )
    log.info("pipeline.render_started", clips=len(plans), encoder=setup.encoder.name)

    rendered = 0
    for plan in plans:
        try:
            render_and_store(plan, setup)
            rendered += 1
        except ClipForgeError as exc:
            # El fallo de un clip no debe tirar los demás: se marca y se sigue.
            log.warning("pipeline.clip_failed", rank=plan.rank, error=exc.message)
            update_candidate(
                plan.candidate_id, status=CandidateStatus.FAILED, error_message=exc.message
            )

    if rendered == 0:
        raise ClipForgeError("No se ha podido renderizar ningún clip")

    log.info("pipeline.render_finished", rendered=rendered, failed=len(plans) - rendered)
    export_project_clips(project_id, log)


def export_project_clips(project_id: uuid.UUID, log: Any) -> None:
    """Deja una copia de los clips con nombres legibles, para subirlos a mano.

    Nunca tumba el pipeline: los clips ya están renderizados y registrados en
    base de datos, y esto es solo una vista derivada. Que falle un enlace no
    puede convertir un proyecto terminado en uno fallido.
    """
    if not settings.export_clips:
        return

    with sync_session_scope() as session:
        project = _require(session, project_id)
        title = project.title
        credit = SourceCredit(title=project.title, author=project.author, url=project.source_url)
        rows = list(
            session.execute(
                select(ClipCandidate, GeneratedClip)
                .join(GeneratedClip, GeneratedClip.candidate_id == ClipCandidate.id)
                .where(ClipCandidate.project_id == project_id)
                .order_by(ClipCandidate.rank)
            ).all()
        )
        clips = [
            ClipExport(
                rank=candidate.rank or position,
                title=candidate.title,
                video=absolute_from_storage(clip.file_path),
                subtitles=(
                    absolute_from_storage(clip.subtitle_path) if clip.subtitle_path else None
                ),
                description=candidate.description,
                hashtags=tuple(candidate.hashtags or []),
                start=candidate.start_time,
                end=candidate.end_time,
            )
            for position, (candidate, clip) in enumerate(rows, start=1)
        ]

    try:
        folder = export_project(project_id, title, clips, credit)
    except OSError as exc:
        log.warning("pipeline.export_failed", error=str(exc))
        return
    if folder is not None:
        log.info("pipeline.export_finished", folder=str(folder), clips=len(clips))


# --------------------------------------------------- render de un solo candidato
def render_and_store(plan: ClipRenderPlan, setup: RenderSetup) -> None:
    """Genera el clip de un candidato y lo registra en base de datos.

    Compartido entre el pipeline y la tarea de render suelto: es exactamente el
    mismo trabajo, lo único que cambia es quién decide cuándo hacerlo.
    """
    update_candidate(plan.candidate_id, status=CandidateStatus.RENDERING, error_message=None)
    result = render_clip(plan, setup)

    with sync_session_scope() as session:
        session.execute(
            delete(GeneratedClip).where(GeneratedClip.candidate_id == plan.candidate_id)
        )
        session.flush()
        session.add(
            GeneratedClip(
                candidate_id=plan.candidate_id,
                file_path=relative_to_storage(result.path),
                subtitle_path=(
                    relative_to_storage(result.subtitle_path) if result.subtitle_path else None
                ),
                duration=result.duration,
                width=result.width,
                height=result.height,
                filesize_bytes=result.filesize_bytes,
                has_burned_subtitles=result.has_burned_subtitles,
                encoder=result.encoder,
                crop_x=result.crop_x,
                crop_width=result.crop_width,
            )
        )
        candidate = session.get(ClipCandidate, plan.candidate_id)
        if candidate is not None:
            candidate.status = CandidateStatus.RENDERED
            candidate.error_message = None

    logger.info("pipeline.clip_rendered", rank=plan.rank, subtitles=result.cues)


def subtitle_segments(session: Session, project_id: uuid.UUID) -> list[SourceSegment]:
    """Segmentos de la transcripción en tiempos del vídeo original."""
    rows = session.execute(
        select(TranscriptSegment)
        .join(Transcript, Transcript.id == TranscriptSegment.transcript_id)
        .where(Transcript.project_id == project_id)
        .order_by(TranscriptSegment.index)
    ).scalars()
    return [SourceSegment(start=row.start_time, end=row.end_time, text=row.text) for row in rows]


def update_candidate(candidate_id: uuid.UUID, **fields: Any) -> None:
    with sync_session_scope() as session:
        candidate = session.get(ClipCandidate, candidate_id)
        if candidate is None:
            return
        for key, value in fields.items():
            setattr(candidate, key, value)


# ----------------------------------------------------------------------- comunes
def _require(session: Session, project_id: uuid.UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise ClipForgeError(f"El proyecto {project_id} ya no existe")
    return project


def _update(project_id: uuid.UUID, **fields: Any) -> None:
    """Aplica cambios al proyecto en una transacción corta e independiente."""
    with sync_session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            logger.warning("pipeline.project_missing", project_id=str(project_id))
            return
        for key, value in fields.items():
            setattr(project, key, value)


def _cleanup(project_id: uuid.UUID, log: Any, *, keep_source: bool | None = None) -> None:
    """Borra los intermedios según la política de KEEP_* configurada."""
    ProjectStorage(project_id).cleanup(keep_source=keep_source)
    log.info("pipeline.cleanup_done")
