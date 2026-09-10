"""El montador: qué es el gancho, qué contexto falta y dónde está el remate.

Las fases anteriores deciden **qué momento** se publica. Esta decide **cómo se
cuenta**, que es lo que separa un recorte de una pieza editada.

Hace tres cosas, y las tres importan por separado:

- **Aprieta la entrada y la salida.** El detector propone un rango generoso
  porque razona con segmentos enteros de transcripción. El montador dice en qué
  segundo empieza de verdad lo interesante. Arrancar dos segundos antes de la
  frase buena es regalar justo los dos segundos que deciden si alguien se queda.
- **Escribe el contexto que falta.** Un espectador que no ha visto el original
  no sabe quién es quién ni qué acaba de pasar. Una nota de cinco palabras en
  pantalla lo resuelve sin narración, sin voz y sin salir en cámara — y es
  **comentario propio**, no metraje ajeno recortado.
- **Marca dónde cae el remate.** Todavía no se usa para cortar, pero es lo que
  permitirá que ningún efecto se coma el final.

Lo que **no** hace: inventarse hechos. El contexto sale de lo que se dice en el
clip o del título del vídeo, y la regla está en el prompt y en la validación.
Una nota que afirme algo que no ha pasado es peor que no poner nada: el
espectador la cree.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.ai.base import AnalysisContext, ClipSuggestion
from clipforge.services.ai.client import ask_json, resolve_model
from clipforge.services.ai.prompts_story import build_story_system_prompt, build_story_user_prompt

logger = get_logger(__name__)

#: Una nota más larga que esto no se lee de un vistazo: se lee en lugar de ver
#: el vídeo, que es exactamente lo contrario de lo que se busca.
MAX_NOTE_CHARS = 42

#: Cuánto se queda una nota en pantalla. Lo justo para leerla dos veces.
NOTE_SECONDS = 2.5

#: Margen mínimo entre el gancho y la primera nota. Pegadas, el ojo salta de
#: una a otra y no mira el vídeo.
NOTE_CLEARANCE = 1.0

#: Cuánto se le permite recortar por los extremos, como fracción del clip. El
#: montador afina la entrada; si quiere quitar la mitad, el que se equivocó fue
#: el que eligió el momento, y eso se arregla más arriba.
MAX_TIGHTEN_RATIO = 0.35

#: Tope del gancho escrito. No es estético: el rótulo se parte en líneas y
#: recorta lo que no cabe, así que un gancho más largo llega a pantalla
#: mutilado. Tres líneas de dieciocho caracteres es lo que entra.
MAX_HOOK_CHARS = 54

#: Comillas de todo tipo, que los modelos ponen alrededor del texto entero.
_WRAPPING_QUOTES = "\u0022\u0027\u201c\u201d\u2018\u2019"

Ask = Callable[[str, str], str]


@dataclass(frozen=True, slots=True)
class StoryNote:
    """Una nota contextual, en segundos desde el inicio del clip."""

    text: str
    at: float

    @property
    def end(self) -> float:
        return self.at + NOTE_SECONDS


@dataclass(frozen=True, slots=True)
class Story:
    """Cómo se cuenta este clip. Tiempos relativos al inicio del clip."""

    #: Frase de apertura para escribir en pantalla. None deja la que hubiera.
    hook: str | None = None
    #: Segundo en el que empieza de verdad lo interesante.
    start_at: float = 0.0
    #: Segundo en el que conviene cortar. None = hasta el final.
    end_at: float | None = None
    #: Dónde cae el remate. Informativo por ahora.
    payoff_at: float | None = None
    notes: tuple[StoryNote, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Para guardarlo en JSONB tal cual."""
        return {
            "hook": self.hook,
            "start_at": round(self.start_at, 2),
            "end_at": round(self.end_at, 2) if self.end_at is not None else None,
            "payoff_at": round(self.payoff_at, 2) if self.payoff_at is not None else None,
            "notes": [{"text": note.text, "at": round(note.at, 2)} for note in self.notes],
        }


class RawNote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(description="Máximo seis palabras, en inglés")
    at: float = Field(description="Segundo del clip en el que aparece")


class RawStory(BaseModel):
    """Lo que el montador propone para un clip."""

    model_config = ConfigDict(extra="ignore")

    hook: str = Field(description="Frase de apertura para escribir en pantalla, en inglés")
    start_at: float = Field(description="Segundo en el que empieza lo interesante; 0 si ya empieza")
    end_at: float = Field(description="Segundo en el que conviene cortar")
    payoff_at: float = Field(description="Segundo en el que cae el remate")
    notes: list[RawNote] = Field(description="Notas de contexto, como mucho las que se pidan")


def write_story(
    clip: ClipSuggestion, context: AnalysisContext, *, ask: Ask | None = None
) -> Story | None:
    """Decide cómo se cuenta el clip, o None si no se ha podido.

    Devolver None es una respuesta legítima: el clip se publica como estaba.
    Igual que el titulado, esto es una mejora y no un requisito.
    """
    if not settings.story_editor_enabled:
        return None

    excerpt = (clip.transcript_excerpt or "").strip()
    if not excerpt:
        # Sin transcripción no hay nada que estructurar: el montador no ve el
        # vídeo. Un clip visual se queda con su gancho del análisis.
        return None

    started = time.perf_counter()
    request = ask or _ask_provider

    try:
        content = request(
            build_story_system_prompt(
                max_notes=settings.max_context_notes,
                max_note_chars=MAX_NOTE_CHARS,
            ),
            build_story_user_prompt(clip, context),
        )
        raw = _parse(content)
    except ExternalToolError as exc:
        logger.warning("ai.story_failed", error=exc.message)
        return None

    story = _validate(raw, duration=clip.duration, context=context)
    logger.info(
        "ai.story_written",
        tightened=round(story.start_at, 1),
        notes=len(story.notes),
        seconds=round(time.perf_counter() - started, 1),
    )
    return story


