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

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.ai.base import AnalysisContext, ClipSuggestion, TitleBrief
from clipforge.services.ai.prompts_titles import (
    build_titles_system_prompt,
    build_titles_user_prompt,
)

logger = get_logger(__name__)

#: Modelo por defecto de cada proveedor cuando el general no le sirve.
DEFAULT_MODELS = {
    "ollama": "qwen2.5:14b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-opus-5",
}

#: Cómo empieza el nombre de modelo de cada proveedor. Sirve para detectar
#: que AI_MODEL trae el de otro y no mandarle a Anthropic un "qwen2.5:14b".
MODEL_PREFIXES: dict[str, tuple[str, ...]] = {
    "openai": ("gpt", "o1", "o3", "o4"),
    "anthropic": ("claude",),
}

MAX_TOKENS = 4000

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
    """Los títulos propuestos para un clip."""

    model_config = ConfigDict(extra="ignore")

    clip: int = Field(description="Número del clip que se te ha dado")
    titles: list[str] = Field(description="Variantes del título, de mejor a peor")


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

    try:
        content = (ask or _ask_provider)(
            build_titles_system_prompt(
                max_chars=settings.title_max_chars,
                variants=settings.title_variants,
                keywords=bool(context.keywords),
            ),
            build_titles_user_prompt(briefs, context),
        )
        proposals = parse_titles(content)
    except ExternalToolError as exc:
        # El titulado es una mejora, no un requisito: los clips ya están.
        logger.warning("ai.titles_failed", error=exc.message)
        return clips

    titled = _apply(clips, proposals)
    logger.info(
        "ai.titles_written",
        clips=len(clips),
        rewritten=sum(1 for old, new in zip(clips, titled, strict=True) if old.title != new.title),
        seconds=round(time.perf_counter() - started, 1),
    )
    return titled


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


def choose_title(
    variants: Sequence[str],
    *,
    fallback: str,
    hook: str | None = None,
    taken_openings: set[str],
    max_chars: int,
) -> str:
    """Elige la primera variante publicable.

    El orden importa: el modelo las devuelve de mejor a peor, así que bajar por
    la lista es bajar por calidad. Si ninguna pasa limpia se recorta la mejor
    por la última palabra que quepa, y si aun así no queda nada aprovechable
    manda el título del análisis: peor, pero real.
    """
    candidates = [title for title in (clean_title(variant) for variant in variants) if title]

    for title in candidates:
        if len(title) > max_chars:
            continue
        if is_cliche(title) or shouts(title):
            continue
        # El gancho ya va escrito en pantalla: repetirlo en el título gasta las
        # dos líneas de texto del clip en decir lo mismo.
        if hook and title.casefold() == hook.strip().casefold():
            continue
        if opening(title) in taken_openings:
            continue
        return title

    # Ninguna limpia. Se rescata la mejor recortando: suele ser un título
    # correcto al que le sobra una subordinada.
    for title in candidates:
        if is_cliche(title) or shouts(title):
            continue
        trimmed = _trim(title, max_chars)
        if trimmed and opening(trimmed) not in taken_openings:
            return trimmed

    return fallback


