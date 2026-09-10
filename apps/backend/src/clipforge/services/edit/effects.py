"""Efectos visuales colocados donde de verdad pasa algo.

La idea de partida era que un modelo decidiera dónde poner cada zoom. Se
descartó por una razón medida, no por gusto: el modelo local que hay detrás
puntúa cinco clips casi idénticos y sustituye una cita textual por una
descripción. Un motor caro que le pregunte dónde acercar la cámara pondría el
zoom en el sitio equivocado, y **un efecto mal puesto es peor que ningún
efecto**.

Así que los efectos no se preguntan: se **miden**. El pipeline lleva desde la
fase 7 una curva de volumen con sus picos y su prominencia, y un pico es
exactamente lo que es un golpe, una risa o un grito. Un acercamiento que cae
sobre el pico real está motivado por el contenido; uno que cae donde lo dijo un
modelo es decoración, y decoración es lo que YouTube llama contenido reutilizado.

Tres reglas que separan el montaje del parpadeo:

- **Pocos.** Un tope por clip. Si todo se subraya, no se subraya nada.
- **Separados.** Dos acercamientos seguidos son un temblor, no un énfasis.
- **Fuera de los extremos.** El primer segundo lo ocupa el gancho y necesita el
  plano limpio; el último es el remate y moverlo lo estropea.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from clipforge.core.logging import get_logger
from clipforge.services.edit.plan import EditPlan

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PunchIn:
    """Un acercamiento momentáneo, en tiempos del CLIP ya montado."""

    #: Instante en el que el acercamiento está en su punto máximo.
    at: float
    #: 1.12 = un doce por ciento más cerca.
    zoom: float
    #: Cuánto tarda en entrar y en salir. Sin rampa es un salto, y un salto
    #: se lee como un fallo de reproducción.
    ramp: float
    #: Cuánto se mantiene arriba antes de volver.
    hold: float

    @property
    def start(self) -> float:
        return max(0.0, self.at - self.ramp)

    @property
    def end(self) -> float:
        return self.at + self.hold + self.ramp


@dataclass(frozen=True, slots=True)
class PunchRules:
    """Cuándo un pico merece un acercamiento."""

    #: Prominencia mínima del pico, 0..1. Por debajo es conversación normal.
    min_prominence: float = 0.45
    #: Tope por clip.
    max_punches: int = 3
    #: Separación mínima entre dos acercamientos.
    min_spacing: float = 5.0
    #: Margen intocable al principio y al final.
    edge_margin: float = 1.5
    zoom: float = 1.12
    ramp: float = 0.35
    hold: float = 0.5


@dataclass(frozen=True, slots=True)
class Peak:
    """Un pico de volumen medido, en tiempos del ORIGINAL."""

    time: float
    prominence: float


def plan_punch_ins(
    edit: EditPlan, peaks: Sequence[Peak], *, rules: PunchRules | None = None
) -> tuple[PunchIn, ...]:
    """Coloca acercamientos sobre los picos que caen dentro del clip.

    Los tiempos de los picos son del original; se traducen por el `EditPlan`,
    igual que los rótulos. Un pico que cae dentro de un trozo eliminado se
    descarta: el golpe que lo justificaba ya no está en el vídeo.
    """
    conf = rules or PunchRules()
    if conf.max_punches <= 0 or edit.duration <= 2 * conf.edge_margin:
        return ()

    candidates: list[tuple[float, float]] = []
    for peak in sorted(peaks, key=lambda item: -item.prominence):
        if peak.prominence < conf.min_prominence:
            continue
        at = edit.map_time(peak.time)
        if at is None:
            continue
        if at < conf.edge_margin or at > edit.duration - conf.edge_margin:
            continue
        candidates.append((at, peak.prominence))

    # Se recorren de más prominente a menos, así que el que gana un hueco es
    # siempre el golpe más fuerte de esa zona.
    chosen: list[float] = []
    for at, _ in candidates:
        if any(abs(at - taken) < conf.min_spacing for taken in chosen):
            continue
        chosen.append(at)
        if len(chosen) >= conf.max_punches:
            break

    punches = tuple(
        PunchIn(at=at, zoom=conf.zoom, ramp=conf.ramp, hold=conf.hold) for at in sorted(chosen)
    )
    if punches:
        logger.info(
            "effects.punch_ins",
            count=len(punches),
            at=[round(punch.at, 1) for punch in punches],
        )
    return punches


def zoom_expression(punches: Sequence[PunchIn], fps: float) -> str:
    """Expresión de zoom para `zoompan`, en función del fotograma de salida.

    Se escribe sobre `on` —el número de fotograma— y no sobre el tiempo porque
    `zoompan` expone el contador de fotogramas en todas las versiones, mientras
    que las variables de tiempo han ido cambiando de nombre. Dividir por los
    fps del clip da lo mismo y no depende de la versión de ffmpeg instalada.

    La forma de cada acercamiento es un trapecio: sube en `ramp`, se mantiene
    `hold` y baja en `ramp`. Sin las rampas el zoom entra de golpe y se ve como
    un fallo, no como un énfasis.
    """
    if not punches or fps <= 0:
        return "1"

    terms: list[str] = []
    for punch in punches:
        rise = punch.zoom - 1.0
        # `t` local en segundos, a partir del contador de fotogramas.
        time = f"(on/{fps:.5f})"
        up = f"({time}-{punch.start:.3f})/{punch.ramp:.3f}"
        down = f"({punch.end:.3f}-{time})/{punch.ramp:.3f}"
        shape = f"min(1,min({up},{down}))"
        terms.append(
            f"if(between({time},{punch.start:.3f},{punch.end:.3f}),{rise:.4f}*max(0,{shape}),0)"
        )

    # Los acercamientos no se solapan —el planificador los separa— así que
    # sumarlos es seguro y se lee mucho mejor que un if anidado.
    return f"1+{'+'.join(terms)}" if len(terms) > 1 else f"1+{terms[0]}"


def zoompan_filter(punches: Sequence[PunchIn], *, width: int, height: int, fps: float) -> str:
    """Filtro `zoompan` completo, ya centrado.

    `d=1` significa un fotograma de salida por cada uno de entrada: `zoompan`
    nació para hacer travellings sobre fotos fijas y por defecto repite cada
    fotograma, que sobre vídeo lo dejaría a cámara lenta.
    """
    zoom = zoom_expression(punches, fps)
    return (
        f"zoompan=z='{zoom}'"
        # El acercamiento va al centro del encuadre: la ventana vertical ya
        # sigue al sujeto, así que el centro es donde está la cara.
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s={width}x{height}:fps={fps:.5f}"
    )


def peaks_from_signals(raw: Sequence[dict[str, object]]) -> list[Peak]:
    """Traduce los picos guardados en `projects.signals`.

    Se salta lo que venga incompleto: un pico sin instante colocaría un
    acercamiento en el segundo cero, encima del gancho.
    """
    peaks: list[Peak] = []
    for item in raw:
        time = item.get("t")
        if not isinstance(time, int | float):
            continue
        prominence = item.get("p")
        peaks.append(
            Peak(
                time=float(time),
                prominence=float(prominence) if isinstance(prominence, int | float) else 0.0,
            )
        )
    return peaks
