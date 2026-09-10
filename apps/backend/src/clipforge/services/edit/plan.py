"""El montaje de un clip, descrito antes de tocar un solo fotograma.

Hasta ahora un clip era **un rango continuo** del original: entrada, salida y a
codificar. Eso funciona mientras el clip sea el original recortado, y deja de
funcionar en cuanto se quiere editar de verdad: quitar un silencio, repetir un
momento, congelar un fotograma. En el instante en que se elimina un trozo de en
medio, la línea de tiempo del clip **deja de ser la del original**, y todo lo
que depende de tiempos —los subtítulos, el gancho en pantalla, el encuadre—
empieza a apuntar al sitio equivocado.

Un `EditPlan` es la lista ordenada de tramos del original que sobreviven al
montaje. Con ella se puede traducir cualquier instante del original al instante
en que aparece en el clip final, que es justamente lo que hacía falta para que
los demás efectos puedan componerse sin pisarse.

Un plan de un solo `Beat` es exactamente lo de siempre, y por eso el camino
antiguo se conserva intacto: si nadie ha cortado nada, no hay nada nuevo que
pueda romperse.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

#: Por debajo de esto dos tramos son el mismo: unirlos evita cortes de un
#: fotograma que se ven como un parpadeo y no como un montaje.
MIN_GAP_TO_SPLIT = 0.04


@dataclass(frozen=True, slots=True)
class Beat:
    """Un tramo del original que se queda en el clip.

    Los tiempos son SIEMPRE del vídeo original. La traducción al tiempo del
    clip la hace el plan, que es el único que sabe qué hay antes.
    """

    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True, slots=True)
class EditPlan:
    """Los tramos que componen el clip, en orden."""

    beats: tuple[Beat, ...]

    @classmethod
    def single(cls, start: float, end: float) -> EditPlan:
        """El plan de toda la vida: un rango continuo, sin cortes."""
        return cls(beats=(Beat(start=start, end=end),))

    @classmethod
    def of(cls, beats: Sequence[Beat]) -> EditPlan:
        """Construye un plan uniendo lo que en realidad es continuo.

        Dos tramos separados por dos centésimas no son un corte: son el mismo
        tramo con una costura que solo se vería como un parpadeo.
        """
        ordered = sorted((beat for beat in beats if beat.duration > 0), key=lambda b: b.start)
        if not ordered:
            return cls(beats=())

        merged = [ordered[0]]
        for beat in ordered[1:]:
            last = merged[-1]
            if beat.start - last.end <= MIN_GAP_TO_SPLIT:
                merged[-1] = Beat(start=last.start, end=max(last.end, beat.end))
            else:
                merged.append(beat)

        return cls(beats=tuple(merged))

    # ------------------------------------------------------------- medidas
    @property
    def is_continuous(self) -> bool:
        """¿Es el clip de siempre, sin nada quitado por dentro?"""
        return len(self.beats) <= 1

    @property
    def source_start(self) -> float:
        return self.beats[0].start if self.beats else 0.0

    @property
    def source_end(self) -> float:
        return self.beats[-1].end if self.beats else 0.0

    @property
    def source_duration(self) -> float:
        """Cuánto ocupa en el original, cortes incluidos."""
        return max(0.0, self.source_end - self.source_start)

    @property
    def duration(self) -> float:
        """Cuánto dura el clip resultante."""
        return sum(beat.duration for beat in self.beats)

    @property
    def removed(self) -> float:
        """Segundos que se han quitado por dentro."""
        return max(0.0, self.source_duration - self.duration)

    # ------------------------------------------------------------- tiempos
    def offsets(self) -> Iterator[tuple[Beat, float]]:
        """Cada tramo con el instante del clip en el que empieza."""
        elapsed = 0.0
        for beat in self.beats:
            yield beat, elapsed
            elapsed += beat.duration

    def map_time(self, source_time: float) -> float | None:
        """Traduce un instante del original al del clip.

        Devuelve None si ese instante cae en un trozo eliminado: no está en el
        clip, y devolver el tiempo más cercano haría que un subtítulo o un
        rótulo apareciesen donde no toca fingiendo precisión.
        """
        for beat, offset in self.offsets():
            if beat.start <= source_time <= beat.end:
                return round(offset + (source_time - beat.start), 3)
        return None

    def spans_for(self, start: float, end: float) -> list[tuple[float, float, float]]:
        """Trocea un rango del original en `(inicio, fin, desfase)` por tramo.

        Un subtítulo puede cruzar un corte: en el original ocupa cuatro
        segundos y en el clip aparece partido en dos. Devolver los trozos deja
        que quien llama decida qué hacer con cada uno.
        """
        pieces: list[tuple[float, float, float]] = []
        for beat, offset in self.offsets():
            piece_start = max(start, beat.start)
            piece_end = min(end, beat.end)
            if piece_end - piece_start > 0:
                pieces.append((piece_start, piece_end, offset - beat.start))
        return pieces
