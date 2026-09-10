"""Schemas de candidatos a clip."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from sqlalchemy import inspect as sa_inspect

from clipforge.db.models.enums import CandidateSource, CandidateStatus

#: Tope de un clip creado a mano. Los límites del perfil (MIN/MAX_CLIP_DURATION)
#: NO se aplican aquí: si el usuario decide que su clip dura ocho segundos, dura
#: ocho segundos. Esto solo evita que un arrastre accidental sobre la línea de
#: tiempo mande media hora de vídeo al codificador.
MAX_MANUAL_CLIP_SECONDS = 600.0

#: Un clip por debajo de esto no da tiempo ni a verse.
MIN_MANUAL_CLIP_SECONDS = 1.0


class ClipScoreBreakdown(BaseModel):
    """Desglose de viralidad. El total es la suma de estas dimensiones.

    Los nombres son los de la rúbrica de contenido hablado. En un proyecto con
    perfil visual las mismas columnas guardan otras dimensiones (`payoff` en
    lugar de `curiosity`, etc.); el frontend las etiqueta según el perfil.
    """

    hook: float | None
    curiosity: float | None
    emotion: float | None
    clarity: float | None
    value: float | None
    shareability: float | None
    duration: float | None


class ClipCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    rank: int | None
    status: CandidateStatus
    source: CandidateSource

    start_time: float
    end_time: float
    start_segment_index: int | None
    end_segment_index: int | None

    title: str
    #: Los otros títulos que propuso el redactor. Cambiar a uno de ellos es
    #: un PATCH, no otra llamada al modelo: ya están pagados y validados.
    title_variants: list[str]
    hook: str | None
    #: Descripción para la caja de YouTube, sin el crédito al canal: ese se
    #: compone al exportar, donde se conoce la URL de origen.
    description: str | None
    #: Etiquetas sin almohadilla; la primera es siempre "shorts".
    hashtags: list[str]
    reason: str | None
    transcript_excerpt: str | None
    error_message: str | None

    score: float
    #: None en un candidato que no ha juzgado ningún modelo: los que salen de
    #: las señales o los que ha recortado el usuario.
    scores: ClipScoreBreakdown | None
    #: Id del clip ya renderizado, si lo tiene.
    clip_id: uuid.UUID | None
    #: Encuadre corregido a mano. None = manda el automático.
    crop_x: int | None
    #: Encuadre con el que se generó el fichero que hay ahora, para poder
    #: pintarlo sobre el vídeo en el editor.
    rendered_crop_x: int | None
    rendered_crop_width: int | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration(self) -> float:
        return round(self.end_time - self.start_time, 2)

    @classmethod
    def from_model(cls, candidate: object) -> ClipCandidateRead:
        """Construye la vista agrupando las dimensiones de puntuación."""
        breakdown = (
            ClipScoreBreakdown(
                hook=candidate.hook_score,  # type: ignore[attr-defined]
                curiosity=candidate.curiosity_score,  # type: ignore[attr-defined]
                emotion=candidate.emotion_score,  # type: ignore[attr-defined]
                clarity=candidate.clarity_score,  # type: ignore[attr-defined]
                value=candidate.value_score,  # type: ignore[attr-defined]
                shareability=candidate.shareability_score,  # type: ignore[attr-defined]
                duration=candidate.duration_score,  # type: ignore[attr-defined]
            )
            if candidate.hook_score is not None  # type: ignore[attr-defined]
            else None
        )
        clip = _loaded_clip(candidate)

        return cls(
            id=candidate.id,  # type: ignore[attr-defined]
            project_id=candidate.project_id,  # type: ignore[attr-defined]
            rank=candidate.rank,  # type: ignore[attr-defined]
            status=candidate.status,  # type: ignore[attr-defined]
            source=candidate.source,  # type: ignore[attr-defined]
            start_time=candidate.start_time,  # type: ignore[attr-defined]
            end_time=candidate.end_time,  # type: ignore[attr-defined]
            start_segment_index=candidate.start_segment_index,  # type: ignore[attr-defined]
            end_segment_index=candidate.end_segment_index,  # type: ignore[attr-defined]
            title=candidate.title,  # type: ignore[attr-defined]
            # NULL y lista vacía son lo mismo para quien las pinta, y una
            # lista siempre presente le ahorra al frontend un caso más.
            title_variants=list(candidate.title_variants or []),  # type: ignore[attr-defined]
            hook=candidate.hook,  # type: ignore[attr-defined]
            description=candidate.description,  # type: ignore[attr-defined]
            hashtags=list(candidate.hashtags or []),  # type: ignore[attr-defined]
            reason=candidate.reason,  # type: ignore[attr-defined]
            transcript_excerpt=candidate.transcript_excerpt,  # type: ignore[attr-defined]
            error_message=candidate.error_message,  # type: ignore[attr-defined]
            score=candidate.score,  # type: ignore[attr-defined]
            scores=breakdown,
            clip_id=clip.id if clip is not None else None,  # type: ignore[attr-defined]
            crop_x=candidate.crop_x,  # type: ignore[attr-defined]
            rendered_crop_x=clip.crop_x if clip is not None else None,  # type: ignore[attr-defined]
            rendered_crop_width=(
                clip.crop_width if clip is not None else None  # type: ignore[attr-defined]
            ),
        )


def _loaded_clip(candidate: object) -> object | None:
    """Clip generado, solo si ya está cargado en la sesión.

    Tocar la relación sin más dispararía una carga perezosa síncrona, y dentro
    del contexto asíncrono de FastAPI eso revienta con `MissingGreenlet`. Pasa
    justo después de crear un candidato: la fila es nueva y la relación no se
    ha cargado nunca, aunque el repositorio la pida con `selectinload`.
    """
    state = sa_inspect(candidate, raiseerr=False)
    if state is None or "generated_clip" in state.unloaded:
        return None
    return getattr(candidate, "generated_clip", None)


class ClipCandidateCreate(BaseModel):
    """Cuerpo de POST /projects/{id}/candidates: un clip recortado a mano."""

    start_time: float = Field(..., ge=0, description="Segundo de entrada en el vídeo original")
    end_time: float = Field(..., gt=0, description="Segundo de salida en el vídeo original")
    title: str = Field(
        "Clip manual",
        min_length=1,
        max_length=300,
        description="Nombre del clip; se usa para el fichero exportado",
    )

    @model_validator(mode="after")
    def _check_span(self) -> ClipCandidateCreate:
        _assert_valid_span(self.start_time, self.end_time)
        return self


class ClipCandidateUpdate(BaseModel):
    """Cuerpo de PATCH /candidates/{id}. Todo opcional: es un ajuste."""

    start_time: float | None = Field(None, ge=0)
    end_time: float | None = Field(None, gt=0)
    title: str | None = Field(None, min_length=1, max_length=300)
    hook: str | None = Field(
        None,
        max_length=500,
        description=(
            "Frase que se escribe sobre el vídeo en los primeros segundos. "
            "Cadena vacía para quitarla."
        ),
    )
    status: CandidateStatus | None = Field(
        None, description="Para descartar un candidato sin borrarlo (REJECTED)"
    )
    crop_x: int | None = Field(
        None,
        ge=-1,
        description=(
            "Posición horizontal del recorte 9:16 en píxeles del original. "
            "-1 devuelve el encuadre al automático."
        ),
    )

    @model_validator(mode="after")
    def _check_span(self) -> ClipCandidateUpdate:
        # Solo se valida cuando llegan los dos extremos: si solo se mueve uno,
        # el router lo comprueba contra el valor que ya tiene guardado.
        if self.start_time is None or self.end_time is None:
            return self
        _assert_valid_span(self.start_time, self.end_time)
        return self


def _assert_valid_span(start: float, end: float) -> None:
    """Comprobaciones comunes de un rango de clip.

    Raises:
        ValueError: pydantic la convierte en un 422 con este mensaje.
    """
    span = end - start
    if span < MIN_MANUAL_CLIP_SECONDS:
        raise ValueError(
            f"El clip dura {span:.1f}s: la salida debe ir al menos "
            f"{MIN_MANUAL_CLIP_SECONDS:g}s por detrás de la entrada"
        )
    if span > MAX_MANUAL_CLIP_SECONDS:
        raise ValueError(f"El clip dura {span:.0f}s y el máximo son {MAX_MANUAL_CLIP_SECONDS:.0f}s")
