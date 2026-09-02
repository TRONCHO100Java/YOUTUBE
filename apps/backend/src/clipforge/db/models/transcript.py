"""Transcripcion y sus segmentos temporales."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clipforge.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from clipforge.db.models.project import Project


class Transcript(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "transcripts"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    language_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    full_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)

    project: Mapped[Project] = relationship(back_populates="transcript")
    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.index",
    )

    def __repr__(self) -> str:
        return f"<Transcript {self.id} lang={self.language} segments={len(self.segments)}>"


class TranscriptSegment(UUIDPrimaryKeyMixin, Base):
    """Un segmento de Whisper. Los timestamps de los clips SIEMPRE salen de aqui."""

    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("transcript_id", "index", name="uq_segment_index"),)

    transcript_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Indice 0-based dentro de la transcripcion; es el identificador estable que
    #: se le ofrece al LLM para que seleccione rangos sin inventarse timestamps.
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    #: Timestamps por palabra: [{"word": "hola", "start": 1.2, "end": 1.4}, ...]
    #: Preparado para subtitulos dinamicos palabra a palabra (fase futura).
    words: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    transcript: Mapped[Transcript] = relationship(back_populates="segments")

    def __repr__(self) -> str:
        return f"<Segment #{self.index} {self.start_time:.1f}-{self.end_time:.1f}>"
