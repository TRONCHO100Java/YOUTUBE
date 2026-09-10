"""Entidad Project: una URL de origen y su recorrido por el pipeline."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clipforge.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from clipforge.db.models.enums import ContentProfile, ProjectStatus, SourceType

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

    #: Palabras que el usuario aporta al crear el proyecto: de que va el video,
    #: quien sale, como se le busca. El pipeline no las puede deducir —el titulo
    #: de YouTube rara vez nombra a los streamers que aparecen— y son justo lo
    #: que hace que un titulo compita en busqueda. Se guardan tal y como se
    #: escriben; separarlas en terminos es cosa de quien las usa.
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Canal propio al que van los clips de este proyecto. Se hereda del
    #: canal vigilado que lo trajo, y se guarda AQUI y no se deduce cada vez
    #: para que siga siendo cierto aunque luego se borre aquel.
    publish_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("publish_channels.id", ondelete="SET NULL"), nullable=True
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Id de la tarea Celery en curso, para poder cancelar o inspeccionar.
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: Tipo de contenido detectado tras transcribir. Decide rubrica y duraciones.
    content_profile: Mapped[ContentProfile | None] = mapped_column(
        SAEnum(ContentProfile, native_enum=False, length=16, name="content_profile"),
        nullable=True,
    )
    #: Fraccion del video con habla real. Es el dato que decide el perfil, y el
    #: que explica por que un video se ha tratado como visual.
    speech_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Senales no verbales del video (energia, cortes, movimiento y bloques).
    #: Se guarda como JSONB y no en tablas propias porque es una vista derivada
    #: —se puede recalcular con ffmpeg— que solo se consume entera: la lee el
    #: analisis y la pinta la linea de tiempo del editor.
    signals: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

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