def parse_titles(content: str) -> dict[int, list[str]]:
    """Extrae {número de clip: variantes} de la respuesta del modelo.

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

    return {entry.clip: entry.titles for entry in payload.clips}


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


def _apply(
    clips: Sequence[ClipSuggestion], proposals: dict[int, list[str]]
) -> list[ClipSuggestion]:
    """Sustituye el título de cada clip por la mejor variante admisible.

    Los arranques ya usados se acumulan mientras se recorre la lista: es lo que
    impide que los cinco clips de un vídeo se llamen todos "The farmer slips…".
    """
    taken: set[str] = set()
    titled: list[ClipSuggestion] = []

    for number, clip in enumerate(clips, start=1):
        title = choose_title(
            proposals.get(number, []),
            fallback=clip.title,
            hook=clip.hook,
            taken_openings=taken,
            max_chars=settings.title_max_chars,
        )
        taken.add(opening(title))
        titled.append(clip if title == clip.title else replace(clip, title=title))

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


def _provider_and_model() -> tuple[str, str]:
    """Proveedor y modelo del titulado, con los generales como respaldo."""
    provider = (settings.ai_title_provider or settings.ai_provider).lower()
    if provider not in DEFAULT_MODELS:
        raise ExternalToolError(
            f"Proveedor de titulado desconocido: '{provider}'",
            details={"supported": sorted(DEFAULT_MODELS)},
        )

    model = settings.ai_title_model or settings.ai_model
    # AI_MODEL es común a todos los proveedores: si trae el de otro, no sirve
    # y hay que caer al de casa. Ollama no entra: ahí el modelo se llama
    # como quiera quien lo haya descargado.
    prefixes = MODEL_PREFIXES.get(provider)
    if prefixes and not model.startswith(prefixes):
        model = DEFAULT_MODELS[provider]
    return provider, model


def _ask_provider(system: str, user: str) -> str:
    """Manda la petición al proveedor configurado y devuelve su JSON."""
    provider, model = _provider_and_model()

    if provider == "ollama":
        return _ask_ollama(system, user, model)
    if provider == "openai":
        return _ask_openai(system, user, model)
    return _ask_anthropic(system, user, model)


def _ask_ollama(system: str, user: str, model: str) -> str:
    base_url = settings.ollama_base_url.rstrip("/")
    payload = {
        "model": model,
        "stream": False,
        "format": _schema(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": TEMPERATURE, "num_ctx": 8192},
    }

    try:
        response = httpx.post(
            f"{base_url}/api/chat", json=payload, timeout=settings.ai_request_timeout_seconds
        )
        response.raise_for_status()
        content = (response.json().get("message") or {}).get("content")
    except httpx.HTTPStatusError as exc:
        raise ExternalToolError(
            f"Ollama ha respondido {exc.response.status_code} al titular",
            details={"body": exc.response.text[:500]},
        ) from exc
    except httpx.HTTPError as exc:
        raise ExternalToolError(
            f"No se ha podido contactar con Ollama en {base_url} para titular",
            details={"error": str(exc)},
        ) from exc

    if not content:
        raise ExternalToolError("Ollama ha devuelto una respuesta vacía al titular")
    return str(content)


def _ask_openai(system: str, user: str, model: str) -> str:
    from openai import OpenAI, OpenAIError

    if not settings.openai_api_key:
        raise ExternalToolError("El titulado usa OpenAI pero falta OPENAI_API_KEY")

    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.ai_request_timeout_seconds,
        max_retries=settings.ai_max_retries,
    )
    try:
        completion = client.chat.completions.create(
            model=model,
            temperature=TEMPERATURE,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "clip_titles", "strict": True, "schema": _schema()},
            },
        )
    except OpenAIError as exc:
        raise ExternalToolError(
            "La llamada de titulado a OpenAI ha fallado", details={"error": str(exc)[:500]}
        ) from exc

    content = completion.choices[0].message.content if completion.choices else None
    if not content:
        raise ExternalToolError("OpenAI ha devuelto una respuesta vacía al titular")
    return str(content)


def _ask_anthropic(system: str, user: str, model: str) -> str:
    import anthropic

    if not settings.anthropic_api_key:
        raise ExternalToolError("El titulado usa Anthropic pero falta ANTHROPIC_API_KEY")

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=float(settings.ai_request_timeout_seconds),
        max_retries=settings.ai_max_retries,
    )
    try:
        message = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            # Sin temperatura explícita: los tipos del SDK no la admiten junto
            # a la salida estructurada, y su valor por defecto ya da variantes
            # distintas, que es lo único que se le pedía aquí.
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": _schema()}},
        )
    except anthropic.APIError as exc:
        raise ExternalToolError(
            "La llamada de titulado a Anthropic ha fallado", details={"error": str(exc)[:500]}
        ) from exc

    if message.stop_reason == "refusal":
        raise ExternalToolError("Anthropic ha rechazado titular por sus filtros de seguridad")

    content = next((block.text for block in message.content if block.type == "text"), None)
    if not content:
        raise ExternalToolError("Anthropic ha devuelto una respuesta vacía al titular")
    return str(content)
