"""A qué canal va cada clip.

El etiquetador (fase 23) dice de qué va un clip; el canal declara qué quiere.
Aquí se cruzan las dos cosas.

La regla es simple y deliberadamente estricta: **todos los filtros que el canal
declara tienen que cumplirse**, y dentro de cada lista basta con uno. Un canal
que pide `people: [speed]` y `kinds: [fail, reaccion]` acepta un fail de Speed
y una reacción de Speed, pero no un fail de Kai Cenat.

Estricto a propósito. Un canal que se llena de contenido que casi encaja es
exactamente el problema que estos canales existen para evitar: el algoritmo
tarda mucho más en entender a quién enseñárselo. Ante la duda, el clip se queda
sin canal y lo reparte una persona.

Las etiquetas del clip vienen normalizadas del etiquetador —minúsculas, sin
acentos— y lo que escribe el usuario en el canal se normaliza igual al
compararlo. Si no, «Speed» y «speed» serían dos cosas distintas y el reparto
fallaría por una mayúscula.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from clipforge.core.logging import get_logger
from clipforge.services.ai.tagging import normalize

logger = get_logger(__name__)


class ChannelLike(Protocol):
    """Lo que el enrutador necesita de un canal.

    Un `Protocol` y no el modelo de base de datos: así se prueba con objetos
    sueltos y esta lógica no depende de SQLAlchemy.
    """

    name: str
    enabled: bool
    niche: str | None
    people: list[str] | None
    topics: list[str] | None
    kinds: list[str] | None
    min_score: float
    priority: int


@dataclass(frozen=True, slots=True)
class ClipFacts:
    """Lo que se sabe de un clip para repartirlo."""

    score: float
    niche: str | None = None
    people: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    kind: str | None = None

    @classmethod
    def from_tags(cls, tags: dict[str, Any] | None, *, score: float) -> ClipFacts:
        """Construye los datos a partir de lo que guardó el etiquetador."""
        data = tags or {}
        return cls(
            score=score,
            niche=_text(data.get("niche")),
            people=_texts(data.get("people")),
            topics=_texts(data.get("topics")),
            kind=_text(data.get("kind")),
        )


@dataclass(frozen=True, slots=True)
class Match:
    """El canal elegido y por qué."""

    channel: ChannelLike
    #: Cuántos filtros ha tenido que cumplir. A igual prioridad gana el que
    #: más pide: un canal específico debe ganarle a uno genérico.
    specificity: int


def route(clip: ClipFacts, channels: Sequence[ChannelLike]) -> Match | None:
    """Elige el canal de un clip, o None si no encaja en ninguno.

    No encajar es una respuesta legítima y frecuente: significa que ese clip lo
    reparte una persona, no que algo haya fallado.
    """
    matches = [
        Match(channel=channel, specificity=specificity)
        for channel in channels
        if channel.enabled
        for specificity in (_specificity(clip, channel),)
        if specificity is not None
    ]
    if not matches:
        return None

    # Prioridad primero —es la palanca explícita del usuario—, luego el que más
    # condiciones pedía, y a igualdad el nombre, para que dos ejecuciones
    # idénticas den el mismo reparto.
    matches.sort(key=lambda m: (m.channel.priority, m.specificity, m.channel.name), reverse=True)
    return matches[0]


def route_all(
    clips: Sequence[tuple[Any, ClipFacts]], channels: Sequence[ChannelLike]
) -> dict[Any, Match]:
    """Reparte varios clips de una vez, devolviendo solo los que encajan."""
    routed = {key: match for key, facts in clips for match in (route(facts, channels),) if match}
    logger.info("publish.routed", clips=len(clips), routed=len(routed))
    return routed


# ------------------------------------------------------------------ privado
def _specificity(clip: ClipFacts, channel: ChannelLike) -> int | None:
    """Cuántos filtros cumple, o None si incumple alguno.

    Devolver el número y no un booleano es lo que permite que un canal que pide
    tres cosas le gane a uno que no pide ninguna.
    """
    if clip.score < channel.min_score:
        return None

    filters = 0

    wanted_niche = _text(channel.niche)
    if wanted_niche:
        if normalize(wanted_niche) != (clip.niche or ""):
            return None
        filters += 1

    for wanted, present in (
        (channel.people, clip.people),
        (channel.topics, clip.topics),
    ):
        values = _texts(wanted)
        if not values:
            continue
        if not set(values) & set(present):
            return None
        filters += 1

    kinds = _texts(channel.kinds)
    if kinds:
        if (clip.kind or "") not in kinds:
            return None
        filters += 1

    return filters


def _text(value: object) -> str | None:
    """Un valor normalizado, o None si no hay nada que comparar."""
    if not isinstance(value, str):
        return None
    return normalize(value) or None


def _texts(values: object) -> tuple[str, ...]:
    """Una lista normalizada, sin vacíos ni repetidos."""
    if not isinstance(values, list | tuple):
        return ()
    seen: list[str] = []
    for value in values:
        text = _text(value)
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)
