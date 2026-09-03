"""Generación de subtítulos SRT recortados a la ventana de un clip.

Pensados para móvil: pocas palabras por línea, como mucho dos líneas, y tiempos
relativos al inicio del clip. Los timestamps por palabra ya se guardan en
`TranscriptSegment.words`, así que el paso a subtítulos palabra a palabra estilo
TikTok es un cambio localizado aquí.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

#: Pensado para leerse de un vistazo en vertical, no para llenar el ancho.
MAX_CHARS_PER_LINE = 30
MAX_LINES = 2

#: Un subtítulo por debajo de esto parpadea; por encima, se queda pegado.
MIN_CUE_SECONDS = 0.6
MAX_CUE_SECONDS = 6.0


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    """Un subtítulo, con tiempos relativos al inicio del clip."""

    start: float
    end: float
    text: str


@dataclass(frozen=True, slots=True)
class SourceSegment:
    """Segmento de la transcripción, en tiempos del vídeo original."""

    start: float
    end: float
    text: str


def build_cues(
    segments: Sequence[SourceSegment], clip_start: float, clip_end: float
) -> list[SubtitleCue]:
    """Recorta los segmentos a la ventana del clip y los reajusta a tiempo cero.

    Un segmento que solo solapa parcialmente se recorta en lugar de descartarse:
    perder la primera frase de un clip es peor que un subtítulo entrando a medias.
    """
    cues: list[SubtitleCue] = []

    for segment in segments:
        start = max(segment.start, clip_start)
        end = min(segment.end, clip_end)
        if end - start <= 0:
            continue

        text = " ".join(segment.text.split())
        if not text:
            continue

        # Un segmento de Whisper puede durar diez segundos y traer una frase
        # larga. Se reparte en varios subtítulos sucesivos, no se comprime en
        # dos líneas gigantes: apilado, el texto tapa medio vídeo.
        chunks = split_into_lines(text)
        total_chars = sum(len(chunk) for chunk in chunks)
        cursor = start

        for chunk in chunks:
            share = (end - start) * (len(chunk) / total_chars) if total_chars else 0.0
            chunk_end = min(cursor + share, end)
            cues.append(
                SubtitleCue(
                    start=round(cursor - clip_start, 3),
                    end=round(min(chunk_end, cursor + MAX_CUE_SECONDS) - clip_start, 3),
                    text=wrap_text(chunk),
                )
            )
            cursor = chunk_end

    return _remove_overlaps(cues)


def split_into_lines(text: str) -> list[str]:
    """Trocea el texto en fragmentos que caben en un subtítulo.

    Cada fragmento ocupa como mucho `MAX_LINES` líneas de `MAX_CHARS_PER_LINE`.
    """
    limit = MAX_CHARS_PER_LINE * MAX_LINES
    chunks: list[str] = []
    current = ""

    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > limit:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)

    return chunks or [text]


def wrap_text(text: str) -> str:
    """Reparte un fragmento en líneas cortas, legibles en vertical."""
    lines: list[str] = []
    current = ""

    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > MAX_CHARS_PER_LINE:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)

    return "\n".join(lines[:MAX_LINES])


def render_srt(cues: Sequence[SubtitleCue]) -> str:
    """Serializa los subtítulos en formato SRT."""
    blocks = [
        f"{index}\n{_timestamp(cue.start)} --> {_timestamp(cue.end)}\n{cue.text}\n"
        for index, cue in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)


def write_srt(cues: Sequence[SubtitleCue], destination: Path) -> Path:
    """Escribe el fichero .srt en UTF-8, que es lo que espera libass."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_srt(cues), encoding="utf-8")
    return destination


def _remove_overlaps(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    """Evita que dos subtítulos se pisen y descarta los demasiado breves."""
    cleaned: list[SubtitleCue] = []

    for cue in sorted(cues, key=lambda c: c.start):
        start = cue.start
        if cleaned and start < cleaned[-1].end:
            start = cleaned[-1].end
        if cue.end - start < MIN_CUE_SECONDS:
            continue
        cleaned.append(SubtitleCue(start=start, end=cue.end, text=cue.text))

    return cleaned


def _timestamp(seconds: float) -> str:
    """Formato SRT: HH:MM:SS,mmm."""
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
