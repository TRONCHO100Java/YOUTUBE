"""Schemas de transcripción."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict


class TranscriptSegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    #: Identificador estable del segmento dentro de la transcripción. Es lo que
    #: se le ofrecerá al LLM en la FASE 4 para seleccionar rangos.
    index: int
    start_time: float
    end_time: float
    text: str
    #: Solo se rellena si se pide `include_words`: en un vídeo largo son miles
    #: de entradas y multiplican el tamaño de la respuesta.
    words: list[dict[str, Any]] | None = None


class TranscriptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    language: str | None
    language_probability: float | None
    model_name: str | None
    duration: float | None
    full_text: str
    segments: list[TranscriptSegmentRead]
