"""Prompts del etiquetador.

A diferencia del juez o el montador, aquí no se pide criterio: se pide lectura.
Reconocer que un vídeo va de streamers y que sale Kai Cenat no es una opinión
sobre si el clip es bueno, y por eso este es el único de los cuatro modelos que
se defiende bien con un modelo pequeño.

El vocabulario de "qué clase de momento es" está **cerrado** a propósito. Con
la lista abierta cada clip inventa su propia etiqueta —"funny moment", "hilarious
bit", "comedy gold"— y entonces no agrupan nada, que era justo para lo que se
pusieron.
"""

from __future__ import annotations

from collections.abc import Sequence

from clipforge.services.ai.base import AnalysisContext, ClipSuggestion
from clipforge.services.ai.prompts import keywords_line, timestamp

#: Vocabulario cerrado de clases de momento. Elegidas para que un canal pueda
#: decir "yo publico reacciones" o "yo publico fails" y que eso signifique algo.
MOMENT_KINDS: tuple[str, ...] = (
    "reaccion",
    "fail",
    "gag",
    "reto",
    "consejo",
    "confesion",
    "discusion",
    "habilidad",
    "sorpresa",
)

TAGGING_INTRO = """\
Etiquetas clips de vídeo para poder repartirlos entre varios canales de Shorts.

No juzgas si el clip es bueno —eso ya está decidido— ni escribes nada de cara \
al público. Solo dices de qué va, para que luego se pueda agrupar."""


def build_tagging_system_prompt(*, max_people: int, max_topics: int) -> str:
    """Reglas del etiquetador."""
    kinds = ", ".join(MOMENT_KINDS)
    rules = [
        "El NICHO es el tema del canal en el que encajaría este clip: "
        "streamers, comedia, motivacion, deportes, gaming… Una sola palabra "
        "o dos, y la misma para clips parecidos.",
        f"Las PERSONAS son quién sale, por el nombre con el que se le busca. "
        f"Como mucho {max_people}. Si no sabes quién es, no lo inventes: deja "
        "la lista vacía.",
        f"Los TEMAS son de qué va el momento: el juego, el sitio, la actividad. "
        f"Como mucho {max_topics}.",
        f"La CLASE de momento tiene que ser una de estas y ninguna más: {kinds}.",
        "Sé consistente: dos clips del mismo vídeo con el mismo protagonista "
        "tienen que llevar el mismo nombre escrito igual.",
        "No te inventes nada. Si el clip no da para saber algo, deja ese campo "
        "vacío en lugar de rellenarlo.",
    ]
    numbered = "\n".join(f"{index}. {rule}" for index, rule in enumerate(rules, start=1))

    return f"""\
{TAGGING_INTRO}

REGLAS
{numbered}

Devuelve una entrada por cada clip, con su número."""


def build_tagging_user_prompt(clips: Sequence[ClipSuggestion], context: AnalysisContext) -> str:
    """Presenta los clips con lo poco que hace falta para etiquetarlos."""
    header = [
        f"Vídeo: {context.title}" if context.title else None,
        f"Canal: {context.author}" if context.author else None,
        keywords_line(context),
    ]

    lines: list[str] = []
    for number, clip in enumerate(clips, start=1):
        lines.append(f"CLIP {number} | {timestamp(clip.start_time)}")
        lines.append(f"  {clip.title}")
        if clip.reason:
            lines.append(f"  {clip.reason.strip()[:200]}")
        if clip.transcript_excerpt:
            lines.append(f"  Se dice: {clip.transcript_excerpt.strip()[:300]}")
        lines.append("")

    return "\n".join(
        [
            *[item for item in header if item],
            "",
            f"Son {len(clips)} clips del mismo vídeo. Etiquétalos todos.",
            "",
            *lines,
        ]
    )
