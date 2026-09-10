"""Etiquetar de qué va cada clip, para poder tener varios canales.

Un canal de Shorts funciona cuando lo que publica se parece entre sí. Mezclar
un gag de Kai Cenat con un recorte de un pódcast de negocios no es variedad: es
un canal sin tema, y el algoritmo tarda mucho más en entender a quién
enseñárselo.

Este módulo pone una etiqueta a cada clip —nicho, quién sale, de qué va y qué
clase de momento es— para que luego se pueda repartir por canales sin abrir los
cinco vídeos y mirarlos.

Es lo más barato de todo el pipeline: **una llamada por proyecto**, no por clip,
y con lo que ya está escrito. Y a diferencia del juez o el montador, aquí un
modelo pequeño se defiende bien: reconocer que un vídeo va de streamers y sale
Kai Cenat no es criterio, es lectura.

Las etiquetas se normalizan al guardarlas —minúsculas, sin acentos ni signos—
porque su único uso es **agrupar**, y "Kai Cenat", "kai cenat" y "Kai-Cenat"
tienen que caer en el mismo montón.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.ai.base import AnalysisContext, ClipSuggestion
from clipforge.services.ai.client import ask_json, resolve_model
from clipforge.services.ai.prompts_tagging import (
    MOMENT_KINDS,
    build_tagging_system_prompt,
    build_tagging_user_prompt,
)

logger = get_logger(__name__)

#: Tope de personas y temas por clip. Más de tres nombres no identifica: diluye.
MAX_PEOPLE = 3
MAX_TOPICS = 3

#: Una etiqueta más larga que esto es una frase, y una frase no agrupa nada.
MAX_TAG_CHARS = 32

_SEPARATORS = re.compile(r"[^a-z0-9]+")

Ask = Callable[[str, str], str]


@dataclass(frozen=True, slots=True)
class Tags:
    """De qué va un clip, en etiquetas normalizadas."""

    #: El tema general del canal al que pertenecería: "streamers", "comedia".
    niche: str | None = None
    #: Quién sale, por su nombre buscable.
    people: tuple[str, ...] = ()
    #: De qué va: "among us", "gimnasio", "reto".
    topics: tuple[str, ...] = ()
    #: Qué clase de momento es. Uno de `MOMENT_KINDS`.
    kind: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "niche": self.niche,
            "people": list(self.people),
            "topics": list(self.topics),
            "kind": self.kind,
        }

    @property
    def is_empty(self) -> bool:
        return not (self.niche or self.people or self.topics or self.kind)


class RawTags(BaseModel):
    """Lo que el etiquetador devuelve para un clip."""

    model_config = ConfigDict(extra="ignore")

    clip: int = Field(description="Número del clip que se te ha dado")
    niche: str = Field(description="El tema del canal: streamers, comedia, motivacion…")
    people: list[str] = Field(description="Quién sale, por su nombre")
    topics: list[str] = Field(description="De qué va el momento")
    kind: str = Field(description="Qué clase de momento es")


class RawTagging(BaseModel):
    model_config = ConfigDict(extra="ignore")

    clips: list[RawTags] = Field(description="Una entrada por clip")


def tag_clips(
    clips: Sequence[ClipSuggestion],
    context: AnalysisContext,
    *,
    ask: Ask | None = None,
) -> list[Tags]:
    """Etiqueta todos los clips de un proyecto en una sola llamada.

    Devuelve una etiqueta por clip, en el mismo orden. Un fallo no es fatal:
    salen etiquetas vacías y el clip se publica igual, solo que sin poder
    repartirse por canales automáticamente.
    """
    pool = list(clips)
    if not pool or not settings.tagging_enabled:
        return [Tags() for _ in pool]

    started = time.perf_counter()
    request = ask or _ask_provider

    try:
        content = request(
            build_tagging_system_prompt(max_people=MAX_PEOPLE, max_topics=MAX_TOPICS),
            build_tagging_user_prompt(pool, context),
        )
        raw = _parse(content)
    except ExternalToolError as exc:
        logger.warning("ai.tagging_failed", error=exc.message)
        return [Tags() for _ in pool]

    tags = _same_niche([_validate(raw.get(index + 1)) for index in range(len(pool))])
    logger.info(
        "ai.tagged",
        clips=len(pool),
        tagged=sum(1 for tag in tags if not tag.is_empty),
        niches=sorted({tag.niche for tag in tags if tag.niche}),
        seconds=round(time.perf_counter() - started, 1),
    )
    return tags


# ------------------------------------------------------------------ privado
def _parse(content: str) -> dict[int, RawTags]:
    """Lee la respuesta del etiquetador, por número de clip.

    Raises:
        ExternalToolError: si no encaja con el esquema.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]

    try:
        payload = RawTagging.model_validate_json(text)
    except ValidationError as exc:
        raise ExternalToolError(
            "El etiquetador ha devuelto algo que no encaja con el esquema",
            details={"error": str(exc)[:400], "content": text[:400]},
        ) from exc

    return {entry.clip: entry for entry in payload.clips}


