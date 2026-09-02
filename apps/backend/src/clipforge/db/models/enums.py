"""Enumeraciones del dominio.

Se persisten como VARCHAR con CHECK constraint (`native_enum=False`) en lugar de
tipos ENUM nativos de Postgres: anadir un estado nuevo es una migracion trivial.
"""

from __future__ import annotations

from enum import StrEnum


class ProjectStatus(StrEnum):
    CREATED = "CREATED"
    DOWNLOADING = "DOWNLOADING"
    TRANSCRIBING = "TRANSCRIBING"
    ANALYZING = "ANALYZING"
    GENERATING_CLIPS = "GENERATING_CLIPS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (ProjectStatus.COMPLETED, ProjectStatus.FAILED)

    @property
    def is_running(self) -> bool:
        return not self.is_terminal and self is not ProjectStatus.CREATED


class SourceType(StrEnum):
    YOUTUBE = "YOUTUBE"
    UPLOAD = "UPLOAD"


class CandidateStatus(StrEnum):
    PENDING = "PENDING"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    RENDERING = "RENDERING"
    RENDERED = "RENDERED"
    FAILED = "FAILED"


#: Orden del pipeline, usado para calcular progreso en la UI.
PIPELINE_ORDER: tuple[ProjectStatus, ...] = (
    ProjectStatus.CREATED,
    ProjectStatus.DOWNLOADING,
    ProjectStatus.TRANSCRIBING,
    ProjectStatus.ANALYZING,
    ProjectStatus.GENERATING_CLIPS,
    ProjectStatus.COMPLETED,
)
