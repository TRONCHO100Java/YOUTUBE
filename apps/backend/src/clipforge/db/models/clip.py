"""Candidatos a clip (salida del LLM) y clips renderizados (salida de FFmpeg)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from clipforge.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from clipforge.db.models.enums import CandidateSource, CandidateStatus

if TYPE_CHECKING:
    from clipforge.db.models.project import Project


class ClipCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Momento propuesto por el analisis de IA, con su desglose de puntuacion."""

    __tablename__ = "clip_candidates"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="end_after_start"),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        Index("ix_clip_candidates_project_score", "project_id", "score"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Timestamps derivados de TranscriptSegment reales, nunca inventados por el LLM.
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    start_segment_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_segment_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Los otros titulos que propuso el redactor, ya validados. Se guardan
    #: aunque no se usen: la llamada al modelo ya esta pagada, y tenerlos
    #: aqui convierte "no me gusta este titulo" en un clic en el editor.
    title_variants: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    #: Descripcion para la caja de YouTube, solo la parte que describe el
    #: clip. El credito al canal original se compone al exportar, porque lo
    #: sabe el sistema y no el modelo.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Etiquetas sin almohadilla. La primera es siempre "shorts".
    hashtags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    #: Desglose del juez. En JSONB y no en columnas porque su rubrica tiene
    #: catorce dimensiones y va a cambiar: es la parte del sistema que mas se
    #: va a iterar, y una migracion por peso ajustado no tiene sentido.
    judge_scores: Mapped[dict[str, int] | None] = mapped_column(JSONB, nullable=True)

    # Desglose de viralidad (total = 100).
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    hook_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-20
    curiosity_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-20
    emotion_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-15
    clarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-15
    value_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-15
    shareability_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-10
    duration_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-5

    status: Mapped[CandidateStatus] = mapped_column(
        SAEnum(CandidateStatus, native_enum=False, length=16, name="candidate_status"),
        default=CandidateStatus.PENDING,
        nullable=False,
    )
    #: De donde salio el candidato. Un reprocesado sustituye lo que produjo la
    #: maquina (AI y SIGNAL) pero nunca borra lo que ha recortado una persona.
    source: Mapped[CandidateSource] = mapped_column(
        SAEnum(CandidateSource, native_enum=False, length=16, name="candidate_source"),
        default=CandidateSource.AI,
        server_default=CandidateSource.AI.value,
        nullable=False,
        index=True,
    )
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Posición horizontal del recorte 9:16, en píxeles del vídeo original.
    #: Solo se rellena cuando el usuario corrige el encuadre a mano; con NULL
    #: manda el encuadre automático, que se recalcula en cada render.
    crop_x: Mapped[int | None] = mapped_column(Integer, nullable=True)

    project: Mapped[Project] = relationship(back_populates="candidates")
    generated_clip: Mapped[GeneratedClip | None] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", uselist=False
    )

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    def __repr__(self) -> str:
        return f"<ClipCandidate {self.id} score={self.score} {self.title!r}>"


class GeneratedClip(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """MP4 vertical final producido para un candidato."""

    __tablename__ = "generated_clips"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clip_candidates.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    #: Rutas relativas a STORAGE_PATH.
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filesize_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    has_burned_subtitles: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    encoder: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Encuadre con el que se genero REALMENTE este fichero, en pixeles del
    #: original. Es lo que el editor pinta sobre el video para que se vea que
    #: parte se quedo dentro, y desde donde se corrige.
    crop_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crop_width: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Id del video en YouTube, si se ha subido. Es la unica prueba de que
    #: este fichero salio de aqui, y la llave con la que se le piden luego las
    #: vistas: sin el, el bucle de rendimiento no tiene por donde empezar.
    youtube_video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Con que privacidad quedo. Importa decirlo: un proyecto de API sin
    #: auditar sube SIEMPRE en privado, y creer que algo esta publicado cuando
    #: no lo esta es peor que no haberlo subido.
    privacy_status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    #: Rendimiento real, releido cada dia. Es lo unico que puede decir si la
    #: rubrica de siete dimensiones acierta o es decoracion.
    view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stats_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    candidate: Mapped[ClipCandidate] = relationship(back_populates="generated_clip")

    def __repr__(self) -> str:
        return f"<GeneratedClip {self.id} {self.width}x{self.height} {self.file_path}>"
