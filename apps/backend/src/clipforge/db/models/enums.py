"""Enumeraciones del dominio.

Se persisten como VARCHAR con CHECK constraint (`native_enum=False`) en lugar de
tipos ENUM nativos de Postgres: anadir un estado nuevo es una migracion trivial.
"""

from __future__ import annotations

from enum import StrEnum


class ProjectStatus(StrEnum):
    CREATED = "CREATED"
    DOWNLOADING = "DOWNLOADING"
    TRANSCRIBING = "TRANSCRIBING"
    ANALYZING = "ANALYZING"
    GENERATING_CLIPS = "GENERATING_CLIPS"
    COMPLETED = "COMPLETED"
    #: El pipeline llegó hasta el final sin errores pero la IA no propuso nada.
    #: NO es un fallo: el vídeo y la transcripción se conservan y el proyecto
    #: queda listo para que el usuario corte a mano en el editor.
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        """Nada más va a ocurrir solo: o terminó, o espera a una persona."""
        return self in (
            ProjectStatus.COMPLETED,
            ProjectStatus.NEEDS_REVIEW,
            ProjectStatus.FAILED,
        )

    @property
    def is_running(self) -> bool:
        return not self.is_terminal and self is not ProjectStatus.CREATED


class SourceType(StrEnum):
    YOUTUBE = "YOUTUBE"
    UPLOAD = "UPLOAD"


class CandidateStatus(StrEnum):
    PENDING = "PENDING"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    RENDERING = "RENDERING"
    RENDERED = "RENDERED"
    FAILED = "FAILED"


class CandidateSource(StrEnum):
    """De dónde salió el candidato.

    Importa para el borrado: un reprocesado sustituye lo que produjo la máquina
    (`AI` y `SIGNAL`) pero **nunca** toca lo que ha recortado una persona.
    """

    #: Propuesto por el LLM a partir de la transcripción o de los fotogramas.
    AI = "AI"
    #: Derivado de las señales de audio/escena, sin que ninguna IA lo juzgue.
    SIGNAL = "SIGNAL"
    #: Recortado a mano en el editor.
    MANUAL = "MANUAL"

    @property
    def is_generated(self) -> bool:
        return self is not CandidateSource.MANUAL


class ContentProfile(StrEnum):
    """Tipo de contenido, que decide rúbrica y duraciones.

    Un pódcast y un vídeo de slapstick no se juzgan igual ni duran lo mismo.
    Se detecta a partir de cuánta habla real trae la transcripción.
    """

    #: Contenido hablado: pódcast, entrevista, charla. Se juzga por lo que dice.
    TALKING = "TALKING"
    #: Contenido visual: comedia física, retos, cocina. Se juzga por lo que pasa.
    VISUAL = "VISUAL"


#: Orden del pipeline, usado para calcular progreso en la UI.
PIPELINE_ORDER: tuple[ProjectStatus, ...] = (
    ProjectStatus.CREATED,
    ProjectStatus.DOWNLOADING,
    ProjectStatus.TRANSCRIBING,
    ProjectStatus.ANALYZING,
    ProjectStatus.GENERATING_CLIPS,
    ProjectStatus.COMPLETED,
)
