"""Quitar de un clip todo lo que no aporta.

Es la transformación con mejor relación esfuerzo/retención de todas las que se
pueden hacer sobre metraje ajeno, y con diferencia. Un clip de setenta y cinco
segundos con nueve pausas de segundo y medio son trece segundos en los que no
pasa nada; en un Short, cada una de esas pausas es un dedo subiendo.

Los datos ya estaban ahí y no se usaban: Whisper guarda el tiempo de **cada
palabra** (`TranscriptSegment.words`). Los huecos entre palabras son el silencio
real, medido, sin volver a analizar el audio.

Tres reglas que evitan que el remedio sea peor:

- **Se corta por el hueco, no por la palabra.** Se deja un margen a cada lado
  para no comerse la consonante inicial ni la respiración final, que es lo que
  hace que un montaje suene atropellado.
- **Ningún tramo puede quedar diminuto.** Una sucesión de trozos de tres
  décimas no es ritmo, es un tartamudeo.
- **Hay un tope de cuánto se puede quitar.** Si un clip es medio silencio, el
  problema es la selección del momento, no el montaje; cortarlo hasta dejarlo
  irreconocible lo empeora y además esconde el fallo de más arriba.

No se aplica al perfil visual, y es a propósito: en una caída, un tropiezo o un
gag físico **el silencio es parte del chiste**. Cortarlo por "no aportar" es
justo lo que arruina el tiempo cómico.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from clipforge.core.logging import get_logger
from clipforge.services.edit.plan import Beat, EditPlan

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Word:
    """Una palabra con sus tiempos en el vídeo original."""

    start: float
    end: float
    text: str = ""


@dataclass(frozen=True, slots=True)
class TrimRules:
    """Cuánto hay que callarse para que merezca la pena cortar."""

    #: Hueco mínimo entre palabras para considerarlo tiempo muerto. Por debajo
    #: de medio segundo casi todo son pausas naturales del habla, y quitarlas
    #: hace que suene a robot.
    min_gap: float = 0.5
    #: Margen que se deja a cada lado del corte.
    padding: float = 0.12
    #: Duración mínima de un tramo tras cortar.
    min_beat: float = 0.4
    #: Fracción máxima del clip que se puede eliminar.
    max_removed_ratio: float = 0.35

    @property
    def min_removable(self) -> float:
        """Un hueco por debajo de esto no deja nada que quitar tras el margen."""
        return self.min_gap - 2 * self.padding


def plan_trim(
    words: Sequence[Word], *, start: float, end: float, rules: TrimRules | None = None
) -> EditPlan:
    """Devuelve el montaje del clip con el tiempo muerto fuera.

    Sin palabras dentro del rango devuelve el plan continuo de siempre: no se
    sabe dónde está el silencio, y adivinarlo sería peor que no cortar.
    """
    rules = rules or TrimRules()
    span = end - start
    if span <= 0:
        return EditPlan.single(start, end)

    inside = sorted(
        (word for word in words if word.end > start and word.start < end),
        key=lambda word: word.start,
    )
    if not inside:
        return EditPlan.single(start, end)

    # Las puntas y el interior no compiten por el mismo presupuesto, y es
    # deliberado. Quitar el silencio de delante y de detrás no es editar el
    # contenido: es elegir bien la entrada y la salida, que es lo primero
    # que hace cualquier montador. Lo que se acota es cuánto se puede
    # quitar POR DENTRO, que ahí sí se está tocando el discurso.
    edges = _edge_cuts(inside, start=start, end=end, rules=rules)
    inner = _within_budget(_inner_cuts(inside, rules=rules), budget=span * rules.max_removed_ratio)

    cuts = sorted([*edges, *inner])
    if not cuts:
        return EditPlan.single(start, end)

    plan = _plan_without(cuts, start=start, end=end, rules=rules)

    logger.info(
        "trim.planned",
        beats=len(plan.beats),
        removed=round(plan.removed, 2),
        before=round(span, 2),
        after=round(plan.duration, 2),
    )
    return plan


def _edge_cuts(
    words: Sequence[Word], *, start: float, end: float, rules: TrimRules
) -> list[tuple[float, float]]:
    """El silencio de delante y de detrás.

    El de delante es el peor de todos: son justo los segundos en los que se
    decide si alguien se queda mirando, y regalarlos a una pausa no tiene
    ninguna defensa.
    """
    cuts: list[tuple[float, float]] = []

    if words[0].start - start >= rules.min_gap:
        cuts.append((start, words[0].start - rules.padding))

    # Algo más de margen por detrás: cortar justo al acabar de hablar se oye
    # como si el vídeo se hubiera roto.
    if end - words[-1].end >= rules.min_gap:
        cuts.append((words[-1].end + rules.padding * 2, end))

    return cuts


def _inner_cuts(words: Sequence[Word], *, rules: TrimRules) -> list[tuple[float, float]]:
    """Los huecos entre palabras, ya con el margen aplicado."""
    cuts: list[tuple[float, float]] = []

    for previous, following in pairwise(words):
        if following.start - previous.end < rules.min_gap:
            continue
        cut_start = previous.end + rules.padding
        cut_end = following.start - rules.padding
        if cut_end - cut_start > 0:
            cuts.append((cut_start, cut_end))

    return cuts


def _within_budget(
    cuts: Sequence[tuple[float, float]], *, budget: float
) -> list[tuple[float, float]]:
    """Se queda con los cortes que caben dentro del tope, los mayores primero.

    Un clip que es medio silencio delata un problema de selección, no de
    montaje, y por eso hay un tope. Pero renunciar a cortar por pasarse dos
    segundos deja al espectador el clip entero con todas sus pausas, que es
    el peor de los dos mundos. Se quitan los huecos más grandes hasta llegar
    al límite: los que más molestan, sin pasarse.
    """
    kept: list[tuple[float, float]] = []
    spent = 0.0

    for cut in sorted(cuts, key=lambda cut: cut[1] - cut[0], reverse=True):
        length = cut[1] - cut[0]
        if spent + length > budget:
            continue
        kept.append(cut)
        spent += length

    # De vuelta al orden del vídeo: quien los aplica recorre la línea de
    # tiempo de principio a fin.
    return sorted(kept)


def _plan_without(
    cuts: Sequence[tuple[float, float]], *, start: float, end: float, rules: TrimRules
) -> EditPlan:
    """Convierte "lo que se quita" en "lo que se queda"."""
    beats: list[Beat] = []
    cursor = start

    for cut_start, cut_end in cuts:
        if cut_start > cursor:
            beats.append(Beat(start=cursor, end=cut_start))
        cursor = max(cursor, cut_end)

    if end > cursor:
        beats.append(Beat(start=cursor, end=end))

    # Los tramos diminutos se descartan enteros: mejor perder tres décimas de
    # una muletilla que dejar un pestañeo entre dos cortes.
    return EditPlan.of([beat for beat in beats if beat.duration >= rules.min_beat])


def words_from_segments(raw: Sequence[dict[str, object]]) -> list[Word]:
    """Traduce los diccionarios de palabras de Whisper a algo con tipos.

    Se salta lo que venga sin tiempos: faster-whisper devuelve alguna palabra
    incompleta y una sola de ellas bastaría para colocar un corte donde no toca.
    """
    words: list[Word] = []
    for item in raw:
        start = item.get("start")
        end = item.get("end")
        if not isinstance(start, int | float) or not isinstance(end, int | float):
            continue
        if end <= start:
            continue
        text = item.get("word") or item.get("text") or ""
        words.append(Word(start=float(start), end=float(end), text=str(text).strip()))
    return words
