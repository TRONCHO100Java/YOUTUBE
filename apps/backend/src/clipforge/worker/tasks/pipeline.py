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
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from clipforge.core.errors import ClipForgeError
from clipforge.core.logging import get_logger
from clipforge.core.storage import (
    ProjectStorage,
    StorageArea,
    absolute_from_storage,
    relative_to_storage,
)
from clipforge.db.models import Project, ProjectStatus, Transcript, TranscriptSegment
from clipforge.db.session import sync_session_scope
from clipforge.services.download.base import VideoDownloader
from clipforge.services.download.ytdlp import YtDlpDownloader
from clipforge.services.source.urls import validate_source_url
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
    El análisis de IA y el render llegan en las fases siguientes.
    """
    pid = uuid.UUID(project_id)
    log = logger.bind(project_id=project_id, task_id=self.request.id)

    try:
        _download_stage(pid, log)
        _transcribe_stage(pid, log)
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

    # FASE 4: encadenar aquí el análisis de IA. Mientras la transcripción sea la
    # última etapa implementada, el proyecto se da por terminado al acabarla.
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
