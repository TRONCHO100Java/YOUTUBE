"""Puerta de calidad: mirar el clip terminado antes de darlo por bueno.

Todo lo anterior comprueba **intenciones**: que el juez puntúe, que el montador
proponga, que el plan cuadre. Nada miraba el MP4 ya escrito. Y ahí es donde se
ven los fallos que ninguna de esas capas puede detectar, porque cada una hizo su
trabajo correctamente sobre datos que no eran los que creía.

Un clip de seis segundos, uno de dos minutos, uno mudo, uno sin una sola línea
de texto en pantalla: todos salen de un pipeline que no ha fallado en ningún
paso. Esto los caza.

Es una **puerta que avisa, no que borra**. Un clip con problemas se marca y se
publica igual si el usuario quiere: la alternativa —tirarlo— repetiría el error
de las primeras fases, cuando un análisis sin resultados marcaba el proyecto
como fallido y se perdía la descarga entera. Quien decide es quien mira.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from clipforge.core.logging import get_logger

logger = get_logger(__name__)


class Severity(StrEnum):
    """Cuánto importa lo que se ha encontrado."""

    #: Publicable, pero con algo que conviene saber.
    WARNING = "WARNING"
    #: Casi seguro que no debería publicarse así.
    PROBLEM = "PROBLEM"


@dataclass(frozen=True, slots=True)
class Issue:
    """Algo que le pasa al clip terminado."""

    code: str
    severity: Severity
    message: str


@dataclass(frozen=True, slots=True)
class ClipFacts:
    """Lo que se sabe del clip ya renderizado, medido y no supuesto."""

    duration: float
    width: int
    height: int
    filesize_bytes: int
    #: Subtítulos incrustados que lleva de verdad.
    cues: int
    has_hook: bool
    #: Cuánto se recortó respecto al rango original, en segundos.
    trimmed: float = 0.0
    #: Si el perfil del vídeo esperaba diálogo.
    expects_speech: bool = True


@dataclass(frozen=True, slots=True)
class QualityRules:
    """Los límites de lo publicable."""

    #: Por debajo de esto no da tiempo ni a entender qué pasa.
    min_duration: float = 8.0
    #: Por encima, deja de ser un Short y pasa a ser un vídeo corto.
    max_duration: float = 90.0
    #: Un fichero minúsculo suele ser un render que salió en negro.
    min_bytes: int = 200_000
    #: Relación de aspecto vertical esperada.
    aspect: float = 9 / 16
    #: Cuánto puede desviarse antes de considerarlo otra forma.
    aspect_tolerance: float = 0.02


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Veredicto sobre un clip."""

    issues: tuple[Issue, ...]

    @property
    def publishable(self) -> bool:
        """¿Se puede publicar sin mirarlo dos veces?"""
        return not any(issue.severity is Severity.PROBLEM for issue in self.issues)

    @property
    def summary(self) -> str:
        """Una línea con lo encontrado, para la interfaz y los logs."""
        if not self.issues:
            return "Sin problemas"
        return " · ".join(issue.message for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "publishable": self.publishable,
            "issues": [
                {"code": issue.code, "severity": str(issue.severity), "message": issue.message}
                for issue in self.issues
            ],
        }


def inspect_clip(facts: ClipFacts, rules: QualityRules | None = None) -> QualityReport:
    """Mira el clip terminado y devuelve lo que le pasa.

    El orden de las comprobaciones es el de gravedad: lo que hace el clip
    impublicable primero, lo que solo conviene saber después.
    """
    conf = rules or QualityRules()
    issues: list[Issue] = []

    if facts.duration < conf.min_duration:
        issues.append(
            Issue(
                "too_short",
                Severity.PROBLEM,
                f"Dura {facts.duration:.0f} s: no da tiempo a entender qué pasa",
            )
        )
    elif facts.duration > conf.max_duration:
        issues.append(
            Issue(
                "too_long",
                Severity.WARNING,
                f"Dura {facts.duration:.0f} s: para Shorts es largo",
            )
        )

    if facts.filesize_bytes < conf.min_bytes:
        # Un MP4 de cien kilobytes con quince segundos dentro es casi siempre
        # un render que salió en negro: pesa poco justamente porque no hay
        # imagen que codificar.
        issues.append(
            Issue(
                "suspiciously_small",
                Severity.PROBLEM,
                f"Pesa {facts.filesize_bytes / 1024:.0f} kB: puede haber salido en negro",
            )
        )

    if facts.height > 0:
        ratio = facts.width / facts.height
        if abs(ratio - conf.aspect) > conf.aspect_tolerance:
            issues.append(
                Issue(
                    "not_vertical",
                    Severity.PROBLEM,
                    f"Sale en {facts.width}x{facts.height}, que no es vertical",
                )
            )

    # Un clip sin una sola palabra escrita se publica mudo: ni subtítulos ni
    # gancho. Es el fallo más caro de todos porque el vídeo existe, se ve bien
    # y nadie entiende de qué va.
    if not facts.cues and not facts.has_hook:
        issues.append(
            Issue(
                "no_text",
                Severity.PROBLEM,
                "No lleva ni subtítulos ni gancho: se publica sin una palabra",
            )
        )
    elif facts.expects_speech and not facts.cues:
        issues.append(
            Issue(
                "no_subtitles",
                Severity.WARNING,
                "Es un clip hablado y no lleva subtítulos incrustados",
            )
        )

    report = QualityReport(issues=tuple(issues))
    if issues:
        logger.info(
            "quality.issues",
            publishable=report.publishable,
            codes=[issue.code for issue in issues],
        )
    return report
