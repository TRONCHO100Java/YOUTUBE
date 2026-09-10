"""Schemas de clips renderizados."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class GeneratedClipRead(BaseModel):
    """Un MP4 vertical listo para reproducir o descargar.

    Lleva incrustados el título y la puntuación de su candidato para que el
    frontend pueda pintar la tarjeta con una sola petición.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    project_id: uuid.UUID

    title: str
    hook: str | None
    #: Lo que hace falta para rellenar la caja de YouTube al subirlo, sin
    #: tener que abrir el editor ni pedir el candidato aparte.
    description: str | None
    hashtags: list[str]
    reason: str | None
    score: float
    rank: int | None

    start_time: float
    end_time: float
    duration: float | None
    width: int | None
    height: int | None
    filesize_bytes: int | None
    has_burned_subtitles: bool
    has_subtitle_file: bool
    encoder: str | None
    created_at: datetime

    #: Id en YouTube si ya se subio. None = todavia no ha salido de aqui.
    youtube_video_id: str | None
    published_at: datetime | None
    #: Cuándo se borró el fichero para dejar sitio. La ficha sigue aquí.
    deleted_at: datetime | None
    #: Con que privacidad quedo. Un proyecto de API sin auditar sube
    #: SIEMPRE en privado, y creer que algo esta publicado cuando no lo
    #: esta es peor que no haberlo subido.
    privacy_status: str | None
    #: Rendimiento real. Es lo unico que puede decir si la nota acerto.
    view_count: int | None
    like_count: int | None
    #: Qué le pasa al fichero, mirado tras renderizar. None en los clips
    #: generados antes de que existiera la puerta de calidad.
    quality: dict[str, Any] | None

    @classmethod
    def from_model(cls, clip: object) -> GeneratedClipRead:
        candidate = clip.candidate  # type: ignore[attr-defined]
        return cls(
            id=clip.id,  # type: ignore[attr-defined]
            candidate_id=candidate.id,
            project_id=candidate.project_id,
            title=candidate.title,
            hook=candidate.hook,
            description=candidate.description,
            hashtags=list(candidate.hashtags or []),
            reason=candidate.reason,
            score=candidate.score,
            rank=candidate.rank,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            duration=clip.duration,  # type: ignore[attr-defined]
            width=clip.width,  # type: ignore[attr-defined]
            height=clip.height,  # type: ignore[attr-defined]
            filesize_bytes=clip.filesize_bytes,  # type: ignore[attr-defined]
            has_burned_subtitles=clip.has_burned_subtitles,  # type: ignore[attr-defined]
            has_subtitle_file=clip.subtitle_path is not None,  # type: ignore[attr-defined]
            encoder=clip.encoder,  # type: ignore[attr-defined]
            created_at=clip.created_at,  # type: ignore[attr-defined]
            youtube_video_id=clip.youtube_video_id,  # type: ignore[attr-defined]
            published_at=clip.published_at,  # type: ignore[attr-defined]
            deleted_at=clip.deleted_at,  # type: ignore[attr-defined]
            privacy_status=clip.privacy_status,  # type: ignore[attr-defined]
            view_count=clip.view_count,  # type: ignore[attr-defined]
            like_count=clip.like_count,  # type: ignore[attr-defined]
            quality=clip.quality,  # type: ignore[attr-defined]
        )
