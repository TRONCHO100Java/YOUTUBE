"""Schemas de Project expuestos por la API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from clipforge.db.models.enums import (
    PIPELINE_ORDER,
    ContentProfile,
    ProjectStatus,
    SourceType,
)
from clipforge.services.source.urls import MAX_URL_LENGTH

#: Tope del campo de palabras clave. Da de sobra para una decena de
#: términos y evita que alguien pegue ahí una transcripción entera.
MAX_KEYWORDS_LENGTH = 500


class ProjectCreate(BaseModel):
    """Cuerpo de POST /projects."""

    url: str = Field(
        ...,
        min_length=1,
        max_length=MAX_URL_LENGTH,
        description="URL del vídeo de YouTube a procesar",
        examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )
    keywords: str | None = Field(
        None,
        max_length=MAX_KEYWORDS_LENGTH,
        description=(
            "De qué va el vídeo y quién sale, separado por comas. Se usa para "
            "escribir títulos con los nombres por los que la gente busca."
        ),
        examples=["Kai Cenat, Speed, Among Us"],
    )


class ProjectUpdate(BaseModel):
    """Cuerpo de PATCH /projects/{id}.

    Existe por una razón concreta: las palabras clave se suelen recordar
    DESPUÉS de pegar la URL, y sin esto la única forma de añadirlas sería
    borrar el proyecto y volver a descargar el vídeo entero.
    """

    keywords: str | None = Field(
        None,
        max_length=MAX_KEYWORDS_LENGTH,
        description="Reemplaza las palabras clave; cadena vacía las borra",
    )


class ProjectSummary(BaseModel):
    """Vista de listado."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_url: str | None
    source_type: SourceType
    status: ProjectStatus
    title: str | None
    duration: float | None
    thumbnail_url: str | None
    # Se incluye en el listado para poder mostrar por qué falló un proyecto
    # —o por qué quedó pendiente de revisión— sin pedir el detalle de cada uno.
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectSummary):
    """Vista de detalle, la que consulta el polling del frontend."""

    author: str | None = None
    #: Lo que escribió el usuario sobre el vídeo, tal cual, para poder editarlo.
    keywords: str | None = None
    progress: float = Field(0.0, ge=0.0, le=1.0, description="Avance 0..1 del pipeline")
    #: Perfil detectado tras transcribir; decide rúbrica y duraciones.
    content_profile: ContentProfile | None = None
    #: Fracción del vídeo con habla real. Explica por qué se eligió el perfil.
    speech_ratio: float | None = None
    #: Si hay línea de tiempo de señales para pintar en el editor.
    has_signals: bool = False

    @classmethod
    def from_model(cls, project: object) -> ProjectDetail:
        detail = cls.model_validate(project, from_attributes=True)
        detail.progress = compute_progress(detail.status)
        # El JSON de señales pesa cientos de kilobytes y el polling pide este
        # recurso cada pocos segundos: aquí solo se dice si existe, y quien lo
        # necesite lo pide a /signals.
        detail.has_signals = bool(getattr(project, "signals", None))
        return detail


def compute_progress(status: ProjectStatus) -> float:
    """Progreso aproximado derivado del estado; suficiente para la barra del MVP."""
    if status is ProjectStatus.FAILED:
        return 0.0
    if status is ProjectStatus.COMPLETED:
        return 1.0
    # El pipeline llegó hasta el análisis y paró ahí a esperar a una persona:
    # el progreso es real, no cero, y la barra no debe retroceder.
    if status is ProjectStatus.NEEDS_REVIEW:
        return round(PIPELINE_ORDER.index(ProjectStatus.ANALYZING) / (len(PIPELINE_ORDER) - 1), 4)
    try:
        position = PIPELINE_ORDER.index(status)
    except ValueError:
        return 0.0
    return round(position / (len(PIPELINE_ORDER) - 1), 4)