# ------------------------------------------------------------------ validación
def _parse(content: str) -> RawStory:
    """Lee la respuesta del montador.

    Raises:
        ExternalToolError: si no encaja con el esquema.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]

    try:
        return RawStory.model_validate_json(text)
    except ValidationError as exc:
        raise ExternalToolError(
            "El montador ha devuelto algo que no encaja con el esquema",
            details={"error": str(exc)[:400], "content": text[:400]},
        ) from exc


def _validate(raw: RawStory, *, duration: float, context: AnalysisContext) -> Story:
    """Acota lo que propone el montador a lo que se puede hacer de verdad."""
    limit = duration * MAX_TIGHTEN_RATIO

    start = _clamp(raw.start_at, 0.0, limit)
    end_raw = _clamp(raw.end_at, 0.0, duration)
    # Un final por debajo del mínimo publicable es el modelo equivocándose de
    # unidad —segundos del original en lugar del clip— más que una decisión.
    end = end_raw if end_raw >= start + settings.min_clip_duration else duration
    end = max(end, duration - limit)

    return Story(
        hook=_usable_hook(raw.hook),
        start_at=start,
        end_at=end if end < duration else None,
        payoff_at=_clamp(raw.payoff_at, start, end),
        notes=_validate_notes(raw.notes, start=start, end=end, context=context),
    )


def _validate_notes(
    raw: Sequence[RawNote], *, start: float, end: float, context: AnalysisContext
) -> tuple[StoryNote, ...]:
    """Deja las notas que caben, no se pisan, no tapan el gancho y DICEN algo."""
    notes: list[StoryNote] = []
    # El gancho ocupa el principio: una nota ahí compite con él y no se lee
    # ninguna de las dos.
    floor = start + settings.hook_overlay_seconds + NOTE_CLEARANCE

    for item in sorted(raw, key=lambda note: note.at):
        text = _clean(item.text, MAX_NOTE_CHARS)
        if not text or _says_nothing(text, context):
            continue

        at = _clamp(item.at, floor, max(floor, end - NOTE_SECONDS))
        if notes and at < notes[-1].end + NOTE_CLEARANCE:
            continue
        if at + NOTE_SECONDS > end:
            continue

        notes.append(StoryNote(text=text, at=at))
        if len(notes) >= settings.max_context_notes:
            break

    return tuple(notes)


def _usable_hook(text: str) -> str | None:
    """El gancho del montador, o None si no sirve para estar en pantalla.

    Se descarta por largo en vez de recortarlo, y no es una manía: medido
    sobre clips reales, un modelo pequeño devuelve descripciones —*Kai
    Cenat's intense training montage reveals a powerful message*— en lugar
    de ganchos. Recortarla dejaría media descripción en pantalla; tirarla
    deja el gancho del análisis, que en un clip hablado es una **cita
    textual** de lo que se dice y casi siempre es mejor.

    Es la regla de siempre del proyecto: ante la duda, lo que ya había.
    """
    cleaned = _clean(text, MAX_HOOK_CHARS * 2)
    if not cleaned or len(cleaned) > MAX_HOOK_CHARS:
        return None
    return cleaned


def _clean(text: str, limit: int) -> str:
    """Una línea de texto plano, recortada por palabra si se pasa."""
    # Las comillas van escapadas: las tipográficas se confunden a simple
    # vista con el acento grave y con la comilla recta.
    cleaned = " ".join((text or "").split()).strip(_WRAPPING_QUOTES).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rsplit(" ", 1)[0].rstrip(",;:-").strip()


def _says_nothing(text: str, context: AnalysisContext) -> bool:
    """¿La nota aporta algo que el espectador no pueda ver?

    Una nota que solo pone "Kai Cenat" encima de un vídeo de Kai Cenat es
    ruido: ocupa pantalla, distrae y no explica nada. Se descarta cuando el
    texto ya está en el título del vídeo o es una de las palabras clave —
    que son, por definición, lo que ya se sabía antes de mirar.
    """
    lowered = text.casefold()
    if any(lowered == keyword.casefold() for keyword in context.keywords):
        return True
    title = (context.title or "").casefold()
    author = (context.author or "").casefold()
    return bool(lowered) and (lowered in title or lowered == author)


def _clamp(value: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    return round(max(low, min(high, number)), 2)


def _schema() -> dict[str, Any]:
    schema = RawStory.model_json_schema()
    schema["additionalProperties"] = False
    return schema


def _ask_provider(system: str, user: str) -> str:
    """Le pide la estructura al modelo configurado para montar."""
    return ask_json(
        system,
        user,
        schema=_schema(),
        choice=resolve_model(settings.ai_story_provider, settings.ai_story_model),
        temperature=0.2,
    )
