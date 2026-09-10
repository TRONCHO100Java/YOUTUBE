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
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from clipforge.db.models.enums import CandidateSource, ContentProfile

if TYPE_CHECKING:
    from clipforge.services.signals.base import MomentBlock


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
    """Momento propuesto por el modelo, ya validado contra tiempos reales.

    Los índices de segmento son opcionales: un candidato salido del análisis
    visual se apoya en un bloque de fotogramas, no en la transcripción, y no
    tiene ningún segmento al que referirse.
    """

    start_segment: int | None
    end_segment: int | None
    start_time: float
    end_time: float
    title: str
    hook: str | None
    reason: str | None
    #: Desglose de la rúbrica. Es None en un candidato salido solo de señales:
    #: ahí no hay ninguna dimensión que puntuar, y rellenar el desglose con
    #: ceros haría creer que un modelo lo ha valorado y le ha dado cero.
    scores: ClipScores | None
    transcript_excerpt: str | None = None
    #: Las otras variantes de título que propuso el redactor, ya validadas.
    #: Se guardan para poder cambiar de título con un clic desde el editor,
    #: sin volver a llamar a ningún modelo: la llamada ya se pagó.
    title_variants: tuple[str, ...] = ()
    #: Descripción para la caja de YouTube. Solo la parte que describe el
    #: clip: el crédito al canal original se compone al exportar, porque lo
    #: sabe el sistema y no el modelo.
    description: str | None = None
    #: Etiquetas, sin la almohadilla. Siempre incluyen "shorts".
    hashtags: tuple[str, ...] = ()
    #: Desglose del juez, si ha pasado por él. Va en un diccionario y no en
    #: columnas porque su rúbrica tiene catorce dimensiones y cambiará: es
    #: justo la parte del sistema que más se va a iterar.
    judge_scores: dict[str, int] | None = None
    #: Cómo se cuenta el clip: por dónde empieza de verdad, qué notas de
    #: contexto lleva y dónde cae el remate. Lo decide el montador.
    story: dict[str, Any] | None = None
    source: CandidateSource = CandidateSource.AI
    #: Puntuación directa, para los candidatos que no tienen desglose.
    signal_score: float | None = None

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def score(self) -> float:
        """Nota 0-100, venga del desglose de la rúbrica o de las señales."""
        if self.scores is not None:
            return self.scores.total
        return round(max(0.0, min(100.0, self.signal_score or 0.0)), 2)

    @property
    def hook_score(self) -> float:
        """Fuerza del gancho, para desempatar en el ranking."""
        return self.scores.hook if self.scores is not None else 0.0


@dataclass(frozen=True, slots=True)
class TitleBrief:
    """Un clip ya elegido, tal y como se le presenta al redactor de títulos.

    Es deliberadamente pobre: número, tiempos y lo poco que se sabe del clip.
    El titulador no recibe la puntuación ni la rúbrica porque no tiene que
    volver a juzgar nada —eso ya está decidido— y enseñarle notas solo le
    daría motivos para discutirlas en lugar de escribir.
    """

    number: int
    start: float
    end: float
    #: Qué pasa en el clip. Sale del análisis: su título o su justificación.
    summary: str
    #: El texto que ya va escrito en pantalla, para que el título no lo repita.
    hook: str | None = None
    #: Lo que se dice, si el clip tiene diálogo aprovechable.
    excerpt: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """Metadatos del vídeo que ayudan al modelo a juzgar el contenido."""

    title: str | None = None
    author: str | None = None
    language: str | None = None
    #: Decide rúbrica y duraciones. Lo fija el pipeline tras transcribir.
    profile: ContentProfile = ContentProfile.TALKING
    #: Términos que ha aportado el usuario: de qué va el vídeo y quién sale.
    #: Es lo único que el sistema no puede deducir mirando el vídeo, y lo que
    #: convierte un título descriptivo en uno que alguien busca.
    keywords: tuple[str, ...] = ()
    duration: float | None = None
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


class BlockAnalyzer(ABC):
    """Propone momentos a partir de fotogramas, sin transcripción.

    Es el contrato paralelo a `ClipAnalyzer` para los vídeos que no se pueden
    juzgar por lo que dicen. Se mantiene aparte en lugar de ampliar el otro
    porque las dos modalidades reciben cosas distintas —segmentos frente a
    bloques de imágenes— y mezclarlas obligaría a que cada implementación
    ignorase la mitad de sus argumentos.
    """

    #: Nombre del proveedor, para logs y trazabilidad.
    provider: str = "unknown"

    @abstractmethod
    def analyze_blocks(
        self,
        blocks: Sequence[MomentBlock],
        context: AnalysisContext,
        *,
        video_path: Path,
        workdir: Path,
    ) -> list[ClipSuggestion]:
        """Analiza bloques del vídeo y devuelve sus mejores momentos.

        Raises:
            ExternalToolError: si el proveedor falla o responde algo inusable.
        """
