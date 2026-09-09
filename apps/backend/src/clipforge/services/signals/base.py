"""Tipos y utilidades compartidas de las señales no verbales.

Un vídeo puede no tener una sola palabra transcribible y aun así estar lleno de
estructura: golpes, risas, cortes de plano y movimiento. Estas señales son lo
único de lo que dispone el análisis cuando la transcripción está vacía, y lo
que alimenta la línea de tiempo del editor manual.

Todo lo de aquí es serializable a JSON: la línea de tiempo se guarda en la
columna `projects.signals` y la consume tanto el analizador como el frontend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: `metadata=print` escribe dos tipos de línea: una con el instante del
#: fotograma y otra con el valor medido. Se parsean en pareja.
_TIME_LINE = re.compile(r"pts_time:\s*([0-9.]+)")
_VALUE_LINE = re.compile(r"=\s*(-?[0-9.]+|-?inf|nan)\s*$")

#: Nivel que se asigna a un tramo de silencio absoluto. ffmpeg escribe `-inf`,
#: que no es serializable a JSON y contamina cualquier media posterior.
SILENCE_DB = -90.0


@dataclass(frozen=True, slots=True)
class SamplePoint:
    """Una medida instantánea de una señal continua (energía o movimiento)."""

    time: float
    value: float

    def to_dict(self) -> dict[str, float]:
        return {"t": round(self.time, 2), "v": round(self.value, 2)}


@dataclass(frozen=True, slots=True)
class EnergyPeak:
    """Un máximo local de volumen: un golpe, una risa, un remate musical."""

    time: float
    level: float
    #: Cuánto sobresale del nivel de fondo, ya normalizado a 0..1.
    prominence: float

    def to_dict(self) -> dict[str, float]:
        return {
            "t": round(self.time, 2),
            "db": round(self.level, 2),
            "p": round(self.prominence, 3),
        }


@dataclass(frozen=True, slots=True)
class MomentBlock:
    """Un tramo candidato a clip, derivado solo de señales.

    No lo ha juzgado ninguna IA: es geometría del vídeo (dónde están los cortes)
    más física del audio (dónde están los picos). Sirve como propuesta para el
    editor manual y como unidad de análisis para el modelo de visión.
    """

    start: float
    end: float
    #: Volumen medio del tramo, normalizado a 0..1 contra el resto del vídeo.
    energy: float
    #: Movimiento medio del tramo, normalizado a 0..1.
    motion: float
    #: Picos de volumen que caen dentro del tramo.
    peaks: int
    #: Cortes de plano por minuto dentro del tramo.
    cut_rate: float
    #: Puntuación combinada 0..100. Solo ordena; no es una nota de viralidad.
    score: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, float]:
        return {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "energy": round(self.energy, 3),
            "motion": round(self.motion, 3),
            "peaks": self.peaks,
            "cut_rate": round(self.cut_rate, 2),
            "score": round(self.score, 1),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MomentBlock:
        return cls(
            start=float(data["start"]),
            end=float(data["end"]),
            energy=float(data.get("energy", 0.0)),
            motion=float(data.get("motion", 0.0)),
            peaks=int(data.get("peaks", 0)),
            cut_rate=float(data.get("cut_rate", 0.0)),
            score=float(data.get("score", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class SignalTimeline:
    """Todas las señales de un vídeo, listas para guardar y para pintar."""

    duration: float
    energy: list[SamplePoint]
    peaks: list[EnergyPeak]
    cuts: list[float]
    motion: list[SamplePoint]
    blocks: list[MomentBlock]

    def to_dict(self) -> dict[str, Any]:
        """Forma compacta para JSONB. Las curvas van ya submuestreadas."""
        return {
            "version": 1,
            "duration": round(self.duration, 2),
            "energy": [point.to_dict() for point in self.energy],
            "peaks": [peak.to_dict() for peak in self.peaks],
            "cuts": [round(cut, 2) for cut in self.cuts],
            "motion": [point.to_dict() for point in self.motion],
            "blocks": [block.to_dict() for block in self.blocks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignalTimeline:
        return cls(
            duration=float(data.get("duration", 0.0)),
            energy=[SamplePoint(float(p["t"]), float(p["v"])) for p in data.get("energy", [])],
            peaks=[
                EnergyPeak(float(p["t"]), float(p["db"]), float(p.get("p", 0.0)))
                for p in data.get("peaks", [])
            ],
            cuts=[float(c) for c in data.get("cuts", [])],
            motion=[SamplePoint(float(p["t"]), float(p["v"])) for p in data.get("motion", [])],
            blocks=[MomentBlock.from_dict(b) for b in data.get("blocks", [])],
        )


def parse_metadata_stream(text: str) -> list[SamplePoint]:
    """Convierte la salida de `metadata=print` en una serie temporal.

    El formato alterna una línea con el instante del fotograma y otra con el
    valor medido:

        frame:0  pts:0  pts_time:0
        lavfi.astats.Overall.RMS_level=-18.387442

    Los valores no numéricos (`-inf` en un silencio absoluto, `nan` en el primer
    fotograma de una diferencia) se normalizan en lugar de descartarse: dejar
    huecos en la serie descoloca cualquier media por ventana posterior.
    """
    points: list[SamplePoint] = []
    current_time: float | None = None

    for line in text.splitlines():
        time_match = _TIME_LINE.search(line)
        if time_match:
            current_time = float(time_match.group(1))
            continue

        if current_time is None:
            continue
        value_match = _VALUE_LINE.search(line)
        if value_match is None:
            continue

        raw = value_match.group(1)
        if raw in ("-inf", "inf"):
            value = SILENCE_DB
        elif raw == "nan":
            value = 0.0
        else:
            value = float(raw)
        points.append(SamplePoint(time=current_time, value=value))
        current_time = None

    return points


def downsample(points: list[SamplePoint], limit: int) -> list[SamplePoint]:
    """Reduce una serie a como mucho `limit` puntos, quedándose con los máximos.

    Se conserva el máximo de cada tramo y no la media: en una curva de energía
    lo que interesa dibujar es el pico, y promediar lo aplanaría justo donde la
    señal importa.
    """
    if limit <= 0 or len(points) <= limit:
        return points

    bucket_size = len(points) / limit
    reduced: list[SamplePoint] = []
    for index in range(limit):
        start = int(index * bucket_size)
        end = max(start + 1, int((index + 1) * bucket_size))
        bucket = points[start:end]
        if bucket:
            reduced.append(max(bucket, key=lambda point: point.value))
    return reduced


def normalize(value: float, low: float, high: float) -> float:
    """Lleva `value` al rango 0..1 dentro de [low, high], sin salirse."""
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))
