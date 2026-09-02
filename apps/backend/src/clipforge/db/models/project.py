"""Entidad Project: una URL de origen y su recorrido por el pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clipforge.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from clipforge.db.models.enums import ProjectStatus, SourceType

if TYPE_CHECKING:
    from clipforge.db.models.clip import ClipCandidate
    from clipforge.db.models.transcript import Transcript


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_status_created_at", "status", "created_at"),)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[SourceType] = mapped_column(
        SAEnum(SourceType, native_enum=False, length=16, name="source_type"),
        default=SourceType.YOUTUBE,
        nullable=False,
    )
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus, native_enum=False, length=32, name="project_status"),
        default=ProjectStatus.CREATED,
        nullable=False,
        index=True,
    )

    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Rutas relativas a STORAGE_PATH (el storage debe poder reubicarse).
    source_video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Id de la tarea Celery en curso, para poder cancelar o inspeccionar.
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    transcript: Mapped[Transcript | None] = relationship(
        back_populates="project", cascade="all, delete-orphan", uselist=False
    )
    candidates: Mapped[list[ClipCandidate]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ClipCandidate.score.desc()",
    )

    def __repr__(self) -> str:
        return f"<Project {self.id} status={self.status} title={self.title!r}>"
