"""Contrato de análisis de clips.

Un `ClipAnalyzer` recibe una ventana de segmentos y propone momentos con
potencial viral. Aislarlo permite cambiar de proveedor (OpenAI, Anthropic,
Ollama) sin tocar el pipeline, y probar las fases siguientes sin gastar tokens.

Regla central: **el modelo elige segmentos, no timestamps**. Devuelve índices de
`TranscriptSegment` y el backend deriva los tiempos exactos, de modo que es
imposible que se invente un instante que no existe en la transcripción.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AnalysisSegment:
    """Segmento tal y como se le presenta al modelo."""

    index: int
    start: float
    end: float
    text: str


@dataclass(frozen=True, slots=True)
class AnalysisWindow:
    """Bloque de transcripción que se analiza en una sola llamada al modelo."""

    number: int
    segments: list[AnalysisSegment]

    @property
    def first_index(self) -> int:
        return self.segments[0].index

    @property
    def last_index(self) -> int:
        return self.segments[-1].index

    @property
    def start(self) -> float:
        return self.segments[0].start

    @property
    def end(self) -> float:
        return self.segments[-1].end

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class ClipScores:
    """Desglose de viralidad. El total es la suma, calculada por nosotros."""

    hook: float  # 0-20
    curiosity: float  # 0-20
    emotion: float  # 0-15
    clarity: float  # 0-15
    value: float  # 0-15
    shareability: float  # 0-10
    duration: float  # 0-5

    @property
    def total(self) -> float:
        """Suma de las dimensiones, acotada a 0-100.

        Se calcula aquí en lugar de pedírsela al modelo: los LLM se equivocan
        sumando y un total incoherente con su desglose es imposible de depurar.
        """
        raw = (
            self.hook
            + self.curiosity
            + self.emotion
            + self.clarity
            + self.value
            + self.shareability
            + self.duration
        )
        return round(max(0.0, min(100.0, raw)), 2)


@dataclass(frozen=True, slots=True)
class ClipSuggestion:
    """Momento propuesto por el modelo, ya validado contra segmentos reales."""

    start_segment: int
    end_segment: int
    start_time: float
    end_time: float
    title: str
    hook: str | None
    reason: str | None
    scores: ClipScores
    transcript_excerpt: str | None = None

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def score(self) -> float:
        return self.scores.total


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """Metadatos del vídeo que ayudan al modelo a juzgar el contenido."""

    title: str | None = None
    author: str | None = None
    language: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


class ClipAnalyzer(ABC):
    """Propone momentos con potencial viral a partir de una ventana."""

    #: Nombre del proveedor, para logs y trazabilidad.
    provider: str = "unknown"

    @abstractmethod
    def analyze_window(
        self, window: AnalysisWindow, context: AnalysisContext
    ) -> list[ClipSuggestion]:
        """Analiza una ventana y devuelve sus mejores momentos.

        Raises:
            ExternalToolError: si el proveedor falla o responde algo inusable.
        """
