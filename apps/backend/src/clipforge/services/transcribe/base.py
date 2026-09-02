"""Contrato de transcripción.

Aislarlo permite cambiar de motor (faster-whisper, WhisperX, un servicio remoto)
sin tocar el pipeline, y probar las fases posteriores con transcripciones fijas.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Word:
    """Palabra con sus tiempos. Base de los subtítulos palabra a palabra."""

    word: str
    start: float
    end: float
    probability: float | None = None

    def to_dict(self) -> dict[str, float | str | None]:
        return {
            "word": self.word,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "probability": round(self.probability, 3) if self.probability is not None else None,
        }


@dataclass(frozen=True, slots=True)
class Segment:
    """Fragmento de transcripción.

    `index` es el identificador estable que se le ofrece al LLM en la FASE 4:
    el modelo elige segmentos y el backend deriva los timestamps exactos, de
    modo que nunca puede inventárselos.
    """

    index: int
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    language: str | None
    language_probability: float | None
    duration: float | None
    model_name: str
    segments: list[Segment]

    @property
    def full_text(self) -> str:
        return " ".join(segment.text.strip() for segment in self.segments if segment.text.strip())


class Transcriber(ABC):
    """Convierte un fichero de audio en segmentos con timestamps."""

    @abstractmethod
    def transcribe(self, audio_path: Path, *, language: str | None = None) -> TranscriptionResult:
        """Transcribe `audio_path`. `language` fuerza el idioma; None lo detecta."""
