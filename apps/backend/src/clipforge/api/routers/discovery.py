"""Buscar vídeos y vigilar canales sin salir de la aplicación.

Es la mitad que le faltaba al pipeline. Hasta ahora esperaba a que alguien
pegase una URL; con esto los vídeos se buscan aquí y los canales traen los
suyos solos.

Nada de esto usa la API de datos de YouTube: ni clave, ni cuota. Ver
`services/source/discover.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from clipforge.api.deps import DbSession
from clipforge.api.schemas.discovery import (
    BatchCreate,
    BatchResult,
    ChannelCreate,
    ChannelRead,
    ChannelUpdate,
    VideoResultRead,
)
from clipforge.core.config import settings
from clipforge.core.errors import ClipForgeError, ConflictError, NotFoundError
from clipforge.core.logging import get_logger
from clipforge.db.models import Project, ProjectStatus, PublishChannel, WatchedChannel
from clipforge.services.source.discover import (
    DiscoveryFilters,
    VideoResult,
    channel_feed,
    resolve_channel,
    search_videos,
)
from clipforge.services.source.urls import validate_source_url

router = APIRouter(tags=["discovery"])
logger = get_logger(__name__)


# -------------------------------------------------------------------- buscar
@router.get("/search", response_model=list[VideoResultRead], summary="Buscar vídeos en YouTube")
async def search(
    session: DbSession,
    q: str = Query(..., min_length=1, description="Qué buscar"),
    limit: int = Query(0, ge=0, le=30, description="0 = el valor configurado"),
    min_duration: int | None = Query(None, ge=0),
    max_duration: int | None = Query(None, ge=0),
    min_views: int | None = Query(None, ge=0),
) -> list[VideoResultRead]:
    """Busca en YouTube y marca lo que ya está en la cola.

    La búsqueda es una llamada de red bloqueante, así que se aparta a un hilo:
    dejar el bucle de eventos parado un segundo y medio congelaría el resto de
    la API mientras alguien escribe en el buscador.
    """
    filters = DiscoveryFilters(
        min_duration=min_duration, max_duration=max_duration, min_views=min_views
    )
    videos = await asyncio.to_thread(
        search_videos, q, limit=limit or settings.search_results, filters=filters
    )
    return await _mark_known(session, videos)


# ------------------------------------------------------------------- tandas
@router.post(
    "/projects/batch",
    response_model=BatchResult,
    status_code=status.HTTP_201_CREATED,
    summary="Encolar varias URLs de una vez",
)
async def create_batch(payload: BatchCreate, session: DbSession) -> BatchResult:
    """Crea un proyecto por URL y encola todos.

    Una URL mala no tumba la tanda: se anota en `rejected` con su motivo y las
    demás siguen. Marcar diez vídeos en el buscador y perderlos todos porque
    uno era privado sería una forma tonta de gastarle el tiempo al usuario.
    """
    queued: list[uuid.UUID] = []
    duplicated: list[str] = []
    rejected: dict[str, str] = {}
    keywords = (payload.keywords or "").strip() or None

    for raw in payload.urls:
        try:
            ref = validate_source_url(raw)
        except ClipForgeError as exc:
            rejected[raw] = exc.message
            continue

        existing = await session.execute(
            select(Project.id).where(Project.source_url == ref.url).limit(1)
        )
        if existing.first() is not None:
            duplicated.append(ref.url)
            continue

        project = Project(
            source_url=ref.url,
            source_type=ref.source_type,
            status=ProjectStatus.CREATED,
            keywords=keywords,
        )
        session.add(project)
        await session.flush()
        queued.append(project.id)

    # Commit ANTES de encolar: un worker que recoja la tarea antes de que la
    # fila esté visible no encontraría el proyecto.
    await session.commit()

    for project_id in queued:
        await _enqueue(session, project_id)
    await session.commit()

    logger.info(
        "projects.batch_created",
        queued=len(queued),
        duplicated=len(duplicated),
        rejected=len(rejected),
    )
    return BatchResult(queued=queued, duplicated=duplicated, rejected=rejected)


# ------------------------------------------------------------------ canales
@router.get("/channels", response_model=list[ChannelRead], summary="Canales vigilados")
async def list_channels(session: DbSession) -> list[ChannelRead]:
    rows = await session.execute(select(WatchedChannel).order_by(WatchedChannel.created_at))
    return [_channel_read(row) for row in rows.scalars()]


@router.post(
    "/channels",
    response_model=ChannelRead,
    status_code=status.HTTP_201_CREATED,
    summary="Vigilar un canal",
)
async def add_channel(payload: ChannelCreate, session: DbSession) -> ChannelRead:
    """Da de alta un canal y deja su marca de agua en el presente.

    Lo segundo es lo importante: sin fijarla, la primera revisión encolaría los
    quince vídeos que trae el feed. Vigilar un canal es querer lo que publique
    **a partir de ahora**, no su historial.
    """
    ref = await asyncio.to_thread(resolve_channel, payload.channel)

    existing = await session.execute(
        select(WatchedChannel).where(WatchedChannel.channel_id == ref.channel_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(f"El canal '{ref.title}' ya está vigilado")

    latest = await asyncio.to_thread(_latest_published, ref.channel_id)

    channel = WatchedChannel(
        channel_id=ref.channel_id,
        title=ref.title,
        url=ref.url,
        min_duration=payload.min_duration,
        max_duration=payload.max_duration,
        min_views=payload.min_views,
        keywords=(payload.keywords or "").strip() or None,
        publish_channel_id=await _require_destination(payload.publish_channel_id, session),
        last_video_published_at=latest,
    )
    session.add(channel)
    await session.commit()
    await session.refresh(channel)

    logger.info("channel.watched", channel_id=ref.channel_id, title=ref.title)
    return _channel_read(channel)


@router.patch("/channels/{channel_uuid}", response_model=ChannelRead, summary="Editar un canal")
async def update_channel(
    channel_uuid: uuid.UUID, payload: ChannelUpdate, session: DbSession
) -> ChannelRead:
    channel = await _require_channel(channel_uuid, session)

    if payload.enabled is not None:
        channel.enabled = payload.enabled
    if payload.min_duration is not None:
        channel.min_duration = payload.min_duration
    if payload.max_duration is not None:
        channel.max_duration = payload.max_duration
    if payload.min_views is not None:
        channel.min_views = payload.min_views
    if payload.keywords is not None:
        channel.keywords = payload.keywords.strip() or None
    # Aquí sí importa si el campo *venía* en el cuerpo: mandar null es la forma
    # de decir "estos clips ya no van a un canal fijo", y con la regla de los
    # demás campos eso sería indistinguible de no mandarlo.
    if "publish_channel_id" in payload.model_fields_set:
        channel.publish_channel_id = await _require_destination(payload.publish_channel_id, session)

    await session.commit()
    await session.refresh(channel)
    return _channel_read(channel)


@router.delete(
    "/channels/{channel_uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dejar de vigilar un canal",
)
async def delete_channel(channel_uuid: uuid.UUID, session: DbSession) -> None:
    channel = await _require_channel(channel_uuid, session)
    await session.delete(channel)
    await session.commit()
    logger.info("channel.unwatched", channel_id=channel.channel_id)


@router.post("/channels/{channel_uuid}/check", summary="Revisar un canal ahora")
async def check_channel(channel_uuid: uuid.UUID, session: DbSession) -> dict[str, str]:
    """Lanza la revisión de un canal sin esperar al temporizador."""
    channel = await _require_channel(channel_uuid, session)

    from clipforge.worker.tasks.ingest import poll_channels

    task = poll_channels.delay(channel.channel_id)
    return {"task_id": str(task.id)}


# ------------------------------------------------------------------ privado
def _channel_read(channel: WatchedChannel) -> ChannelRead:
    """Vista del canal, con cuanto lleva sin publicar.

    El dato se calcula aqui y no se guarda: se deduce de la marca de agua,
    y una columna mas seria un dato que puede quedarse viejo sin que nadie
    lo note.
    """
    silent: int | None = None
    if channel.last_video_published_at is not None:
        silent = (datetime.now(UTC) - channel.last_video_published_at).days

    read = ChannelRead.model_validate(channel, from_attributes=True)
    return read.model_copy(update={"days_since_last_video": silent})


async def _require_channel(channel_uuid: uuid.UUID, session: DbSession) -> WatchedChannel:
    channel = await session.get(WatchedChannel, channel_uuid)
    if channel is None:
        raise NotFoundError(f"Canal {channel_uuid} no encontrado")
    return channel


async def _require_destination(
    destination: uuid.UUID | None, session: DbSession
) -> uuid.UUID | None:
    """Comprueba que el canal de destino existe antes de guardarlo.

    Sin esto, un id inventado no fallaría aquí sino en el ``COMMIT``, como un
    error de integridad convertido en un 500 sin explicación. Vale más un 404
    que diga cuál es el canal que no existe.
    """
    if destination is None:
        return None

    if await session.get(PublishChannel, destination) is None:
        raise NotFoundError(f"Canal de publicación {destination} no encontrado")
    return destination


async def _mark_known(session: DbSession, videos: list[VideoResult]) -> list[VideoResultRead]:
    """Marca los resultados que ya tienen proyecto.

    En una consulta y no en una por vídeo: son doce resultados y doce viajes a
    la base de datos por cada tecla del buscador serían doce de más.
    """
    urls = [video.url for video in videos]
    known: set[str] = set()
    if urls:
        rows = await session.execute(select(Project.source_url).where(Project.source_url.in_(urls)))
        known = {url for url in rows.scalars() if url}

    return [
        VideoResultRead(
            video_id=video.video_id,
            title=video.title,
            url=video.url,
            channel=video.channel,
            duration=video.duration,
            view_count=video.view_count,
            thumbnail=video.thumbnail,
            published_at=video.published_at,
            already_queued=video.url in known,
        )
        for video in videos
    ]


def _latest_published(channel_id: str) -> datetime | None:
    """Fecha del vídeo más reciente del canal, o None si el feed falla.

    Que el feed no conteste al dar de alta no debe impedir vigilar el canal:
    la marca de agua se quedará vacía y la primera revisión hará el trabajo.
    """
    try:
        videos = channel_feed(channel_id)
    except ClipForgeError:
        return None
    dates = [video.published_at for video in videos if video.published_at is not None]
    return max(dates) if dates else None


async def _enqueue(session: DbSession, project_id: uuid.UUID) -> None:
    """Encola el pipeline de un proyecto y le anota su tarea."""
    from clipforge.worker.tasks.pipeline import process_project

    task = process_project.delay(str(project_id))
    project = await session.get(Project, project_id)
    if project is not None:
        project.task_id = str(task.id)
