"""Subir clips a YouTube y releer cómo les va.

Cierra el flujo por los dos extremos. Por delante, subir deja de ser abrir una
carpeta y pegar cinco veces el mismo texto a mano. Por detrás —y esto importa
más de lo que parece— el id del vídeo subido es la primera vez que el sistema
puede **comprobar si acierta**: lleva cinco fases afinando una rúbrica de siete
dimensiones sin que ningún clip publicado le haya dicho nunca si sirve.

Las vistas se leen con yt-dlp, no con la API de analíticas: son públicas, no
hacen falta credenciales y no gastan cuota. Es menos preciso que el panel de
YouTube —no hay retención ni impresiones— pero responde a la única pregunta que
de verdad se estaba haciendo: de estos cinco clips, ¿cuál funcionó?
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from clipforge.core.config import settings
from clipforge.core.errors import ClipForgeError
from clipforge.core.logging import get_logger
from clipforge.core.storage import absolute_from_storage
from clipforge.db.models import ClipCandidate, GeneratedClip, Project
from clipforge.db.session import sync_session_scope
from clipforge.services.export import SourceCredit
from clipforge.services.publish import UploadRequest, upload_clip
from clipforge.worker.celery_app import celery_app

logger = get_logger(__name__)

#: Cada cuántos días deja de tener sentido volver a mirar un clip. Un Short que
#: lleva un mes publicado ya ha hecho lo que iba a hacer.
STATS_WINDOW_DAYS = 30


@celery_app.task(name="clipforge.publish.upload_clip", bind=True)
def upload_generated_clip(self: Any, clip_id: str) -> dict[str, Any]:
    """Sube un clip renderizado a YouTube.

    Raises:
        ClipForgeError: si el clip no existe, no está en disco o ya se subió.
    """
    cid = uuid.UUID(clip_id)
    log = logger.bind(clip_id=clip_id, task_id=self.request.id)

    request, video_path = _prepare(cid)
    log.info("publish.uploading", size_mb=round(video_path.stat().st_size / 1e6, 1))

    result = upload_clip(request)

    with sync_session_scope() as session:
        clip = session.get(GeneratedClip, cid)
        if clip is not None:
            clip.youtube_video_id = result.video_id
            clip.published_at = datetime.now(UTC)
            clip.privacy_status = result.privacy

    log.info("publish.done", video_id=result.video_id, privacy=result.privacy)
    return {"clip_id": clip_id, "video_id": result.video_id, "privacy": result.privacy}


@celery_app.task(name="clipforge.publish.refresh_stats", bind=True)
def refresh_stats(self: Any) -> dict[str, Any]:
    """Relee las vistas de los clips publicados hace poco.

    Solo los recientes: un Short de hace un mes ya ha hecho lo que iba a hacer,
    y volver a mirarlo cada día es gastar peticiones en un número que no se
    mueve.
    """
    log = logger.bind(task_id=self.request.id)
    ids = _recent_published()

    updated = 0
    for clip_id, video_id in ids:
        stats = _read_stats(video_id)
        if stats is None:
            continue
        with sync_session_scope() as session:
            clip = session.get(GeneratedClip, clip_id)
            if clip is None:
                continue
            clip.view_count = stats.get("view_count")
            clip.like_count = stats.get("like_count")
            clip.stats_checked_at = datetime.now(UTC)
        updated += 1

    log.info("publish.stats_refreshed", checked=len(ids), updated=updated)
    return {"checked": len(ids), "updated": updated}


# ------------------------------------------------------------------- privado
def _prepare(clip_id: uuid.UUID) -> tuple[UploadRequest, Any]:
    """Compone la petición de subida a partir de lo que hay guardado.

    La descripción se monta aquí, y no se guarda montada, porque el crédito al
    canal de origen depende del proyecto: si mañana cambia, no hay que reescribir
    ninguna fila.
    """
    with sync_session_scope() as session:
        clip = session.get(GeneratedClip, clip_id)
        if clip is None:
            raise ClipForgeError(f"El clip {clip_id} no existe")
        if clip.youtube_video_id:
            raise ClipForgeError(
                f"Este clip ya está subido: youtube.com/shorts/{clip.youtube_video_id}"
            )

        candidate = session.get(ClipCandidate, clip.candidate_id)
        if candidate is None:
            raise ClipForgeError("El clip no tiene candidato: no se sabe qué texto ponerle")

        project = session.get(Project, candidate.project_id)
        credit = SourceCredit(
            title=project.title if project else None,
            author=project.author if project else None,
            url=project.source_url if project else None,
        )

        description = "\n\n".join(
            part
            for part in (
                candidate.description,
                "\n".join(credit.lines()),
                " ".join(f"#{tag}" for tag in (candidate.hashtags or [])),
            )
            if part
        )

        request = UploadRequest(
            video=absolute_from_storage(clip.file_path),
            title=candidate.title,
            description=description,
            tags=tuple(candidate.hashtags or []),
            privacy=settings.youtube_privacy,
        )

    if not request.video.is_file():
        raise ClipForgeError(f"El fichero del clip ya no está en disco: {request.video}")
    return request, request.video


def _recent_published() -> list[tuple[uuid.UUID, str]]:
    """Clips publicados dentro de la ventana en la que aún se mueven las vistas."""
    cutoff = datetime.now(UTC).timestamp() - STATS_WINDOW_DAYS * 86400

    with sync_session_scope() as session:
        rows = list(
            session.execute(
                select(GeneratedClip.id, GeneratedClip.youtube_video_id, GeneratedClip.published_at)
                .where(GeneratedClip.youtube_video_id.is_not(None))
                .order_by(GeneratedClip.published_at.desc())
            ).all()
        )

    return [
        (row[0], str(row[1]))
        for row in rows
        if row[1] and (row[2] is None or row[2].timestamp() >= cutoff)
    ]


def _read_stats(video_id: str) -> dict[str, Any] | None:
    """Vistas y me gusta de un vídeo, o None si no se pueden leer.

    Con yt-dlp y no con la API de analíticas: son datos públicos, así que no
    hacen falta credenciales ni se gasta cuota. Un vídeo privado —que es como
    sube un proyecto sin auditar— no devuelve nada, y eso no es un error.
    """
    try:
        with YoutubeDL(cast(Any, {"quiet": True, "no_warnings": True, "skip_download": True})) as y:
            info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except DownloadError as exc:
        logger.info("publish.stats_unavailable", video_id=video_id, error=str(exc)[:200])
        return None

    if not info:
        return None
    return {"view_count": info.get("view_count"), "like_count": info.get("like_count")}
