"""Schemas de los canales de destino."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

#: Tope de valores por filtro. Más de una decena deja de ser una línea
#: editorial y pasa a ser "todo", que ya se consigue dejándolo vacío.
MAX_FILTER_VALUES = 12
MAX_URL = 2048


class PublishChannelBase(BaseModel):
    """Lo que se puede configurar de un canal."""

    niche: str | None = Field(
        None, max_length=64, description="Nicho que acepta. Vacío = cualquiera"
    )
    people: list[str] = Field(
        default_factory=list,
        max_length=MAX_FILTER_VALUES,
        description="Quién sale: basta con que el clip mencione a uno",
        examples=[["speed", "kai cenat"]],
    )
    topics: list[str] = Field(
        default_factory=list, max_length=MAX_FILTER_VALUES, description="Temas que acepta"
    )
    kinds: list[str] = Field(
        default_factory=list,
        max_length=MAX_FILTER_VALUES,
        description="Clases de momento: fail, reaccion, gag…",
    )
    min_score: float = Field(
        0.0, ge=0, le=100, description="Nota mínima para publicar en este canal"
    )
    priority: int = Field(0, ge=0, le=100, description="A igualdad de encaje, gana el más alto")
    notes: str | None = Field(None, max_length=1000, description="Para qué es este canal")
    outro_handle: str | None = Field(
        None,
        max_length=120,
        description="Nombre con arroba que sale en el cierre",
        examples=["@ClipRushViralRush"],
    )
    outro_tagline: str | None = Field(
        None,
        max_length=120,
        description="Línea roja del cierre. Vacía = la de la plantilla",
        examples=["NEW CLIPS EVERY DAY"],
    )


class PublishChannelCreate(PublishChannelBase):
    """Cuerpo de POST /publish-channels."""

    name: str = Field(..., min_length=1, max_length=120, examples=["Speed Clips"])
    url: str | None = Field(
        None,
        min_length=1,
        max_length=MAX_URL,
        description="URL del canal. Se puede dejar para despues",
        examples=["https://www.youtube.com/@IShowSpeed"],
    )


class PublishChannelUpdate(BaseModel):
    """Cuerpo de PATCH. Todo opcional: lo que no venga se queda como estaba.

    No hereda de la base a propósito. Heredar y volver opcional cada campo
    estrecha el tipo del padre, que es justo lo que un tipo no puede hacer:
    quien reciba un `PublishChannelBase` esperaría una lista y podría
    encontrarse un None.
    """

    name: str | None = Field(None, min_length=1, max_length=120)
    url: str | None = Field(None, min_length=1, max_length=MAX_URL)
    enabled: bool | None = None
    niche: str | None = Field(None, max_length=64)
    people: list[str] | None = Field(None, max_length=MAX_FILTER_VALUES)
    topics: list[str] | None = Field(None, max_length=MAX_FILTER_VALUES)
    kinds: list[str] | None = Field(None, max_length=MAX_FILTER_VALUES)
    min_score: float | None = Field(None, ge=0, le=100)
    priority: int | None = Field(None, ge=0, le=100)
    notes: str | None = Field(None, max_length=1000)
    outro_handle: str | None = Field(None, max_length=120)
    outro_tagline: str | None = Field(None, max_length=120)


class PublishChannelRead(PublishChannelCreate):
    """Un canal de destino tal y como se guarda."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    enabled: bool
    youtube_channel_id: str | None
    #: Si el cierre ya está construido. El texto solo dice qué DEBERÍA
    #: poner; esto dice si existe el vídeo que lo pone.
    has_outro: bool
    created_at: datetime


class RoutedClip(BaseModel):
    """Un clip listo para subir y el canal que le toca."""

    clip_id: uuid.UUID
    candidate_id: uuid.UUID
    project_title: str | None
    title: str
    description: str | None
    hashtags: list[str]
    score: float
    duration: float | None
    #: Etiquetas que han decidido el reparto, para poder discutirlo.
    tags: dict[str, object] | None
    #: None cuando ningún canal lo acepta: ese lo reparte una persona.
    channel_id: uuid.UUID | None
    channel_name: str | None
    #: Si ya está en YouTube, para no subirlo dos veces.
    youtube_video_id: str | None