def _same_niche(tags: list[Tags]) -> list[Tags]:
    """Un solo nicho para todo el proyecto, el más votado.

    Medido sobre un vídeo real de recopilación: el modelo devolvió `fail`,
    `gag`, `reto`, `gag`, `gag` — un nicho distinto casi por clip, y con
    eso no se puede repartir nada, que era justo para lo que estaba.

    El nicho es una propiedad del VÍDEO, no del momento: los cinco clips
    salen de la misma fuente y van al mismo canal. La clase de momento sí
    varía —ahí es donde estaba la diferencia que el modelo veía— y esa se
    respeta clip a clip.
    """
    votes = Counter(tag.niche for tag in tags if tag.niche)
    if not votes:
        return tags

    # A empate, gana el primero que apareció: `most_common` conserva el
    # orden de inserción y así dos ejecuciones dan lo mismo.
    winner = votes.most_common(1)[0][0]
    return [replace(tag, niche=winner) if not tag.is_empty else tag for tag in tags]


def _validate(raw: RawTags | None) -> Tags:
    """Normaliza lo que devuelve el modelo a etiquetas que agrupan."""
    if raw is None:
        return Tags()

    kind = normalize(raw.kind)
    return Tags(
        niche=normalize(raw.niche) or None,
        people=_normalize_all(raw.people, limit=MAX_PEOPLE),
        topics=_normalize_all(raw.topics, limit=MAX_TOPICS),
        # Una clase de momento que no está en la lista no sirve para agrupar:
        # el objetivo era un vocabulario cerrado, no que cada clip invente el
        # suyo.
        kind=kind if kind in MOMENT_KINDS else None,
    )


def _normalize_all(values: Sequence[str], *, limit: int) -> tuple[str, ...]:
    """Normaliza, quita repetidos y corta por el tope."""
    seen: list[str] = []
    for value in values:
        tag = normalize(value)
        if tag and tag not in seen:
            seen.append(tag)
        if len(seen) >= limit:
            break
    return tuple(seen)


def normalize(value: str) -> str:
    """Deja una etiqueta comparable: minúsculas, sin acentos ni signos.

    Su único uso es agrupar, así que "Kai Cenat", "kai cenat" y "Kai-Cenat"
    tienen que caer en el mismo montón. Se conservan los espacios internos
    porque un nombre de dos palabras se lee mejor así que pegado.
    """
    text = unicodedata.normalize("NFKD", value or "")
    ascii_only = "".join(char for char in text if not unicodedata.combining(char))
    cleaned = _SEPARATORS.sub(" ", ascii_only.casefold()).strip()
    return cleaned[:MAX_TAG_CHARS].strip()


def _schema() -> dict[str, Any]:
    schema = RawTagging.model_json_schema()
    schema["additionalProperties"] = False
    return schema


def _ask_provider(system: str, user: str) -> str:
    """Le pide las etiquetas al modelo configurado para etiquetar."""
    return ask_json(
        system,
        user,
        schema=_schema(),
        choice=resolve_model(settings.ai_tagging_provider, settings.ai_tagging_model),
        temperature=0.0,
    )
