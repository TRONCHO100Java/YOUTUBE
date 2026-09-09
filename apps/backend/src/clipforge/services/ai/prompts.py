"""Construcción de los prompts de análisis de viralidad.

Se mantienen aquí, separados de los clientes de cada proveedor, porque el
prompt es la pieza que más se itera y debe ser idéntica entre proveedores para
que comparar OpenAI, Anthropic y Ollama sea justo.

El baremo no se escribe a mano: se genera a partir de las dimensiones del
perfil (`profiles.py`), de modo que el prompt y el esquema JSON que se le exige
al modelo no puedan quedar desincronizados.
"""

from __future__ import annotations

from collections.abc import Sequence

from clipforge.services.ai.base import AnalysisContext, AnalysisWindow
from clipforge.services.ai.profiles import ProfileRules
from clipforge.services.signals.base import MomentBlock

#: Los segmentos se numeran para que el modelo pueda referenciarlos. Es el
#: mecanismo que impide que invente timestamps: solo puede elegir índices.
TEXT_INTRO = """\
Eres un editor experto en vídeo social (TikTok, Reels, Shorts). Tu trabajo es \
encontrar, dentro de la transcripción de un vídeo largo, los momentos que \
funcionarían como clips cortos independientes.

Recibes segmentos numerados de la transcripción. Cada uno lleva su índice, su \
marca de tiempo y su texto."""

VISION_INTRO = """\
Eres un editor experto en vídeo social (TikTok, Reels, Shorts). Tu trabajo es \
encontrar, dentro de un vídeo largo, los momentos que funcionarían como clips \
cortos independientes.

Este vídeo casi no tiene diálogo utilizable, así que NO recibes transcripción: \
recibes fotogramas de varios bloques del vídeo, numerados, junto con las \
señales medidas en cada uno (volumen, movimiento y cortes de plano). Juzga por \
lo que VES."""

TEXT_RULES = """\
1. Un clip se define SIEMPRE por un rango de índices de segmento existentes \
(start_segment y end_segment). Nunca escribas tiempos: no los conoces mejor que \
el sistema, y se calculan a partir de los segmentos que elijas.
2. Usa únicamente índices que aparezcan en el fragmento que se te ha dado.
3. end_segment debe ser mayor o igual que start_segment."""

VISION_RULES = """\
1. Un clip se define SIEMPRE por el número de uno de los bloques que se te han \
mostrado. Nunca escribas tiempos: no los conoces, y los calcula el sistema.
2. Usa únicamente números de bloque que aparezcan en esta petición.
3. Si el bloque contiene relleno al principio o al final, dilo con trim_start y \
trim_end en segundos. Si te vale entero, pon 0 en ambos."""

#: Cómo de exigente debe ser el modelo al INCLUIR un momento.
#:
#: En el análisis de texto se le pasa la transcripción entera y la mayor parte
#: es relleno, así que descartar sin piedad es lo correcto. En el visual los
#: bloques ya llegan preseleccionados por volumen y movimiento, y repetirle allí
#: que puede devolver una lista vacía hace que un modelo pequeño devuelva
#: siempre eso. La exigencia va en la PUNTUACIÓN, no en dejar el clip fuera.
TEXT_SELECTIVITY = (
    "Prefiere la calidad a la cantidad. Si no hay ningún momento realmente "
    "bueno, devuelve una lista vacía. No rellenes."
)

VISION_SELECTIVITY = (
    "Evalúa TODOS los bloques que se te muestran y devuelve los que contengan "
    "una situación con remate. Vienen preseleccionados por sus señales de audio "
    "y movimiento, así que lo normal es que alguno valga: sé exigente con la "
    "PUNTUACIÓN, no dejándolos fuera. Reserva la lista vacía para cuando todos "
    "sean claramente relleno."
)


def build_system_prompt(rules: ProfileRules, *, vision: bool = False) -> str:
    """Prompt del sistema para el perfil y la modalidad indicados."""
    intro = VISION_INTRO if vision else TEXT_INTRO
    modality_rules = VISION_RULES if vision else TEXT_RULES

    numbered_guidance = "\n".join(
        f"{index}. {line}" for index, line in enumerate(rules.guidance, start=5)
    )

    scoring = "\n".join(
        f"- {dimension.field_name} 0-{dimension.maximum}: {dimension.description}."
        for dimension in rules.dimensions
    )

    return f"""\
{intro}

REGLAS OBLIGATORIAS
{modality_rules}
4. Un clip debe durar entre {rules.min_duration} y {rules.max_duration} segundos; \
el punto óptimo está cerca de {rules.target_duration}.
{numbered_guidance}
{len(rules.guidance) + 5}. Escribe título, gancho y motivo en ESPAÑOL.
{len(rules.guidance) + 6}. {VISION_SELECTIVITY if vision else TEXT_SELECTIVITY}

PUNTUACIÓN (entero dentro de cada rango; no calcules el total, ya lo hace el sistema)
{scoring}

Sé severo puntuando. Un clip mediocre debe quedar por debajo de \
{rules.total_maximum // 2}."""


def build_user_prompt(window: AnalysisWindow, context: AnalysisContext) -> str:
    """Presenta una ventana de segmentos numerados al modelo."""
    header = [
        f"Vídeo: {context.title}" if context.title else None,
        f"Autor: {context.author}" if context.author else None,
        f"Idioma: {context.language}" if context.language else None,
        f"Fragmento {window.number}, de {timestamp(window.start)} a {timestamp(window.end)} "
        f"(índices {window.first_index}-{window.last_index}).",
    ]

    lines = [
        f"[{segment.index}] {timestamp(segment.start)} - {timestamp(segment.end)} | {segment.text}"
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


def build_vision_prompt(
    blocks: Sequence[MomentBlock], context: AnalysisContext, *, frames_per_block: int
) -> str:
    """Describe los bloques cuyos fotogramas acompañan a la petición.

    Las señales van incluidas como texto porque orientan la lectura de los
    fotogramas: un bloque con mucho movimiento y un pico de volumen al final
    tiene pinta de gag rematado, y eso no se ve en imágenes sueltas.
    """
    header = [
        f"Vídeo: {context.title}" if context.title else None,
        f"Autor: {context.author}" if context.author else None,
        f"Duración total: {timestamp(context.duration)}" if context.duration else None,
    ]

    lines = []
    for number, block in enumerate(blocks, start=1):
        lines.append(
            f"BLOQUE {number} | {timestamp(block.start)} - {timestamp(block.end)}"
            f" | {round(block.duration)} s"
            f" | volumen {block.energy:.2f}"
            f" | movimiento {block.motion:.2f}"
            f" | {block.peaks} picos de sonido"
            f" | {block.cut_rate:.1f} cortes/min"
        )

    return "\n".join(
        [
            *[item for item in header if item],
            "",
            f"Se te muestran {len(blocks)} bloques, {frames_per_block} fotogramas de cada uno, "
            "en orden. Los fotogramas van precedidos por la línea de su bloque.",
            "",
            *lines,
            "",
            "Para cada bloque que contenga una situación con remate, devuelve una "
            "entrada con su número de bloque y su puntuación.",
        ]
    )


def timestamp(seconds: float | None) -> str:
    """Formatea segundos como m:ss, que es como los lee mejor un modelo."""
    total = round(seconds or 0)
    return f"{total // 60}:{total % 60:02d}"
