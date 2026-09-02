"""Schemas de candidatos a clip."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, computed_field

from clipforge.db.models.enums import CandidateStatus


class ClipScoreBreakdown(BaseModel):
    """Desglose de viralidad. El total es la suma de estas dimensiones."""

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

    start_time: float
    end_time: float
    start_segment_index: int | None
    end_segment_index: int | None

    title: str
    hook: str | None
    reason: str | None
    transcript_excerpt: str | None

    score: float
    scores: ClipScoreBreakdown

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration(self) -> float:
        return round(self.end_time - self.start_time, 2)

    @classmethod
    def from_model(cls, candidate: object) -> ClipCandidateRead:
        """Construye la vista agrupando las dimensiones de puntuación."""
        return cls(
            id=candidate.id,  # type: ignore[attr-defined]
            project_id=candidate.project_id,  # type: ignore[attr-defined]
            rank=candidate.rank,  # type: ignore[attr-defined]
            status=candidate.status,  # type: ignore[attr-defined]
            start_time=candidate.start_time,  # type: ignore[attr-defined]
            end_time=candidate.end_time,  # type: ignore[attr-defined]
            start_segment_index=candidate.start_segment_index,  # type: ignore[attr-defined]
            end_segment_index=candidate.end_segment_index,  # type: ignore[attr-defined]
            title=candidate.title,  # type: ignore[attr-defined]
            hook=candidate.hook,  # type: ignore[attr-defined]
            reason=candidate.reason,  # type: ignore[attr-defined]
            transcript_excerpt=candidate.transcript_excerpt,  # type: ignore[attr-defined]
            score=candidate.score,  # type: ignore[attr-defined]
            scores=ClipScoreBreakdown(
                hook=candidate.hook_score,  # type: ignore[attr-defined]
                curiosity=candidate.curiosity_score,  # type: ignore[attr-defined]
                emotion=candidate.emotion_score,  # type: ignore[attr-defined]
                clarity=candidate.clarity_score,  # type: ignore[attr-defined]
                value=candidate.value_score,  # type: ignore[attr-defined]
                shareability=candidate.shareability_score,  # type: ignore[attr-defined]
                duration=candidate.duration_score,  # type: ignore[attr-defined]
            ),
        )
