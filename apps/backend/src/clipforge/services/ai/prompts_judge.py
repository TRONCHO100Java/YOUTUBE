"""Prompts del juez.

Separados de los del detector porque el trabajo es opuesto. El detector barre
el vídeo sin haber visto nada más y propone; el juez ve todos los candidatos
juntos y **compara**. Pedirle a uno solo las dos cosas es lo que hacía que un
momento correcto de una ventana floja acabara publicándose por delante de uno
bueno de otra.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from clipforge.services.ai.base import AnalysisContext, ClipSuggestion
from clipforge.services.ai.prompts import keywords_line, timestamp

if TYPE_CHECKING:
    from clipforge.services.ai.judge import Criterion

JUDGE_INTRO = """\
Eres el editor jefe de un canal de YouTube Shorts. Recibes una lista de \
momentos que otro editor ha sacado de un vídeo largo y decides cuáles se \
publican.

No los propusiste tú y no tienes que ser amable con ellos. Tu trabajo es \
comparar y ser exigente: publicar cinco cosas mediocres hace más daño al canal \
que publicar dos buenas."""

RULES = (
    "Un Short se pierde o se gana en el PRIMER SEGUNDO. Si el momento no "
    "arranca ya en lo interesante, la nota de gancho es baja por muy bueno que "
    "sea lo que viene después.",
    "Un momento sin remate no es un clip: es un trozo de conversación. Si no "
    "pasa nada que cierre, la nota de remate es baja.",
    "El espectador NO ha visto el vídeo original y no lo va a ver. Si hay que "
    "saber algo de antes para entenderlo, eso son espectadores perdidos.",
    "Castiga sin piedad lo que retrasa lo interesante: saludos, "
    "presentaciones, frases empezadas a la mitad, repeticiones, muletillas y "
    "silencios.",
    "Un momento largo no es mejor por ser largo. Si lo bueno son quince "
    "segundos, lo demás sobra y se nota en la nota de tiempo muerto.",
    "No infles las notas. Si de diez candidatos solo dos valen, dilo con los "
    "números: para eso están.",
)


def build_judge_system_prompt(criteria: Sequence[Criterion], *, minimum: int, maximum: int) -> str:
    """Rúbrica del juez, generada desde los criterios.

    Se genera y no se escribe a mano por lo mismo que el esquema: si se toca un
    peso, el prompt cambia con él y no pueden quedar desincronizados.
    """
    merits = "\n".join(
        f"- {c.key} 0-{c.maximum}: {c.description}." for c in criteria if not c.penalty
    )
    penalties = "\n".join(
        f"- {c.key} 0-{c.maximum}: {c.description}." for c in criteria if c.penalty
    )
    numbered = "\n".join(f"{index}. {rule}" for index, rule in enumerate(RULES, start=1))

    return f"""\
{JUDGE_INTRO}

REGLAS
{numbered}

LO QUE SUMA (entero dentro de cada rango; no calcules el total, ya lo hace el sistema)
{merits}

LO QUE RESTA (cuánto de esto hay en el momento; se descuenta de la nota)
{penalties}

La nota va de 0 a {maximum} menos los descuentos. Un clip que no llegue a \
{minimum} no se publica, así que no le pongas {minimum} a algo que no \
publicarías tú.

Devuelve una entrada por cada clip que se te ha dado, con su número."""


def build_judge_user_prompt(
    candidates: Sequence[ClipSuggestion], context: AnalysisContext, *, offset: int = 0
) -> str:
    """Presenta los candidatos numerados, con lo que se sabe de cada uno.

    Se le da la duración porque forma parte del juicio: el mismo contenido en
    veinte segundos y en ochenta no vale lo mismo en Shorts.
    """
    header = [
        f"Vídeo: {context.title}" if context.title else None,
        f"Canal: {context.author}" if context.author else None,
        keywords_line(context),
    ]

    lines: list[str] = []
    for number, clip in enumerate(candidates, start=1):
        lines.append(
            f"CLIP {number} | {timestamp(clip.start_time)} - {timestamp(clip.end_time)}"
            f" | {round(clip.duration)} s"
        )
        if clip.title:
            lines.append(f"  Lo que propone: {clip.title}")
        if clip.reason:
            lines.append(f"  Por qué lo eligió: {clip.reason.strip()}")
        if clip.transcript_excerpt:
            lines.append(f"  Se dice: {clip.transcript_excerpt.strip()[:700]}")
        lines.append("")

    position = f" (son del {offset + 1} en adelante del vídeo)" if offset else ""

    return "\n".join(
        [
            *[item for item in header if item],
            "",
            f"Tienes {len(candidates)} candidatos{position}. Púntualos todos.",
            "",
            *lines,
        ]
    )
