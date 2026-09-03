"""Schemas de clips renderizados."""

from __future__ import annotations

import uuid
from datetime import datetime

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

    @classmethod
    def from_model(cls, clip: object) -> GeneratedClipRead:
        candidate = clip.candidate  # type: ignore[attr-defined]
        return cls(
            id=clip.id,  # type: ignore[attr-defined]
            candidate_id=candidate.id,
            project_id=candidate.project_id,
            title=candidate.title,
            hook=candidate.hook,
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
        )
