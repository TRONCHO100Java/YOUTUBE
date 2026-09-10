"""Revisión periódica de los canales vigilados.

Es lo que convierte la aplicación en algo que corre solo: cada pocos minutos se
lee el RSS de cada canal activo y los vídeos nuevos entran en la cola sin que
nadie pegue una URL.

Tres decisiones que gobiernan el módulo:

- **La marca de agua es la fecha de publicación, no la de revisión.** Un vídeo
  publicado hace dos días que aparece hoy en el feed —pasa— no debe encolarse
  si su fecha es anterior a lo que ya se vio.
- **Un canal que falla no para a los demás.** El error se guarda en su fila y
  la revisión sigue: que YouTube tenga un mal rato con un canal no puede dejar
  el resto sin vigilar.
- **El tope por revisión existe.** Un canal que publica quince vídeos de golpe
  no debe convertirse en quince descargas simultáneas.

Va a la cola ligera (`clipforge.ingest.*` no encaja con la ruta de
`clipforge.pipeline.*`): leer un RSS no necesita la tarjeta gráfica.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from clipforge.core.config import settings
from clipforge.core.errors import ClipForgeError
from clipforge.core.logging import get_logger
from clipforge.db.models import Project, ProjectStatus, SourceType, WatchedChannel
from clipforge.db.session import sync_session_scope
from clipforge.services.source.discover import (
    DiscoveryFilters,
    VideoResult,
    channel_feed,
)
from clipforge.worker.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="clipforge.ingest.poll_channels", bind=True)
def poll_channels(self: Any, channel_id: str | None = None) -> dict[str, Any]:
    """Revisa los canales vigilados y encola lo que sea nuevo.

    Con `channel_id` revisa solo ese, que es lo que hace el botón "Revisar
    ahora"; sin él los revisa todos, que es lo que hace el temporizador.
    """
    log = logger.bind(task_id=self.request.id)
    channels = _enabled_channels(channel_id)

    if not channels:
        log.info("ingest.no_channels")
        return {"channels": 0, "queued": 0}

    queued = 0
    for watched in channels:
        queued += _poll_one(watched, log)

    log.info("ingest.finished", channels=len(channels), queued=queued)
    return {"channels": len(channels), "queued": queued}


def _enabled_channels(channel_id: str | None) -> list[str]:
    """Ids de los canales a revisar. Devuelve ids y no filas para no arrastrar
    objetos de una sesión ya cerrada a un trabajo que dura minutos."""
    with sync_session_scope() as session:
        query = select(WatchedChannel.channel_id).where(WatchedChannel.enabled.is_(True))
        if channel_id is not None:
            query = query.where(WatchedChannel.channel_id == channel_id)
        return list(session.execute(query).scalars())


def _poll_one(channel_id: str, log: Any) -> int:
    """Revisa un canal y devuelve cuántos proyectos ha encolado.

    Nunca propaga: un canal roto se anota en su propia fila y la revisión de
    los demás continúa.
    """
    try:
        videos = channel_feed(channel_id)
    except ClipForgeError as exc:
        _record(channel_id, error=exc.message)
        log.warning("ingest.channel_failed", channel_id=channel_id, error=exc.message)
        return 0

    with sync_session_scope() as session:
        watched = session.execute(
            select(WatchedChannel).where(WatchedChannel.channel_id == channel_id)
        ).scalar_one_or_none()
        if watched is None:
            # Lo han borrado entre la lectura y ahora. No es un error.
            return 0

        filters = DiscoveryFilters(
            min_duration=watched.min_duration,
            max_duration=watched.max_duration,
            min_views=watched.min_views,
        )
        watermark = watched.last_video_published_at
        keywords = watched.keywords

        fresh = [video for video in videos if _is_new(video, watermark)]
        accepted = [video for video in fresh if filters.accepts(video)][
            : max(1, settings.ingest_max_per_check)
        ]

        # La marca de agua avanza con TODO lo visto, no solo con lo aceptado:
        # si no, un vídeo descartado por el filtro se volvería a mirar en cada
        # revisión, para siempre.
        newest = _newest_date([*fresh, *videos])
        if newest is not None:
            watched.last_video_published_at = newest

        watched.last_checked_at = datetime.now(UTC)
        watched.last_error = None

        created: list[Project] = []
        for video in accepted:
            if _already_known(session, video.url):
                continue
            project = Project(
                source_url=video.url,
                source_type=SourceType.YOUTUBE,
                status=ProjectStatus.CREATED,
                keywords=keywords,
            )
            session.add(project)
            created.append(project)

        watched.projects_created += len(created)
        # flush para que las filas tengan id; se encola FUERA de la
        # transacción, porque un worker que recoge la tarea antes del
        # commit no encontraría el proyecto.
        session.flush()
        queued = [project.id for project in created]

    for project_id in queued:
        _enqueue(project_id)

    if queued:
        log.info("ingest.channel_queued", channel_id=channel_id, queued=len(queued))
    return len(queued)


def _enqueue(project_id: Any) -> None:
    """Encola el pipeline de un proyecto y le anota su tarea."""
    from clipforge.worker.tasks.pipeline import process_project

    task = process_project.delay(str(project_id))
    with sync_session_scope() as session:
        project = session.get(Project, project_id)
        if project is not None:
            project.task_id = str(task.id)


def _record(channel_id: str, *, error: str) -> None:
    """Anota en el canal que su última revisión falló."""
    with sync_session_scope() as session:
        watched = session.execute(
            select(WatchedChannel).where(WatchedChannel.channel_id == channel_id)
        ).scalar_one_or_none()
        if watched is not None:
            watched.last_checked_at = datetime.now(UTC)
            watched.last_error = error[:500]


def _is_new(video: VideoResult, watermark: datetime | None) -> bool:
    """¿Se publicó después de lo último que vimos?

    Sin marca de agua todo es nuevo, y por eso al dar de alta un canal se fija
    con su último vídeo: si no, la primera revisión encolaría quince.
    """
    if watermark is None:
        return True
    if video.published_at is None:
        # Sin fecha no se puede comparar, y encolarlo en cada revisión sería
        # peor que ignorarlo: el feed trae siempre los mismos quince.
        return False
    return video.published_at > watermark


def _newest_date(videos: list[VideoResult]) -> datetime | None:
    """La fecha de publicación más reciente de la lista."""
    dates = [video.published_at for video in videos if video.published_at is not None]
    return max(dates) if dates else None


def _already_known(session: Any, url: str) -> bool:
    """¿Ya existe un proyecto para esa URL?

    El feed repite los mismos quince vídeos en cada lectura, y un reinicio con
    la marca de agua a medias no puede acabar descargando dos veces lo mismo.
    """
    return (
        session.execute(select(Project.id).where(Project.source_url == url).limit(1)).first()
        is not None
    )
