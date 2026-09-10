"""Schemas de búsqueda y canales vigilados."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from clipforge.services.source.urls import MAX_URL_LENGTH

#: Un canal se puede indicar de muchas formas (@handle, URL, id); ninguna
#: legítima llega a esto.
MAX_CHANNEL_REF = 512

#: Tope de URLs por tanda. Más no es una tanda, es un canal vigilado.
MAX_BATCH_URLS = 25


class VideoResultRead(BaseModel):
    """Un vídeo encontrado, con lo justo para decidir sin descargarlo."""

    video_id: str
    title: str
    url: str
    channel: str | None = None
    duration: float | None = None
    view_count: int | None = None
    thumbnail: str | None = None
    published_at: datetime | None = None
    #: Si ya hay un proyecto para esta URL. Evita encolar dos veces el mismo
    #: vídeo sin darse cuenta, que cuesta una descarga entera.
    already_queued: bool = False


class BatchCreate(BaseModel):
    """Cuerpo de POST /projects/batch."""

    urls: list[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_BATCH_URLS,
        description="URLs de YouTube a encolar",
    )
    keywords: str | None = Field(
        None,
        max_length=500,
        description="Palabras clave que heredan todos los proyectos de la tanda",
    )


class BatchResult(BaseModel):
    """Qué ha pasado con cada URL de la tanda.

    Se informa de las tres cosas por separado porque significan cosas
    distintas: lo encolado es trabajo nuevo, lo repetido es una descarga que
    nos hemos ahorrado y lo rechazado es un error del usuario.
    """

    queued: list[uuid.UUID]
    duplicated: list[str]
    rejected: dict[str, str]


class ChannelCreate(BaseModel):
    """Cuerpo de POST /channels."""

    channel: str = Field(
        ...,
        min_length=1,
        max_length=MAX_CHANNEL_REF,
        description="@handle, URL del canal o URL de cualquiera de sus vídeos",
        examples=["@KaiCenat"],
    )
    min_duration: int | None = Field(None, ge=0, description="Segundos mínimos del vídeo")
    max_duration: int | None = Field(None, ge=0, description="Segundos máximos del vídeo")
    min_views: int | None = Field(None, ge=0, description="Vistas mínimas")
    keywords: str | None = Field(
        None, max_length=500, description="Palabras clave para los proyectos de este canal"
    )
    publish_channel_id: uuid.UUID | None = Field(
        None, description="Canal propio al que van los clips de este"
    )


class ChannelUpdate(BaseModel):
    """Cuerpo de PATCH /channels/{id}. Todo opcional.

    El destino se lee con ``model_fields_set`` y no por ``is not None``: es el
    único campo que se puede querer *vaciar*, y con la regla de los demás
    ("None = no lo toques") no habría forma de decir "ya no va a ningún canal".
    """

    enabled: bool | None = None
    min_duration: int | None = Field(None, ge=0)
    max_duration: int | None = Field(None, ge=0)
    min_views: int | None = Field(None, ge=0)
    keywords: str | None = Field(None, max_length=500)
    publish_channel_id: uuid.UUID | None = None


class ChannelRead(BaseModel):
    """Un canal vigilado, con el resultado de su última revisión."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_id: str
    title: str
    url: str
    enabled: bool
    min_duration: int | None
    max_duration: int | None
    min_views: int | None
    keywords: str | None
    #: A qué canal propio van los clips de este. null = se reparten por
    #: etiquetas, como antes de que existiera esto.
    publish_channel_id: uuid.UUID | None
    last_video_published_at: datetime | None
    last_checked_at: datetime | None
    #: Por qué falló la última revisión. Un canal que lleva días callado y uno
    #: que lleva días fallando se ven igual sin esto.
    last_error: str | None
    projects_created: int
    created_at: datetime


class SearchQuery(BaseModel):
    """Parámetros de búsqueda, validados antes de llegar a yt-dlp."""

    q: str = Field(..., min_length=1, max_length=MAX_URL_LENGTH)
    limit: int = Field(12, ge=1, le=30)
    min_duration: int | None = Field(None, ge=0)
    max_duration: int | None = Field(None, ge=0)
    min_views: int | None = Field(None, ge=0)
