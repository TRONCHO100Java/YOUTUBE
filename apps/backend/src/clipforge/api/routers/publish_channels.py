"""Canales de destino y reparto de clips.

Aquí se declara qué quiere cada canal propio, y se consulta qué clip le toca a
cada uno. No sube nada: subir es otra cosa (`/api/clips/{id}/publish`) y aquí
solo se decide el destino.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from clipforge.api.deps import DbSession
from clipforge.api.schemas.publish_channel import (
    PublishChannelCreate,
    PublishChannelRead,
    PublishChannelUpdate,
    RoutedClip,
)
from clipforge.core.errors import NotFoundError
from clipforge.core.logging import get_logger
from clipforge.db.models import ClipCandidate, GeneratedClip, PublishChannel
from clipforge.services.publish import ClipFacts, route

router = APIRouter(prefix="/publish-channels", tags=["publish"])
logger = get_logger(__name__)


@router.get("", response_model=list[PublishChannelRead], summary="Canales de destino")
async def list_channels(session: DbSession) -> list[PublishChannelRead]:
    rows = await session.execute(
        select(PublishChannel).order_by(PublishChannel.priority.desc(), PublishChannel.name)
    )
    return [_read(channel) for channel in rows.scalars()]


@router.post(
    "",
    response_model=PublishChannelRead,
    status_code=status.HTTP_201_CREATED,
    summary="Dar de alta un canal de destino",
)
async def create_channel(payload: PublishChannelCreate, session: DbSession) -> PublishChannelRead:
    """Registra un canal propio y qué contenido va en él."""
    channel = PublishChannel(
        name=payload.name.strip(),
        url=(payload.url or "").strip() or None,
        niche=(payload.niche or "").strip() or None,
        people=payload.people or None,
        topics=payload.topics or None,
        kinds=payload.kinds or None,
        min_score=payload.min_score,
        priority=payload.priority,
        notes=(payload.notes or "").strip() or None,
    )
    session.add(channel)
    await session.commit()
    await session.refresh(channel)

    logger.info("publish_channel.created", name=channel.name)
    return _read(channel)


@router.patch("/{channel_id}", response_model=PublishChannelRead, summary="Editar un canal")
async def update_channel(
    channel_id: uuid.UUID, payload: PublishChannelUpdate, session: DbSession
) -> PublishChannelRead:
    channel = await _require(channel_id, session)

    if payload.name is not None:
        channel.name = payload.name.strip()
    if payload.url is not None:
        channel.url = payload.url.strip() or None
    if payload.enabled is not None:
        channel.enabled = payload.enabled
    if payload.niche is not None:
        channel.niche = payload.niche.strip() or None
    if payload.people is not None:
        channel.people = payload.people or None
    if payload.topics is not None:
        channel.topics = payload.topics or None
    if payload.kinds is not None:
        channel.kinds = payload.kinds or None
    if payload.min_score is not None:
        channel.min_score = payload.min_score
    if payload.priority is not None:
        channel.priority = payload.priority
    if payload.notes is not None:
        channel.notes = payload.notes.strip() or None

    await session.commit()
    await session.refresh(channel)
    return _read(channel)


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Borrar un canal")
async def delete_channel(channel_id: uuid.UUID, session: DbSession) -> None:
    channel = await _require(channel_id, session)
    await session.delete(channel)
    await session.commit()
    logger.info("publish_channel.deleted", name=channel.name)


@router.get(
    "/routing",
    response_model=list[RoutedClip],
    summary="Qué clip va a qué canal",
)
async def routing(
    session: DbSession,
    pending: bool = Query(True, description="Solo los que no se han subido todavía"),
    limit: int = Query(50, ge=1, le=200),
) -> list[RoutedClip]:
    """Reparte los clips ya renderizados entre los canales configurados.

    No cambia nada: es la vista previa del reparto. Un clip sin canal no es un
    fallo — significa que no encaja limpiamente en ninguna línea editorial y lo
    coloca una persona.
    """
    channels = list((await session.execute(select(PublishChannel))).scalars())

    query = (
        select(GeneratedClip)
        .options(selectinload(GeneratedClip.candidate).selectinload(ClipCandidate.project))
        .order_by(GeneratedClip.created_at.desc())
        .limit(limit)
    )
    if pending:
        query = query.where(GeneratedClip.youtube_video_id.is_(None))

    routed: list[RoutedClip] = []
    for clip in (await session.execute(query)).scalars():
        candidate = clip.candidate
        match = route(ClipFacts.from_tags(candidate.tags, score=candidate.score), channels)
        routed.append(
            RoutedClip(
                clip_id=clip.id,
                candidate_id=candidate.id,
                project_title=candidate.project.title if candidate.project else None,
                title=candidate.title,
                description=candidate.description,
                hashtags=list(candidate.hashtags or []),
                score=candidate.score,
                duration=clip.duration,
                tags=candidate.tags,
                channel_id=match.channel.id if match else None,  # type: ignore[attr-defined]
                channel_name=match.channel.name if match else None,
                youtube_video_id=clip.youtube_video_id,
            )
        )

    return routed


# ------------------------------------------------------------------ privado
async def _require(channel_id: uuid.UUID, session: DbSession) -> PublishChannel:
    channel = await session.get(PublishChannel, channel_id)
    if channel is None:
        raise NotFoundError(f"Canal de destino {channel_id} no encontrado")
    return channel


def _read(channel: PublishChannel) -> PublishChannelRead:
    """Vista del canal con las listas siempre presentes.

    NULL y lista vacía significan lo mismo —«este filtro no se usa»— y una
    lista siempre presente le ahorra un caso al frontend.
    """
    return PublishChannelRead(
        id=channel.id,
        name=channel.name,
        url=channel.url,
        enabled=channel.enabled,
        youtube_channel_id=channel.youtube_channel_id,
        niche=channel.niche,
        people=list(channel.people or []),
        topics=list(channel.topics or []),
        kinds=list(channel.kinds or []),
        min_score=channel.min_score,
        priority=channel.priority,
        notes=channel.notes,
        created_at=channel.created_at,
    )
