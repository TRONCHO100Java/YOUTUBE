"""Construcción de los prompts de análisis de viralidad.

Se mantienen aquí, separados de los clientes de cada proveedor, porque el
prompt es la pieza que más se itera y debe ser idéntica entre proveedores para
que comparar OpenAI, Anthropic y Ollama sea justo.
"""

from __future__ import annotations

from clipforge.core.config import settings
from clipforge.services.ai.base import AnalysisContext, AnalysisWindow

#: Los segmentos se numeran para que el modelo pueda referenciarlos. Es el
#: mecanismo que impide que invente timestamps: solo puede elegir índices.
SYSTEM_PROMPT = """\
Eres un editor experto en vídeo social (TikTok, Reels, Shorts). Tu trabajo es \
encontrar, dentro de la transcripción de un vídeo largo, los momentos que \
funcionarían como clips cortos independientes.

Recibes segmentos numerados de la transcripción. Cada uno lleva su índice, su \
marca de tiempo y su texto.

REGLAS OBLIGATORIAS
1. Un clip se define SIEMPRE por un rango de índices de segmento existentes \
(start_segment y end_segment). Nunca escribas tiempos: no los conoces mejor que \
el sistema, y se calculan a partir de los segmentos que elijas.
2. Usa únicamente índices que aparezcan en el fragmento que se te ha dado.
3. end_segment debe ser mayor o igual que start_segment.
4. Un clip debe durar entre {min_duration} y {max_duration} segundos; el punto \
óptimo está cerca de {target_duration}. Cuenta los segundos con las marcas de \
tiempo antes de decidir el rango.
5. El clip tiene que entenderse SIN haber visto lo anterior. Si empieza a mitad \
de una idea o depende de algo dicho antes, no sirve.
6. Empieza en un momento fuerte: una afirmación rotunda, una pregunta, una \
confesión o un dato sorprendente. No empieces con relleno ni con una transición.
7. Termina en un cierre natural, no a mitad de frase.
8. Escribe título, gancho y motivo en el MISMO IDIOMA que la transcripción.
9. El gancho debe ser una cita textual del propio segmento inicial.
10. Prefiere la calidad a la cantidad. Si el fragmento no contiene ningún \
momento realmente bueno, devuelve una lista vacía. No rellenes.

PUNTUACIÓN (entero dentro de cada rango; no calcules el total, ya lo hace el sistema)
- hook_score 0-20: fuerza de los primeros segundos para frenar el scroll.
- curiosity_score 0-20: cuánta necesidad de seguir viendo genera.
- emotion_score 0-15: intensidad emocional (sorpresa, indignación, humor, empatía).
- clarity_score 0-15: se entiende solo, sin contexto previo.
- value_score 0-15: enseña algo, resuelve algo o aporta información útil.
- shareability_score 0-10: ganas de compartirlo, citarlo o discutirlo.
- duration_score 0-5: lo cerca que queda de la duración ideal.

Sé severo puntuando. Un clip mediocre debe quedar por debajo de 50."""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT.format(
        min_duration=settings.min_clip_duration,
        max_duration=settings.max_clip_duration,
        target_duration=settings.target_clip_duration,
    )


def build_user_prompt(window: AnalysisWindow, context: AnalysisContext) -> str:
    """Presenta una ventana de segmentos numerados al modelo."""
    header = [
        f"Vídeo: {context.title}" if context.title else None,
        f"Autor: {context.author}" if context.author else None,
        f"Idioma: {context.language}" if context.language else None,
        f"Fragmento {window.number}, de {_timestamp(window.start)} a {_timestamp(window.end)} "
        f"(índices {window.first_index}-{window.last_index}).",
    ]

    lines = [
        f"[{segment.index}] {_timestamp(segment.start)} - {_timestamp(segment.end)}"
        f" | {segment.text}"
        for segment in window.segments
    ]

    return "\n".join(
        [
            *[item for item in header if item],
            "",
            "SEGMENTOS:",
            *lines,
            "",
            "Devuelve los mejores momentos de este fragmento como rangos de índices. "
            "Si no hay ninguno que merezca la pena, devuelve una lista vacía.",
        ]
    )


def _timestamp(seconds: float) -> str:
    """Formatea segundos como m:ss, que es como los lee mejor un modelo."""
    total = round(seconds)
    return f"{total // 60}:{total % 60:02d}"
