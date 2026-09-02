"""Schemas de Project expuestos por la API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from clipforge.db.models.enums import PIPELINE_ORDER, ProjectStatus, SourceType


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
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectSummary):
    """Vista de detalle, la que consulta el polling del frontend."""

    author: str | None = None
    error_message: str | None = None
    progress: float = Field(0.0, ge=0.0, le=1.0, description="Avance 0..1 del pipeline")

    @classmethod
    def from_model(cls, project: object) -> ProjectDetail:
        detail = cls.model_validate(project, from_attributes=True)
        detail.progress = compute_progress(detail.status)
        return detail


def compute_progress(status: ProjectStatus) -> float:
    """Progreso aproximado derivado del estado; suficiente para la barra del MVP."""
    if status is ProjectStatus.FAILED:
        return 0.0
    if status is ProjectStatus.COMPLETED:
        return 1.0
    try:
        position = PIPELINE_ORDER.index(status)
    except ValueError:
        return 0.0
    return round(position / (len(PIPELINE_ORDER) - 1), 4)
