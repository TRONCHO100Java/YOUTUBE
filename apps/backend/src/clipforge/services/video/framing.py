"""Dónde poner la ventana vertical dentro del fotograma original.

El recorte centrado que había hasta ahora es correcto para un plano medio de
alguien hablando, y desastroso para el resto: en un plano general de comedia
física con dos personas, centrar deja a una fuera del encuadre justo cuando lo
gracioso es la reacción del otro.

La pregunta que se responde aquí **no es "dónde está el punto medio del sujeto"
sino "qué franja vertical concentra más de lo que importa"**. La diferencia no
es sutil: con dos personas en los extremos del plano, el punto medio cae entre
las dos y la ventana no coge a ninguna. Buscar la franja con más peso coge a
una entera, que es lo que quiere el espectador.

Lo que pesa, en orden:

1. **Caras.** Es lo que busca el ojo, y en contenido hablado es todo lo que
   importa. Se detectan de frente y de perfil.
2. **Movimiento.** Cuando no hay caras utilizables —planos generales, gente de
   espaldas, cámara lejos— el sujeto es lo que se mueve. En comedia física eso
   es casi siempre el remate.
3. **El centro.** Si el fotograma no tiene ni una cosa ni la otra, se centra,
   que es lo que se hacía antes.

La detección es deliberadamente barata: fotogramas en escala de grises a 480 px
sacados de ffmpeg, dos por segundo. No hace falta más para decidir sobre qué
tercio del fotograma va una ventana de 606 píxeles de ancho.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from clipforge.core.config import settings
from clipforge.core.logging import get_logger
from clipforge.services.video.binaries import run_tool_binary
from clipforge.services.video.crop import CropWindow, center_crop_within

logger = get_logger(__name__)

SAMPLE_TIMEOUT_SECONDS = 10 * 60

#: Diferencia mínima entre dos fotogramas para contar como movimiento y no como
#: ruido de compresión. En unidades de píxel (0-255).
MOTION_PIXEL_THRESHOLD = 14

#: Cuánto pesa una cara frente al movimiento. Alto a propósito: si hay una cara
#: reconocible, el encuadre va sobre ella aunque la acción esté en otro lado.
FACE_WEIGHT = 4.0
MOTION_WEIGHT = 1.0

#: Un perfil de importancia tan plano como este no dice nada: la mejor franja y
#: la peor se diferencian en menos de esta fracción, así que se centra.
FLATNESS_THRESHOLD = 0.08


class FocusSource(StrEnum):
    """De dónde salió la posición elegida."""

    FACE = "face"
    MOTION = "motion"
    CENTER = "center"


@dataclass(frozen=True, slots=True)
class FocusSample:
    """La mejor posición de la ventana en un instante, en píxeles del original."""

    time: float
    x: float
    source: FocusSource


@dataclass(frozen=True, slots=True)
class FocusTrack:
    """Recorrido de la ventana a lo largo de un clip."""

    samples: list[FocusSample]
    #: Perfil de importancia acumulado de todo el clip, por columnas del
    #: fotograma reducido. Es lo que decide el encuadre estático.
    profile: np.ndarray
    #: Escala aplicada al analizar, para volver a coordenadas del original.
    scale: float
    source: FocusSource = FocusSource.CENTER

    @property
    def faces(self) -> int:
        return sum(1 for sample in self.samples if sample.source is FocusSource.FACE)

    @property
    def travel(self) -> float:
        """Cuánto se desplaza la ventana de un extremo a otro, en píxeles."""
        if len(self.samples) < 2:
            return 0.0
        positions = [sample.x for sample in self.samples]
        return max(positions) - min(positions)


@dataclass(frozen=True, slots=True)
class CropPlan:
    """Ventana de recorte final, estática o con paneo.

    Cumple el mismo contrato que `CropWindow` (`to_filter()`), así que el render
    no necesita saber cuál de las dos ha recibido.
    """

    window: CropWindow
    #: Pares (segundo dentro del clip, x). Vacío = ventana fija.
    keyframes: tuple[tuple[float, int], ...] = ()
    source: FocusSource = FocusSource.CENTER

    def to_filter(self) -> str:
        if not self.keyframes:
            return self.window.to_filter()
        return (
            f"crop={self.window.width}:{self.window.height}:"
            f"{_piecewise_expression(self.keyframes)}:{self.window.y}"
        )


# --------------------------------------------------------------------- muestreo
def sample_frames(
    video: Path,
    *,
    start: float,
    end: float,
    source_width: int,
    source_height: int,
) -> tuple[np.ndarray, float]:
    """Extrae fotogramas en gris de un tramo del vídeo.

    Devuelve el montón de fotogramas `(n, alto, ancho)` y la escala aplicada,
    para poder traducir las coordenadas de vuelta al vídeo original.

    Raises:
        ExternalToolError: si ffmpeg falla o no está instalado.
    """
    duration = end - start
    if duration <= 0 or source_width <= 0 or source_height <= 0:
        return np.empty((0, 0, 0), dtype=np.uint8), 1.0

    width = min(settings.smart_crop_analysis_width, source_width)
    width -= width % 2
    scale = width / source_width
    height = max(2, round(source_height * scale))
    height -= height % 2

    fps = settings.smart_crop_sample_fps
    frames = min(settings.smart_crop_max_samples, max(2, int(duration * fps)))

    command = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-v",
        "error",
        # -ss antes de -i busca por el índice del contenedor: instantáneo aunque
        # el fichero pese gigabytes.
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(video),
        "-vf",
        f"fps={fps},scale={width}:{height}",
        "-frames:v",
        str(frames),
        "-pix_fmt",
        "gray",
        "-f",
        "rawvideo",
        "-",
    ]
    raw = run_tool_binary(command, tool_name="ffmpeg", timeout=SAMPLE_TIMEOUT_SECONDS)

    frame_bytes = width * height
    count = len(raw) // frame_bytes if frame_bytes else 0
    if count == 0:
        return np.empty((0, height, width), dtype=np.uint8), scale

    stack = np.frombuffer(raw[: count * frame_bytes], dtype=np.uint8)
    return stack.reshape(count, height, width), scale


# ----------------------------------------------------------------------- caras
@lru_cache(maxsize=1)
def _cascades() -> tuple[Any, ...]:
    """Detectores de cara de OpenCV, cargados una vez por proceso.

    Van de frente y de perfil: en una conversación grabada de lado, el detector
    frontal no encuentra nada y el encuadre se iría al centro por defecto.

    Si OpenCV no está instalado se devuelve una tupla vacía y todo el módulo
    sigue funcionando solo con movimiento. Es una degradación aceptable: el
    encuadre empeora, pero nada se rompe.
    """
    try:
        import cv2
    except ImportError:
        logger.warning("framing.opencv_missing", detail="el encuadre usará solo movimiento")
        return ()

    # `cv2.data` no lleva anotaciones en los stubs, pero es la forma oficial de
    # localizar las cascadas que vienen dentro del propio paquete.
    cascade_dir = Path(cv2.data.haarcascades)  # type: ignore[attr-defined]

    loaded = []
    for name in ("haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml"):
        classifier = cv2.CascadeClassifier(str(cascade_dir / name))
        if not classifier.empty():
            loaded.append(classifier)
        else:
            logger.warning("framing.cascade_missing", cascade=name)
    return tuple(loaded)


def face_weights(frame: np.ndarray) -> np.ndarray | None:
    """Peso por columna de las caras del fotograma, o None si no hay ninguna.

    Cada cara reparte su área entre las columnas que ocupa. Así dos caras
    producen dos montículos separados y la ventana puede caer sobre uno de los
    dos, en lugar de en el valle que queda entre ambos.
    """
    detectors = _cascades()
    if not detectors or frame.size == 0:
        return None

    import cv2

    equalized = cv2.equalizeHist(frame)
    minimum = max(16, frame.shape[1] // 24)

    weights = np.zeros(frame.shape[1], dtype=np.float64)
    found = False
    for detector in detectors:
        for x, _y, w, h in detector.detectMultiScale(
            equalized, scaleFactor=1.1, minNeighbors=5, minSize=(minimum, minimum)
        ):
            left = max(0, int(x))
            right = min(frame.shape[1], int(x + w))
            if right <= left:
                continue
            # El área premia a la cara más grande, que suele ser el sujeto: está
            # más cerca de la cámara.
            weights[left:right] += float(w * h)
            found = True

    return weights if found else None


# ------------------------------------------------------------------ movimiento
def motion_weights(previous: np.ndarray, current: np.ndarray) -> np.ndarray | None:
    """Peso por columna de lo que se ha movido entre dos fotogramas.

    Es la señal que salva los planos generales sin caras reconocibles, que es
    justo el material para el que el recorte centrado fallaba más.
    """
    if previous.shape != current.shape or previous.size == 0:
        return None

    difference = np.abs(current.astype(np.int16) - previous.astype(np.int16))
    # El umbral quita el ruido de compresión, que está repartido por todo el
    # fotograma y aplanaría el perfil hasta volverlo inútil.
    difference[difference < MOTION_PIXEL_THRESHOLD] = 0

    columns = difference.sum(axis=0).astype(np.float64)
    return columns if columns.sum() > 0 else None


# ------------------------------------------------------------------- perfiles
def frame_profiles(frames: np.ndarray) -> tuple[np.ndarray, list[FocusSource]]:
    """Perfil de importancia por columna de cada fotograma.

    Cada fila se normaliza antes de combinarse: sin eso, un fotograma con mucho
    movimiento pesaría más que uno con una cara clarísima solo porque los
    números de la diferencia de píxeles son más grandes.
    """
    if len(frames) == 0:
        return np.empty((0, 0), dtype=np.float64), []

    width = frames.shape[2]
    profiles = np.zeros((len(frames), width), dtype=np.float64)
    sources: list[FocusSource] = []

    for index, frame in enumerate(frames):
        row = np.zeros(width, dtype=np.float64)
        source = FocusSource.CENTER

        faces = face_weights(frame)
        if faces is not None and faces.sum() > 0:
            row += FACE_WEIGHT * faces / faces.sum()
            source = FocusSource.FACE

        if index > 0:
            motion = motion_weights(frames[index - 1], frame)
            if motion is not None:
                row += MOTION_WEIGHT * motion / motion.sum()
                if source is FocusSource.CENTER:
                    source = FocusSource.MOTION

        profiles[index] = row
        sources.append(source)

    return profiles, sources


def best_offset(profile: np.ndarray, window: int) -> int | None:
    """Columna donde empieza la franja de `window` columnas con más peso.

    Es una suma deslizante resuelta con la suma acumulada, así que cuesta lo
    mismo mirar todas las posiciones que mirar una.

    Devuelve None si el perfil está tan plano que la elección sería arbitraria:
    en ese caso es más honesto centrar que fingir que se ha decidido algo.
    """
    if profile.size == 0 or window <= 0:
        return None
    if window >= profile.size:
        return 0

    cumulative = np.concatenate(([0.0], np.cumsum(profile)))
    totals = cumulative[window:] - cumulative[:-window]
    if totals.size == 0:
        return None

    best, worst = float(totals.max()), float(totals.min())
    if best <= 0:
        return None
    if (best - worst) / best < FLATNESS_THRESHOLD:
        return None

    return int(np.argmax(totals))


# ------------------------------------------------------------------ seguimiento
def build_track(
    video: Path,
    *,
    start: float,
    end: float,
    source_width: int,
    source_height: int,
    window_width: int,
) -> FocusTrack:
    """Sigue la mejor franja del fotograma a lo largo del clip.

    Nunca propaga un fallo: sin seguimiento el encuadre vuelve al centrado de
    siempre, que es peor pero perfectamente utilizable.
    """
    empty = FocusTrack(samples=[], profile=np.empty(0), scale=1.0)
    try:
        frames, scale = sample_frames(
            video,
            start=start,
            end=end,
            source_width=source_width,
            source_height=source_height,
        )
    except Exception as exc:  # el encuadre nunca debe tumbar el render
        logger.warning("framing.sampling_failed", error=str(exc))
        return empty

    if len(frames) == 0 or scale <= 0:
        return empty

    profiles, sources = frame_profiles(frames)
    scaled_window = max(1, round(window_width * scale))
    step = 1.0 / settings.smart_crop_sample_fps

    samples: list[FocusSample] = []
    for index, (row, source) in enumerate(zip(profiles, sources, strict=True)):
        offset = best_offset(row, scaled_window)
        if offset is None:
            continue
        samples.append(FocusSample(time=index * step, x=offset / scale, source=source))

    smoothed = _smooth(samples, settings.smart_crop_smoothing)
    faces = sum(1 for sample in smoothed if sample.source is FocusSource.FACE)
    if not smoothed:
        dominant = FocusSource.CENTER
    elif faces >= len(smoothed) / 2:
        dominant = FocusSource.FACE
    else:
        dominant = FocusSource.MOTION

    track = FocusTrack(samples=smoothed, profile=profiles.sum(axis=0), scale=scale, source=dominant)
    logger.info(
        "framing.track_built",
        frames=len(frames),
        samples=len(smoothed),
        faces=faces,
        travel=round(track.travel),
        source=dominant.value,
    )
    return track


def _smooth(samples: list[FocusSample], window: int) -> list[FocusSample]:
    """Media móvil sobre las posiciones.

    Sin esto el seguimiento tiembla: la mejor franja salta unas columnas en cada
    fotograma, y ese temblor se convertiría en un encuadre nervioso.
    """
    if window <= 1 or len(samples) < 2:
        return samples

    positions = np.array([sample.x for sample in samples], dtype=np.float64)
    size = min(window, len(positions))
    averaged = np.convolve(positions, np.ones(size) / size, mode="same")

    # `mode="same"` degrada los extremos porque promedia con ceros implícitos;
    # se dejan tal cual venían.
    half = size // 2
    if half:
        averaged[:half] = positions[:half]
        averaged[-half:] = positions[-half:]

    return [
        FocusSample(time=sample.time, x=float(value), source=sample.source)
        for sample, value in zip(samples, averaged, strict=True)
    ]


# ---------------------------------------------------------------------- plan
def plan_crop(
    track: FocusTrack,
    content: CropWindow,
    *,
    target_width: int,
    target_height: int,
) -> CropPlan:
    """Coloca la ventana de salida sobre el sujeto, dentro de la zona con imagen.

    Devuelve un plan estático salvo que el sujeto recorra más de lo que cabe en
    la ventana y el paneo esté habilitado. Un paneo mal seguido marea más de lo
    que aporta, así que el listón para moverse es alto a propósito.
    """
    centered = center_crop_within(content, target_width, target_height)
    lowest = content.x
    highest = content.x + content.width - centered.width

    # El encuadre estático sale del perfil acumulado del clip entero, no de la
    # media de las posiciones: interesa dónde han pasado más cosas durante todo
    # el clip, no dónde estaba el sujeto en promedio.
    offset = (
        best_offset(track.profile, max(1, round(centered.width * track.scale)))
        if track.profile.size
        else None
    )
    if offset is None:
        logger.info("framing.centered", reason="sin senal utilizable")
        return CropPlan(window=centered, source=FocusSource.CENTER)

    static_x = _clamp_even(content.x + offset / track.scale, lowest, highest)
    window = CropWindow(x=static_x, y=centered.y, width=centered.width, height=centered.height)

    if not settings.smart_crop_pan or track.travel < centered.width * settings.smart_crop_pan_ratio:
        logger.info(
            "framing.static_crop",
            x=static_x,
            centered_x=centered.x,
            shift=static_x - centered.x,
            source=track.source.value,
        )
        return CropPlan(window=window, source=track.source)

    keyframes = tuple(
        (sample.time, _clamp_even(content.x + sample.x, lowest, highest))
        for sample in _thin(track.samples, settings.smart_crop_max_keyframes)
    )
    logger.info(
        "framing.pan_crop",
        keyframes=len(keyframes),
        travel=round(track.travel),
        source=track.source.value,
    )
    return CropPlan(window=window, keyframes=keyframes, source=track.source)


def _thin(samples: list[FocusSample], limit: int) -> list[FocusSample]:
    """Reduce las muestras a como mucho `limit`, repartidas por el clip.

    La expresión de recorte de ffmpeg se evalúa en cada fotograma, así que
    conviene que sea corta: con doce tramos el paneo ya es suave.
    """
    if limit <= 0 or len(samples) <= limit:
        return samples
    indices = np.linspace(0, len(samples) - 1, limit).round().astype(int)
    return [samples[index] for index in dict.fromkeys(indices.tolist())]


def _piecewise_expression(keyframes: tuple[tuple[float, int], ...]) -> str:
    """Interpolación lineal entre keyframes, como expresión de ffmpeg.

    El filtro `crop` evalúa `x` en cada fotograma con `t` como tiempo dentro del
    flujo. Como el corte se hace con `-ss` antes de `-i`, ese `t` ya empieza en
    cero al principio del clip y los tiempos de las muestras valen tal cual.

    Las comillas simples del resultado son obligatorias: la expresión lleva
    comas, y sin protegerlas separarían filtros dentro del filtrograma.
    """
    if not keyframes:
        return "0"
    if len(keyframes) == 1:
        return str(keyframes[0][1])

    # Se construye de atrás hacia delante: el último tramo es el valor final, y
    # cada paso lo envuelve en un `if` con su propia rampa.
    expression = str(keyframes[-1][1])
    for (time_a, x_a), (time_b, x_b) in reversed(list(pairwise(keyframes))):
        span = max(time_b - time_a, 1e-3)
        ramp = f"({x_a}+({x_b - x_a})*(t-{time_a:.3f})/{span:.3f})"
        expression = f"if(lt(t,{time_b:.3f}),{ramp},{expression})"

    # Par obligado: un desplazamiento impar descoloca el croma en 4:2:0.
    return f"'2*floor(({expression})/2)'"


def _clamp_even(value: float, low: int, high: int) -> int:
    """Acota a [low, high] y deja el resultado par."""
    if high < low:
        return low - low % 2
    bounded = int(max(low, min(high, value)))
    return bounded - bounded % 2
