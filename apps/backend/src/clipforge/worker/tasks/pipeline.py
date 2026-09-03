"""Pipeline de procesamiento de un proyecto.

La tarea es autocontenida: recibe solo el id del proyecto y obtiene todo lo
demás de PostgreSQL. Así puede ejecutarse en cualquier worker (esta máquina,
otra GPU o RunPod) sin estado compartido más allá de la base de datos.

Cada etapa deja el estado del proyecto actualizado en una transacción corta,
de modo que el frontend puede seguir el progreso por polling. El trabajo pesado
(descarga, ffmpeg, Whisper) ocurre SIEMPRE fuera de transacción: puede durar
minutos y no debe mantener ocupada una conexión de PostgreSQL.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from clipforge.core.config import settings
from clipforge.core.errors import ClipForgeError
from clipforge.core.logging import get_logger
from clipforge.core.storage import (
    ProjectStorage,
    StorageArea,
    absolute_from_storage,
    relative_to_storage,
)
from clipforge.db.models import (
    CandidateStatus,
    ClipCandidate,
    GeneratedClip,
    Project,
    ProjectStatus,
    Transcript,
    TranscriptSegment,
)
from clipforge.db.session import sync_session_scope
from clipforge.services.ai import (
    AnalysisContext,
    ClipAnalyzer,
    ClipSuggestion,
    get_analyzer,
    select_clips,
)
from clipforge.services.ai.chunking import to_analysis_segments
from clipforge.services.download.base import VideoDownloader
from clipforge.services.download.ytdlp import YtDlpDownloader
from clipforge.services.source.urls import validate_source_url
from clipforge.services.subtitles import SourceSegment, build_cues, write_ass, write_srt
from clipforge.services.transcribe.base import Transcriber, TranscriptionResult
from clipforge.services.transcribe.whisper import FasterWhisperTranscriber
from clipforge.services.video.audio import extract_audio
from clipforge.services.video.crop import CropWindow, center_crop_within
from clipforge.services.video.encoder import resolve_encoder
from clipforge.services.video.letterbox import detect_content_window
from clipforge.services.video.probe import probe_video
from clipforge.services.video.render import render_vertical_clip
from clipforge.worker.celery_app import celery_app

logger = get_logger(__name__)

AUDIO_FILENAME = "audio.wav"


@celery_app.task(name="clipforge.pipeline.process_project", bind=True)
def process_project(self: Any, project_id: str) -> dict[str, Any]:
    """Procesa un proyecto de principio a fin.

    FASE 2: descarga y metadatos. FASE 3: audio y transcripción.
    FASE 4: detección de los mejores momentos. FASE 5: recorte y render 9:16.
    """
    pid = uuid.UUID(project_id)
    log = logger.bind(project_id=project_id, task_id=self.request.id)

    try:
        _download_stage(pid, log)
        _transcribe_stage(pid, log)
        _analyze_stage(pid, log)
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

    # FASE 6: el smart crop sustituirá el recorte centrado dentro del render.
    _update(pid, status=ProjectStatus.COMPLETED)
    _cleanup(pid, log)
    log.info("pipeline.completed")
    return {"project_id": project_id, "status": ProjectStatus.COMPLETED}


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
        raise ClipForgeError("El vídeo no tiene pista de audio, no se puede transcribir")

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
    """Extrae el audio y lo transcribe, guardando segmentos con timestamps."""
    with sync_session_scope() as session:
        project = _require(session, project_id)
        if not project.source_video_path:
            raise ClipForgeError("El proyecto no tiene vídeo descargado")
        video_relative = project.source_video_path
        project.status = ProjectStatus.TRANSCRIBING

    storage = ProjectStorage(project_id)
    video_path = absolute_from_storage(video_relative)
    audio_path = storage.path_for(StorageArea.AUDIO, AUDIO_FILENAME)

    log.info("pipeline.audio_extraction_started")
    extract_audio(video_path, audio_path)

    log.info("pipeline.transcription_started")
    result = (transcriber or FasterWhisperTranscriber()).transcribe(audio_path)
    if not result.segments:
        raise ClipForgeError("La transcripción no ha producido texto: el vídeo no tiene voz")

    _save_transcript(project_id, result, relative_to_storage(audio_path))
    log.info(
        "pipeline.transcription_finished",
        language=result.language,
        segments=len(result.segments),
        characters=len(result.full_text),
    )


def _save_transcript(
    project_id: uuid.UUID, result: TranscriptionResult, audio_relative: str
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
            full_text=result.full_text,
            model_name=result.model_name,
            duration=result.duration,
        )
        session.add(transcript)
        session.flush()  # necesitamos el id para los segmentos

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


# ------------------------------------------------------------------- análisis IA
def _analyze_stage(project_id: uuid.UUID, log: Any, analyzer: ClipAnalyzer | None = None) -> None:
    """Detecta los mejores momentos y los guarda como candidatos puntuados."""
    with sync_session_scope() as session:
        project = _require(session, project_id)
        transcript = session.execute(
            select(Transcript).where(Transcript.project_id == project_id)
        ).scalar_one_or_none()
        if transcript is None:
            raise ClipForgeError("El proyecto no tiene transcripción que analizar")

        rows = list(
            session.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.transcript_id == transcript.id)
                .order_by(TranscriptSegment.index)
            ).scalars()
        )
        segments = to_analysis_segments(rows)
        context = AnalysisContext(
            title=project.title, author=project.author, language=transcript.language
        )
        project.status = ProjectStatus.ANALYZING

    if not segments:
        raise ClipForgeError("La transcripción no tiene segmentos que analizar")

    log.info("pipeline.analysis_started", segments=len(segments))
    suggestions = select_clips(segments, context, analyzer or get_analyzer())
    if not suggestions:
        raise ClipForgeError("La IA no ha encontrado ningún momento aprovechable en este vídeo")

    _save_candidates(project_id, suggestions)
    log.info(
        "pipeline.analysis_finished",
        candidates=len(suggestions),
        best_score=suggestions[0].score,
    )


def _save_candidates(project_id: uuid.UUID, suggestions: list[ClipSuggestion]) -> None:
    """Reemplaza los candidatos del proyecto por los recién seleccionados."""
    with sync_session_scope() as session:
        _require(session, project_id)
        # Igual que con la transcripción: un reintento deja un único conjunto.
        session.execute(delete(ClipCandidate).where(ClipCandidate.project_id == project_id))
        session.flush()

        session.add_all(
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
                score=item.score,
                hook_score=item.scores.hook,
                curiosity_score=item.scores.curiosity,
                emotion_score=item.scores.emotion,
                clarity_score=item.scores.clarity,
                value_score=item.scores.value,
                shareability_score=item.scores.shareability,
                duration_score=item.scores.duration,
                # Seleccionados: son los que renderizará la FASE 5.
                status=CandidateStatus.SELECTED,
                rank=position,
            )
            for position, item in enumerate(suggestions, start=1)
        )


# ----------------------------------------------------------------------- render
def _render_stage(project_id: uuid.UUID, log: Any) -> None:
    """Recorta cada candidato y lo renderiza en vertical 9:16."""
    with sync_session_scope() as session:
        project = _require(session, project_id)
        if not project.source_video_path:
            raise ClipForgeError("El proyecto no tiene vídeo de origen que recortar")
        video_relative = project.source_video_path

        candidates = list(
            session.execute(
                select(ClipCandidate)
                .where(ClipCandidate.project_id == project_id)
                .where(ClipCandidate.status != CandidateStatus.REJECTED)
                .order_by(ClipCandidate.rank, ClipCandidate.score.desc())
            ).scalars()
        )
        plans = [
            _ClipPlan(
                candidate_id=candidate.id,
                rank=candidate.rank or position,
                start=candidate.start_time,
                end=candidate.end_time,
            )
            for position, candidate in enumerate(candidates, start=1)
        ]
        segments = _subtitle_segments(session, project_id)
        project.status = ProjectStatus.GENERATING_CLIPS

    if not plans:
        raise ClipForgeError("No hay candidatos que renderizar")

    source = absolute_from_storage(video_relative)
    storage = ProjectStorage(project_id)
    # Ambas cosas se calculan una vez por proyecto: la comprobación de NVENC
    # cuesta cerca de un segundo y la detección de letterbox analiza fotogramas.
    encoder = resolve_encoder()
    probed = probe_video(source)
    content = detect_content_window(source, probed.width, probed.height, start=plans[0].start)
    crop = center_crop_within(content, settings.output_width, settings.output_height)
    log.info(
        "pipeline.render_started",
        clips=len(plans),
        encoder=encoder.name,
        crop=crop.to_filter(),
    )

    rendered = 0
    for plan in plans:
        try:
            _render_one(plan, source, storage, segments, encoder, crop, log)
            rendered += 1
        except ClipForgeError as exc:
            # El fallo de un clip no debe tirar los demás: se marca y se sigue.
            log.warning("pipeline.clip_failed", rank=plan.rank, error=exc.message)
            _update_candidate(
                plan.candidate_id, status=CandidateStatus.FAILED, error_message=exc.message
            )

    if rendered == 0:
        raise ClipForgeError("No se ha podido renderizar ningún clip")

    log.info("pipeline.render_finished", rendered=rendered, failed=len(plans) - rendered)


@dataclass(frozen=True, slots=True)
class _ClipPlan:
    """Lo que hace falta para renderizar un clip, sin la sesión de BD abierta."""

    candidate_id: uuid.UUID
    rank: int
    start: float
    end: float


def _render_one(
    plan: _ClipPlan,
    source: Path,
    storage: ProjectStorage,
    segments: list[SourceSegment],
    encoder: Any,
    crop: CropWindow,
    log: Any,
) -> None:
    """Genera el .srt y el .mp4 de un candidato, y los registra."""
    _update_candidate(plan.candidate_id, status=CandidateStatus.RENDERING, error_message=None)

    stem = f"clip_{plan.rank:02d}_{plan.candidate_id.hex[:8]}"
    cues = build_cues(segments, plan.start, plan.end)

    # Dos ficheros con el mismo contenido y distinto propósito: el .srt es el
    # que se entrega para publicar el clip, el .ass es el que se incrusta.
    subtitle_path = (
        write_srt(cues, storage.path_for(StorageArea.SUBTITLES, f"{stem}.srt")) if cues else None
    )
    burn_path = (
        write_ass(
            cues,
            storage.path_for(StorageArea.TEMP, f"{stem}.ass"),
            settings.output_width,
            settings.output_height,
        )
        if cues
        else None
    )

    result = render_vertical_clip(
        source,
        storage.path_for(StorageArea.CLIPS, f"{stem}.mp4"),
        start=plan.start,
        end=plan.end,
        # BURN_SUBTITLES a false deja el .srt en disco pero no lo quema, para
        # poder publicar el clip limpio y subir los subtítulos aparte.
        subtitles=burn_path if settings.burn_subtitles else None,
        crop=crop,
        encoder=encoder,
    )
    storage.assert_within_root(result.path)

    with sync_session_scope() as session:
        session.execute(
            delete(GeneratedClip).where(GeneratedClip.candidate_id == plan.candidate_id)
        )
        session.flush()
        session.add(
            GeneratedClip(
                candidate_id=plan.candidate_id,
                file_path=relative_to_storage(result.path),
                subtitle_path=relative_to_storage(subtitle_path) if subtitle_path else None,
                duration=result.duration,
                width=result.width,
                height=result.height,
                filesize_bytes=result.filesize_bytes,
                has_burned_subtitles=result.has_burned_subtitles,
                encoder=result.encoder,
            )
        )
        candidate = session.get(ClipCandidate, plan.candidate_id)
        if candidate is not None:
            candidate.status = CandidateStatus.RENDERED
            candidate.error_message = None

    log.info("pipeline.clip_rendered", rank=plan.rank, subtitles=len(cues))


def _subtitle_segments(session: Session, project_id: uuid.UUID) -> list[SourceSegment]:
    """Segmentos de la transcripción en tiempos del vídeo original."""
    rows = session.execute(
        select(TranscriptSegment)
        .join(Transcript, Transcript.id == TranscriptSegment.transcript_id)
        .where(Transcript.project_id == project_id)
        .order_by(TranscriptSegment.index)
    ).scalars()
    return [SourceSegment(start=row.start_time, end=row.end_time, text=row.text) for row in rows]


def _update_candidate(candidate_id: uuid.UUID, **fields: Any) -> None:
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


def _cleanup(project_id: uuid.UUID, log: Any) -> None:
    """Borra los intermedios según la política de KEEP_* configurada."""
    ProjectStorage(project_id).cleanup()
    log.info("pipeline.cleanup_done")
