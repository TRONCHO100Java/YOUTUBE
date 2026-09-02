"""Pipeline de procesamiento de un proyecto.

La tarea es autocontenida: recibe solo el id del proyecto y obtiene todo lo
demás de PostgreSQL. Así puede ejecutarse en cualquier worker (esta máquina,
otra GPU o RunPod) sin estado compartido más allá de la base de datos.

Las etapas se ejecutan en secuencia y cada una deja el estado del proyecto
actualizado, de modo que el frontend puede seguir el progreso por polling.
"""

from __future__ import annotations

import uuid
from typing import Any

from clipforge.core.errors import ClipForgeError
from clipforge.core.logging import get_logger
from clipforge.core.storage import ProjectStorage, StorageArea, relative_to_storage
from clipforge.db.models import Project, ProjectStatus
from clipforge.db.session import sync_session_scope
from clipforge.services.download.base import VideoDownloader
from clipforge.services.download.ytdlp import YtDlpDownloader
from clipforge.services.source.urls import validate_source_url
from clipforge.services.video.probe import probe_video
from clipforge.worker.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="clipforge.pipeline.process_project", bind=True)
def process_project(self: Any, project_id: str) -> dict[str, Any]:
    """Procesa un proyecto de principio a fin.

    FASE 2: descarga y metadatos. Las etapas de transcripción, análisis y
    render se añadirán aquí en las fases siguientes.
    """
    pid = uuid.UUID(project_id)
    log = logger.bind(project_id=project_id, task_id=self.request.id)

    try:
        _download_stage(pid, log)
    except ClipForgeError as exc:
        # Error esperado (fuente no disponible, vídeo demasiado largo, ffprobe):
        # el mensaje es apto para enseñárselo al usuario.
        log.warning("pipeline.failed", code=exc.code, error=exc.message)
        _update(pid, status=ProjectStatus.FAILED, error_message=exc.message)
        return {"project_id": project_id, "status": ProjectStatus.FAILED, "error": exc.message}
    except Exception as exc:
        log.error("pipeline.crashed", exc_info=exc)
        _update(pid, status=ProjectStatus.FAILED, error_message=f"Error inesperado: {exc}")
        raise

    # FASE 3: encadenar aquí la transcripción. Mientras la descarga sea la
    # última etapa implementada, el proyecto se da por terminado al acabarla.
    _update(pid, status=ProjectStatus.COMPLETED)
    log.info("pipeline.completed")
    return {"project_id": project_id, "status": ProjectStatus.COMPLETED}


def _download_stage(
    project_id: uuid.UUID, log: Any, downloader: VideoDownloader | None = None
) -> None:
    """Descarga el vídeo de origen y guarda sus metadatos reales."""
    with sync_session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise ClipForgeError(f"El proyecto {project_id} ya no existe")
        if not project.source_url:
            raise ClipForgeError("El proyecto no tiene URL de origen")
        source_url = project.source_url
        project.status = ProjectStatus.DOWNLOADING
        project.error_message = None

    ref = validate_source_url(source_url)
    storage = ProjectStorage(project_id)
    storage.ensure_layout()

    # La descarga ocurre FUERA de cualquier transacción: puede durar minutos y
    # no debe mantener ocupada una conexión de PostgreSQL.
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

    _update(
        project_id,
        title=result.metadata.title,
        author=result.metadata.author,
        thumbnail_url=result.metadata.thumbnail_url,
        # La duración fiable es la del fichero, no la anunciada por la fuente.
        duration=probed.duration,
        source_video_path=relative_to_storage(result.video_path),
    )


def _update(project_id: uuid.UUID, **fields: Any) -> None:
    """Aplica cambios al proyecto en una transacción corta e independiente."""
    with sync_session_scope() as session:
        project = session.get(Project, project_id)
        if project is None:
            logger.warning("pipeline.project_missing", project_id=str(project_id))
            return
        for key, value in fields.items():
            setattr(project, key, value)
