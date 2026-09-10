"""Reescritura de los títulos de los clips ya elegidos.

El título que sale del análisis es un subproducto. Ese modelo está repartiendo
cien puntos entre siete dimensiones y el título lo escribe de paso, así que
nombra la escena en lugar de venderla: "La fiesta de colores", "El salto del
niño". Eso es una etiqueta de archivo, no un título de YouTube.

Esta pasada lo arregla por donde se puede arreglar: separando el trabajo. Corre
**después** de la selección, sobre los clips que van a existir de verdad, así
que cuesta una llamada por proyecto en lugar de una por ventana de
transcripción. A ese precio se puede pagar un modelo bueno aunque el análisis
corra en local.

Dos principios heredados del resto del pipeline:

- **Nada de lo que devuelve el modelo se cree sin comprobar.** Se piden varias
  variantes por clip y se acepta la primera que pasa el filtro.
- **Nunca terminar con las manos vacías.** Si el titulado falla, o si ninguna
  variante sirve, el clip conserva el título del análisis. Un título mediocre
  es infinitamente mejor que un proyecto sin clips.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.ai.base import AnalysisContext, ClipSuggestion, TitleBrief
from clipforge.services.ai.client import ask_json, resolve_model
from clipforge.services.ai.prompts_titles import (
    build_titles_system_prompt,
    build_titles_user_prompt,
)

logger = get_logger(__name__)

#: Un poco de temperatura, al contrario que en el análisis. Con 0 las variantes
#: de un mismo clip salen casi idénticas y el validador se queda sin recambio
#: en cuanto la primera falla; el análisis sí la necesita a 0 porque su salida
#: es un ranking y tiene que ser reproducible.
TEMPERATURE = 0.4

#: Tópicos que hacen que un título parezca spam. No basta con prohibírselos en
#: el prompt: están en el título de medio YouTube, así que un modelo pequeño
#: los escribe igual.
CLICHES = (
    "you won't believe",
    "you wont believe",
    "this is what happened",
    "watch what happens",
    "wait for it",
    "must watch",
    "gone wrong",
    "funny moment",
    "best clip",
    "amazing video",
)

#: Cuántas palabras iniciales tienen que compartir dos títulos para considerar
#: que arrancan igual. Con dos saltarían falsos positivos ("The moment...") y
#: con cuatro ya no se parecería ningún título a otro.
SAME_OPENING_WORDS = 3

#: Tope de la descripción. YouTube admite muchísimo más, pero solo se leen
#: las dos primeras líneas antes del "…más"; lo que sobre es relleno.
MAX_DESCRIPTION_CHARS = 400

#: La etiqueta que decide que el vídeo entre en el carrusel de Shorts. Va
#: siempre y va la primera, aunque el modelo se olvide de ella.
SHORTS_TAG = "shorts"

#: Con más etiquetas no se gana alcance, se gana ruido: YouTube ignora las
#: que no encajan y una lista larga parece spam.
MAX_HASHTAGS = 5

#: Una etiqueta es una palabra pegada: fuera espacios, almohadillas y
#: cualquier signo. "Kai Cenat" se busca como #KaiCenat.
_TAG_JUNK = re.compile(r"\W+", flags=re.UNICODE)

_WHITESPACE = re.compile(r"\s+")
#: Comillas de todo tipo: los modelos envuelven el título entero en ellas.
#: Van escapadas porque las tipográficas se confunden a simple vista con
#: el acento grave y con la comilla recta.
_WRAPPING_QUOTES = "\u0022\u0027\u201c\u201d\u2018\u2019"
#: Numeración de lista pegada al título ("1. ", "2) "). Se exige el punto o
#: el paréntesis y el espacio para no descabezar un título que empieza de
#: verdad por un número, que en Shorts es de lo más normal ("3 seconds…").
_LIST_NUMBER = re.compile(r"^\d+[.)]\s+")
#: Un título que empieza por emoji o por viñeta no es un título.
_LEADING_JUNK = re.compile(r"^[^\w\"'¿¡(]+", flags=re.UNICODE)


class RawTitle(BaseModel):
    """Lo que el redactor propone para un clip."""

    model_config = ConfigDict(extra="ignore")

    clip: int = Field(description="Número del clip que se te ha dado")
    titles: list[str] = Field(description="Variantes del título, de mejor a peor")
    description: str = Field(description="Dos o tres frases para la caja de YouTube")
    hashtags: list[str] = Field(description="Etiquetas temáticas, sin almohadilla")


class RawTitles(BaseModel):
    """Respuesta completa del titulado."""

    model_config = ConfigDict(extra="ignore")

    clips: list[RawTitle] = Field(description="Una entrada por clip")


#: "Pregúntale al proveedor y devuélveme su JSON". Se inyecta en los tests para
#: poder probar toda la validación sin gastar una llamada ni encender una GPU.
Ask = Callable[[str, str], str]


# ------------------------------------------------------------------- público
def write_titles(
    suggestions: Sequence[ClipSuggestion],
    context: AnalysisContext,
    *,
    ask: Ask | None = None,
) -> list[ClipSuggestion]:
    """Devuelve los mismos clips con el título reescrito.

    No toca nada más: ni tiempos, ni puntuación, ni el gancho que se incrusta
    en el vídeo. Un fallo aquí no es un fallo del proyecto, así que se registra
    y los clips salen tal y como entraron.
    """
    clips = list(suggestions)
    if not clips or not settings.titles_enabled:
        return clips

    started = time.perf_counter()
    briefs = [_brief(number, clip) for number, clip in enumerate(clips, start=1)]
    system = build_titles_system_prompt(
        max_chars=settings.title_max_chars,
        variants=settings.title_variants,
        # Una la pone el sistema, así que al modelo se le piden el resto.
        hashtags=MAX_HASHTAGS - 1,
        keywords=bool(context.keywords),
    )
    user = build_titles_user_prompt(briefs, context)
    request = ask or _ask_provider

    proposals = _ask_until_answered(request, system, user)
    if not proposals:
        # Una lista vacía cumple el esquema, así que no es un error del que
        # avise nadie. Pero tratarla como éxito haría que la interfaz dijese
        # "sin cambios, los títulos que había siguen siendo los mejores"
        # cuando en realidad el modelo no ha dicho ni una palabra.
        logger.warning("ai.titles_empty", clips=len(clips))
        return clips

    titled = _apply(clips, proposals)
    logger.info(
        "ai.titles_written",
        clips=len(clips),
        answered=len(proposals),
        rewritten=sum(1 for a, b in zip(clips, titled, strict=True) if a.title != b.title),
        seconds=round(time.perf_counter() - started, 1),
    )
    return titled


def _ask_until_answered(ask: Ask, system: str, user: str) -> dict[int, RawTitle]:
    """Pide títulos, reintentando mientras la respuesta venga vacía.

    Un modelo local devuelve de vez en cuando `{"clips": []}`: cumple el
    esquema, así que no salta ningún error, y sin embargo no ha titulado
    nada. Es el mismo reintento que ya hace el análisis con Ollama, y por la
    misma razón: perder la pasada entera por un mal rato del modelo cuesta
    mucho más que volver a preguntar.
    """
    attempts = max(1, settings.ai_max_retries)

    for attempt in range(1, attempts + 1):
        try:
            proposals = parse_titles(ask(system, user))
        except ExternalToolError as exc:
            # El titulado es una mejora, no un requisito: los clips ya están.
            logger.warning("ai.titles_failed", attempt=attempt, error=exc.message)
            return {}

        if proposals:
            return proposals
        logger.info("ai.titles_retry", attempt=attempt)

    return {}


# ----------------------------------------------------------------- validación
def clean_title(raw: str) -> str:
    """Quita lo que un modelo añade sin que se le pida.

    Comillas alrededor, viñetas, emojis de adorno al principio y el punto
    final: nada de eso se publica, y todo llega de vez en cuando pegado al
    título.
    """
    title = _WHITESPACE.sub(" ", raw).strip()
    title = title.strip(_WRAPPING_QUOTES).strip()
    title = _LIST_NUMBER.sub("", title).strip()
    title = _LEADING_JUNK.sub("", title).strip()
    return title.rstrip(".").strip()


def is_cliche(title: str) -> bool:
    """¿Es una de esas frases por las que se pasa de largo?"""
    lowered = title.casefold()
    return any(cliche in lowered for cliche in CLICHES)


def shouts(title: str) -> bool:
    """TODO EN MAYÚSCULAS.

    Se mide sobre las letras, y solo a partir de ocho, para no confundirlo con
    un título corto lleno de siglas o de nombres propios.
    """
    letters = [character for character in title if character.isalpha()]
    return len(letters) >= 8 and all(character.isupper() for character in letters)


def opening(title: str) -> str:
    """Las primeras palabras, que es por donde se parecen dos títulos."""
    return " ".join(title.casefold().split()[:SAME_OPENING_WORDS])


def publishable_variants(variants: Sequence[str], *, max_chars: int) -> list[str]:
    """Variantes limpias y publicables, ordenadas por preferencia.

    Aplica solo los filtros que dependen del texto y de nada más. Los que
    dependen del contexto —no repetir el gancho, no repetir el arranque de
    otro clip— los aplica `choose_title`, porque el mismo título puede valer
    en un clip y estorbar en el siguiente.

    Las que caben van delante y las recortadas detrás: un título que el
    modelo escribió corto es mejor que uno al que le hemos cortado el final,
    aunque lo propusiera antes.
    """
    fits: list[str] = []
    trimmed: list[str] = []
    seen: set[str] = set()

    for variant in variants:
        title = clean_title(variant)
        if not title or is_cliche(title) or shouts(title):
            continue

        bucket = fits
        if len(title) > max_chars:
            # Suele ser un título correcto al que le sobra una subordinada,
            # así que se rescata en vez de tirarlo.
            title = _trim(title, max_chars)
            bucket = trimmed

        key = title.casefold()
        if not title or key in seen:
            continue
        seen.add(key)
        bucket.append(title)

    return [*fits, *trimmed]


def choose_title(
    variants: Sequence[str],
    *,
    fallback: str,
    hook: str | None = None,
    taken_openings: set[str],
    max_chars: int,
) -> str:
    """Elige la primera variante publicable que además encaja en este clip.

    El orden importa: el modelo las devuelve de mejor a peor, así que bajar
    por la lista es bajar por calidad. Si ninguna sirve manda el título del
    análisis: peor, pero real.
    """
    for title in publishable_variants(variants, max_chars=max_chars):
        # El gancho ya va escrito en pantalla: repetirlo en el título gasta
        # los dos textos del clip en decir lo mismo.
        if hook and title.casefold() == hook.strip().casefold():
            continue
        if opening(title) in taken_openings:
            continue
        return title

    return fallback


def clean_description(raw: str) -> str | None:
    """Deja la descripción en una línea de texto plano, o None si no hay nada."""
    text = _WHITESPACE.sub(" ", raw).strip()
    text = text.strip(_WRAPPING_QUOTES).strip()
    if not text:
        return None
    return _trim(text, MAX_DESCRIPTION_CHARS) or None


def clean_hashtags(raw: Sequence[str]) -> tuple[str, ...]:
    """Normaliza las etiquetas y garantiza que `shorts` va la primera.

    Una etiqueta es una palabra pegada, así que fuera espacios, almohadillas
    y signos: "Kai Cenat" se busca como #KaiCenat. `shorts` se pone aquí y no
    se le pide al modelo porque es la que decide que el vídeo entre en el
    carrusel, y olvidarla cuesta demasiado como para dejarla a su criterio.
    """
    tags = [SHORTS_TAG]
    seen = {SHORTS_TAG}

    for item in raw:
        tag = _TAG_JUNK.sub("", item)
        key = tag.casefold()
        if not tag or key in seen:
            continue
        seen.add(key)
        tags.append(tag)
        if len(tags) == MAX_HASHTAGS:
            break

    return tuple(tags)


def parse_titles(content: str) -> dict[int, RawTitle]:
    """Extrae lo que el modelo propone para cada clip, por número de clip.

    Raises:
        ExternalToolError: si lo que ha devuelto no encaja con el esquema.
    """
    text = content.strip()
    # Algunos modelos envuelven el JSON en un bloque de código pese al esquema.
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]

    try:
        payload = RawTitles.model_validate_json(text)
    except ValidationError as exc:
        raise ExternalToolError(
            "El titulado ha devuelto algo que no encaja con el esquema",
            details={"error": str(exc)[:400], "content": text[:400]},
        ) from exc

    return {entry.clip: entry for entry in payload.clips}


# -------------------------------------------------------------------- privado
def _brief(number: int, clip: ClipSuggestion) -> TitleBrief:
    """Lo que se le enseña al redactor sobre un clip.

    El resumen sale del motivo antes que del título: el motivo explica por qué
    el momento funciona, mientras que el título del análisis es justo el texto
    pobre que se está intentando sustituir. Dárselo como resumen invitaría a
    reescribirlo con otras palabras en lugar de mirar el clip.
    """
    summary = (clip.reason or "").strip() or clip.title
    excerpt = (clip.transcript_excerpt or "").strip()
    return TitleBrief(
        number=number,
        start=clip.start_time,
        end=clip.end_time,
        summary=summary,
        hook=clip.hook,
        excerpt=excerpt[:600] or None,
    )


def _apply(clips: Sequence[ClipSuggestion], proposals: dict[int, RawTitle]) -> list[ClipSuggestion]:
    """Vuelca sobre cada clip el título, las variantes y los metadatos.

    Los arranques ya usados se acumulan mientras se recorre la lista: es lo
    que impide que los cinco clips de un vídeo se llamen todos "The farmer
    slips…".

    Las variantes se guardan aunque no se usen. La llamada ya está pagada, y
    tenerlas en la base de datos convierte "no me gusta este título" en un
    clic en el editor en lugar de en otra llamada al modelo.
    """
    taken: set[str] = set()
    titled: list[ClipSuggestion] = []

    for number, clip in enumerate(clips, start=1):
        proposal = proposals.get(number)
        if proposal is None:
            # El modelo se ha saltado este clip: se queda como estaba.
            taken.add(opening(clip.title))
            titled.append(clip)
            continue

        title = choose_title(
            proposal.titles,
            fallback=clip.title,
            hook=clip.hook,
            taken_openings=taken,
            max_chars=settings.title_max_chars,
        )
        taken.add(opening(title))

        variants = publishable_variants(proposal.titles, max_chars=settings.title_max_chars)
        titled.append(
            replace(
                clip,
                title=title,
                # El elegido no se repite entre las alternativas: en el editor
                # son "los otros títulos", no "todos los títulos".
                title_variants=tuple(other for other in variants if other != title),
                description=clean_description(proposal.description),
                hashtags=clean_hashtags(proposal.hashtags),
            )
        )

    return titled


def _trim(title: str, max_chars: int) -> str:
    """Recorta por la última palabra que quepa, sin dejar el corte a la vista."""
    if len(title) <= max_chars:
        return title
    cut = title[:max_chars].rsplit(" ", 1)[0].strip()
    return cut.rstrip(",;:-").strip()


def _schema() -> dict[str, Any]:
    """Esquema JSON que se le exige a la respuesta."""
    schema = RawTitles.model_json_schema()
    schema["additionalProperties"] = False
    return schema


def _ask_provider(system: str, user: str) -> str:
    """Le pide los títulos al modelo configurado para titular."""
    return ask_json(
        system,
        user,
        schema=_schema(),
        choice=resolve_model(settings.ai_title_provider, settings.ai_title_model),
        temperature=TEMPERATURE,
    )
