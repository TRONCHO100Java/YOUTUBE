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
#: Esto decía lo contrario hasta la fase 20, y con razón: cuando el detector
#: era también quien elegía, lo que proponía se publicaba, así que descartar
#: sin piedad era lo correcto.
#:
#: Desde que hay un juez que compara y recorta, esa orden se volvió dañina.
#: Medido sobre tres recopilaciones de Kai Cenat de nueve minutos: el modelo
#: devolvió `{"candidates": []}` en TODAS las ventanas y los tres proyectos
#: acabaron sin un solo clip. No es que no hubiera momentos: es que se le
#: había dicho que ante la duda no propusiera, y un modelo pequeño lleva esa
#: instrucción hasta el final.
#:
#: Ahora las dos modalidades dicen lo mismo, que es lo que siempre debió ser:
#: propón, que ya hay quien descarta.
TEXT_SELECTIVITY = (
    "Propón con generosidad: varios momentos por fragmento si los hay. NO eres "
    "tú quien decide qué se publica —después hay un editor jefe que los compara "
    "todos y se queda con unos pocos—, así que tu trabajo es no dejarte nada "
    "bueno fuera. Un momento dudoso que propones no cuesta nada; uno bueno que "
    "no propones se pierde para siempre. Sé exigente con la PUNTUACIÓN, no "
    "dejando momentos fuera. Devuelve la lista vacía solo si el fragmento "
    "entero es relleno."
)

VISION_SELECTIVITY = (
    "Evalúa TODOS los bloques que se te muestran y devuelve los que contengan "
    "una situación con remate. Vienen preseleccionados por sus señales de audio "
    "y movimiento, así que lo normal es que alguno valga: sé exigente con la "
    "PUNTUACIÓN, no dejándolos fuera. Reserva la lista vacía para cuando todos "
    "sean claramente relleno."
)


#: El vídeo puede estar en cualquier idioma, pero el clip se publica en inglés:
#: el título y el gancho son texto de cara al público (el gancho se incrusta en
#: pantalla), así que van en inglés siempre. El motivo no se publica —es la nota
#: que lee el editor en la interfaz— y se queda en español.
LANGUAGE_RULE = (
    "Escribe el título y el gancho SIEMPRE EN INGLÉS, sea cual sea el idioma del "
    "vídeo: son los textos que se publican. Si lo que se dice está en otro idioma, "
    "tradúcelo. El motivo escríbelo en español: es una nota interna para el editor."
)


#: Las palabras clave son un arma de doble filo: bien usadas ponen en el
#: título el nombre que la gente busca; metidas a la fuerza producen títulos
#: que prometen algo que el clip no enseña, y eso se paga en retención. La
#: regla dice las dos cosas.
KEYWORDS_RULE = (
    "Se te dan PALABRAS CLAVE del vídeo (de qué va, quién sale, cómo se le "
    "busca). Úsalas en el título y en el gancho SOLO cuando encajen con lo que "
    "pasa en ese clip concreto: un nombre propio que la gente busca vale más "
    "que cualquier adjetivo. Si no encajan, no las metas: un título que promete "
    "algo que el clip no enseña pierde al espectador en dos segundos."
)


def build_system_prompt(
    rules: ProfileRules, *, vision: bool = False, keywords: bool = False
) -> str:
    """Prompt del sistema para el perfil y la modalidad indicados.

    `keywords` dice si el usuario ha aportado términos. La regla que los
    gobierna solo se añade cuando los hay: explicarle a un modelo cómo usar
    una lista vacía es gastar atención en nada.
    """
    intro = VISION_INTRO if vision else TEXT_INTRO
    modality_rules = VISION_RULES if vision else TEXT_RULES

    # Las reglas del perfil, el idioma y la exigencia son una sola lista
    # numerada: así ninguna se queda sin número al añadir o quitar otra.
    guidance = [*rules.guidance, LANGUAGE_RULE]
    if keywords:
        guidance.append(KEYWORDS_RULE)
    guidance.append(VISION_SELECTIVITY if vision else TEXT_SELECTIVITY)

    numbered_guidance = "\n".join(
        f"{index}. {line}" for index, line in enumerate(guidance, start=5)
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

PUNTUACIÓN (entero dentro de cada rango; no calcules el total, ya lo hace el sistema)
{scoring}

Sé severo puntuando. Un clip mediocre debe quedar por debajo de \
{rules.total_maximum // 2}."""


def keywords_line(context: AnalysisContext) -> str | None:
    """Las palabras clave del usuario, listas para la cabecera del mensaje.

    Van en el mensaje y no en el prompt del sistema porque describen ESTE
    vídeo, no cómo trabajar. Devuelve None si no hay ninguna, para que la
    cabecera no arrastre una línea vacía.
    """
    if not context.keywords:
        return None
    return f"Palabras clave del usuario: {', '.join(context.keywords)}"


def build_user_prompt(window: AnalysisWindow, context: AnalysisContext) -> str:
    """Presenta una ventana de segmentos numerados al modelo."""
    header = [
        f"Vídeo: {context.title}" if context.title else None,
        f"Autor: {context.author}" if context.author else None,
        f"Idioma: {context.language}" if context.language else None,
        keywords_line(context),
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
        keywords_line(context),
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
