"""Perfiles de contenido: qué rúbrica y qué duraciones aplican a cada vídeo.

Un pódcast y una recopilación de comedia física no se juzgan con los mismos
criterios. La rúbrica original premiaba "enseñar algo" y exigía que el gancho
fuera una cita textual del audio; sobre un gag visual eso reparte cero puntos
en la mitad del baremo, por bueno que sea el momento.

Cada perfil declara sus dimensiones. La columna donde se guarda cada una es fija
(la tabla `clip_candidates` tiene siete columnas de puntuación), pero el nombre
que ve el modelo y su máximo cambian con el perfil. Así se puede cambiar de
rúbrica sin migrar la base de datos y sin romper los proyectos ya analizados.
"""

from __future__ import annotations

from dataclasses import dataclass

from clipforge.core.config import settings
from clipforge.core.logging import get_logger
from clipforge.db.models.enums import ContentProfile

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Dimension:
    """Una dimensión de la puntuación.

    `key` es como la llama el modelo en su respuesta; `column` es dónde acaba
    en base de datos. Separarlos permite que "payoff" y "curiosity" compartan
    columna sin que el modelo vea nunca un nombre que no le encaja.
    """

    key: str
    column: str
    maximum: int
    description: str

    @property
    def field_name(self) -> str:
        """Nombre del campo en el JSON que devuelve el modelo."""
        return f"{self.key}_score"


@dataclass(frozen=True, slots=True)
class ProfileRules:
    """Todo lo que cambia entre un tipo de contenido y otro."""

    profile: ContentProfile
    min_duration: int
    max_duration: int
    target_duration: int
    dimensions: tuple[Dimension, ...]
    #: Reglas específicas que se añaden al prompt del sistema.
    guidance: tuple[str, ...]
    #: Los subtítulos incrustados solo tienen sentido si hay algo que subtitular.
    burn_subtitles: bool

    @property
    def total_maximum(self) -> int:
        return sum(dimension.maximum for dimension in self.dimensions)


TALKING_DIMENSIONS: tuple[Dimension, ...] = (
    Dimension("hook", "hook", 20, "fuerza de los primeros segundos para frenar el scroll"),
    Dimension("curiosity", "curiosity", 20, "cuánta necesidad de seguir viendo genera"),
    Dimension("emotion", "emotion", 15, "intensidad emocional (sorpresa, indignación, humor)"),
    Dimension("clarity", "clarity", 15, "se entiende solo, sin contexto previo"),
    Dimension("value", "value", 15, "enseña algo, resuelve algo o aporta información útil"),
    Dimension("shareability", "shareability", 10, "ganas de compartirlo, citarlo o discutirlo"),
    Dimension("duration", "duration", 5, "lo cerca que queda de la duración ideal"),
)

#: Rúbrica visual. Reparte los mismos 100 puntos entre lo que sí se puede juzgar
#: sin diálogo, y carga la mano en el remate: es lo único que decide si un gag
#: funciona o no.
VISUAL_DIMENSIONS: tuple[Dimension, ...] = (
    Dimension("setup", "hook", 20, "la premisa se entiende en los primeros segundos"),
    Dimension(
        "payoff", "curiosity", 25, "fuerza del remate: lo inesperado o absurdo del desenlace"
    ),
    Dimension("reaction", "emotion", 15, "reacciones visibles de los protagonistas o del público"),
    Dimension("universality", "clarity", 15, "se entiende sin saber el idioma ni oír el audio"),
    Dimension("pacing", "value", 15, "ritmo sin tiempos muertos entre la premisa y el remate"),
    Dimension("duration", "duration", 10, "lo cerca que queda de la duración ideal"),
)


def rules_for(profile: ContentProfile) -> ProfileRules:
    """Reglas del perfil, con las duraciones que haya configuradas."""
    if profile is ContentProfile.VISUAL:
        return ProfileRules(
            profile=ContentProfile.VISUAL,
            min_duration=settings.visual_min_clip_duration,
            max_duration=settings.visual_max_clip_duration,
            target_duration=settings.visual_target_clip_duration,
            dimensions=VISUAL_DIMENSIONS,
            guidance=(
                "El vídeo se juzga por lo que OCURRE, no por lo que se dice. "
                "Puede no haber diálogo alguno, y eso no es un problema.",
                "Un clip debe contener una situación completa: se plantea algo y "
                "termina en un remate. Cortar antes del remate lo estropea.",
                "No cites diálogo: puede no existir o estar en otro idioma. Describe la acción.",
                "Prefiere momentos que se entiendan con el sonido quitado.",
            ),
            burn_subtitles=False,
        )

    return ProfileRules(
        profile=ContentProfile.TALKING,
        min_duration=settings.min_clip_duration,
        max_duration=settings.max_clip_duration,
        target_duration=settings.target_clip_duration,
        dimensions=TALKING_DIMENSIONS,
        guidance=(
            "El clip tiene que entenderse SIN haber visto lo anterior. Si empieza "
            "a mitad de una idea o depende de algo dicho antes, no sirve.",
            "Empieza en un momento fuerte: una afirmación rotunda, una pregunta, "
            "una confesión o un dato sorprendente. No empieces con relleno.",
            "Termina en un cierre natural, no a mitad de frase.",
            "El gancho debe ser una cita textual del propio segmento inicial.",
        ),
        burn_subtitles=settings.burn_subtitles,
    )


def detect_profile(
    *,
    speech_seconds: float,
    text_characters: int,
    video_duration: float,
) -> ContentProfile:
    """Decide el perfil a partir de cuánta habla real trae la transcripción.

    Dos criterios, y basta con que falle uno para tratar el vídeo como visual:

    - **Fracción de habla.** Segundos con voz sobre segundos de vídeo.
    - **Densidad de texto.** Caracteres por minuto. Hace falta como segundo
      criterio porque en un vídeo muy corto tres palabras sueltas pueden dar
      una fracción de habla engañosamente alta.

    Con `CONTENT_PROFILE` distinto de "auto" no se detecta nada: manda el ajuste.
    """
    configured = settings.content_profile
    if configured == "talking":
        return ContentProfile.TALKING
    if configured == "visual":
        return ContentProfile.VISUAL

    if video_duration <= 0:
        return ContentProfile.TALKING

    ratio = speech_seconds / video_duration
    per_minute = text_characters / (video_duration / 60.0)
    visual = ratio < settings.visual_speech_ratio or per_minute < settings.visual_chars_per_minute

    profile = ContentProfile.VISUAL if visual else ContentProfile.TALKING
    logger.info(
        "ai.profile_detected",
        profile=profile.value,
        speech_ratio=round(ratio, 4),
        chars_per_minute=round(per_minute, 1),
    )
    return profile
