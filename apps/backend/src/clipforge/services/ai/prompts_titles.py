"""Prompts del titulado.

Viven aparte de `prompts.py` porque el trabajo es otro. En el análisis el
modelo está puntuando siete dimensiones y el título lo escribe de paso: sale
una etiqueta que describe la escena ("El salto del niño") en lugar de un
título que dé ganas de abrirla. Aquí no hay nada que juzgar —los clips ya
están elegidos— y toda la atención va al texto que se publica.

Las reglas que sí son comunes a las dos pasadas (idioma, palabras clave) se
importan de `prompts.py` en vez de reescribirse: dos copias de la misma regla
acaban divergiendo.
"""

from __future__ import annotations

from collections.abc import Sequence

from clipforge.services.ai.base import AnalysisContext, TitleBrief
from clipforge.services.ai.prompts import KEYWORDS_RULE, keywords_line, timestamp

TITLES_INTRO = """\
Eres un redactor de títulos para YouTube Shorts. Recibes clips ya elegidos de \
un vídeo, con lo que pasa en cada uno, y escribes el título con el que se van \
a publicar.

No juzgas los clips ni cambias sus tiempos: eso ya está decidido. Tu único \
trabajo es el texto."""


def build_titles_system_prompt(*, max_chars: int, variants: int, keywords: bool = False) -> str:
    """Reglas de redacción de títulos.

    Se piden varias variantes por clip a propósito. Un título puede salir
    largo, repetir el arranque de otro o caer en un tópico, y descartarlo
    costaría otra llamada entera si no hubiera recambio. Con variantes, el
    validador elige sin volver a preguntar.
    """
    rules = [
        f"Máximo {max_chars} caracteres por título, contando espacios. Apunta a unos "
        f"{max_chars * 2 // 3}: en el móvil el resto se corta.",
        "El remate va en las tres primeras palabras. Nadie llega al final de un "
        "título que empieza explicando el contexto.",
        "Nombra lo concreto: quién sale, qué objeto, qué sitio. Los nombres propios "
        "se buscan; los adjetivos no.",
        "Genera curiosidad SIN mentir. Prometer algo que el clip no enseña hace que "
        "lo cierren a los dos segundos, y eso hunde el vídeo.",
        "Prohibido: 'you won't believe', 'this is what happened', 'watch what "
        "happens', 'wait for it', 'must watch', 'gone wrong', y títulos genéricos "
        "tipo 'funny moment' o 'best clip'.",
        "Nada de TODO EN MAYÚSCULAS ni de emojis.",
        "El título NO puede repetir el gancho que ya va escrito en pantalla: se leen "
        "juntos, así que tienen que decir cosas distintas.",
        "Dos títulos de esta tanda no pueden empezar con las mismas palabras: son "
        "clips del mismo vídeo y se van a ver seguidos.",
        f"Escribe {variants} variantes por clip, con ángulos distintos: una que cite "
        "lo que se dice o se ve, otra en forma de pregunta, y otra que plantee lo "
        "que está en juego y su remate.",
        "TODO en INGLÉS, sea cual sea el idioma del vídeo.",
    ]
    if keywords:
        rules.append(KEYWORDS_RULE)

    numbered = "\n".join(f"{index}. {rule}" for index, rule in enumerate(rules, start=1))

    return f"""\
{TITLES_INTRO}

REGLAS
{numbered}

Devuelve una entrada por clip, con el número de clip que se te ha dado."""


def build_titles_user_prompt(clips: Sequence[TitleBrief], context: AnalysisContext) -> str:
    """Presenta los clips ya elegidos, numerados, con lo que se sabe de cada uno.

    Van todos en la misma petición, y no uno por uno, por dos razones: cuesta
    una llamada en lugar de cinco y, sobre todo, el modelo ve los demás
    mientras escribe cada título. Es la única forma de que cinco clips del
    mismo vídeo no acaben con cinco variaciones de la misma frase.
    """
    header = [
        f"Vídeo: {context.title}" if context.title else None,
        f"Canal: {context.author}" if context.author else None,
        keywords_line(context),
    ]

    lines: list[str] = []
    for clip in clips:
        lines.append(f"CLIP {clip.number} | {timestamp(clip.start)} - {timestamp(clip.end)}")
        lines.append(f"  Lo que pasa: {clip.summary}")
        if clip.hook:
            lines.append(f"  Gancho que ya va escrito en pantalla: {clip.hook}")
        if clip.excerpt:
            lines.append(f"  Se dice: {clip.excerpt}")
        lines.append("")

    return "\n".join(
        [
            *[item for item in header if item],
            "",
            f"Son {len(clips)} clips del mismo vídeo. Titúlalos todos.",
            "",
            *lines,
        ]
    )
