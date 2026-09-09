"""Generación del subtítulo ASS que se quema en el vídeo.

El `.srt` es el fichero que se entrega para publicar el clip en cualquier sitio;
este `.ass` es el que se incrusta.

Hace falta un formato propio porque el estilo del `.srt` solo puede darse con
`force_style`, y libass lo interpreta sobre un lienzo de 384x288 en lugar de
sobre el vídeo real: los tamaños y márgenes quedan a merced de ese factor y un
margen algo grande manda el texto fuera de pantalla. Un `.ass` declara su propia
`PlayResX/PlayResY`, así que cada valor está en píxeles del clip final.

El fichero lleva dos capas con propósitos distintos:

- **Subtítulos**, abajo, durante todo el clip. Transcriben lo que se dice.
- **Gancho**, arriba, solo los primeros segundos. Es la frase que decide si
  alguien sigue mirando, y en un clip sin diálogo es lo único escrito que hay:
  sin ella se publica un vídeo mudo y sin contexto.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from clipforge.services.subtitles.srt import SubtitleCue


@dataclass(frozen=True, slots=True)
class SubtitleStyle:
    """Estilo pensado para móvil: grande, blanco y con borde grueso."""

    font: str = "Arial"
    #: En píxeles del vídeo de salida.
    size: int = 64
    bold: bool = True
    outline: int = 4
    shadow: int = 2
    #: Distancia al borde inferior. Deja el texto por debajo de la cara del
    #: hablante y por encima de la interfaz de las apps de vídeo.
    margin_vertical: int = 320
    margin_horizontal: int = 60


@dataclass(frozen=True, slots=True)
class HookStyle:
    """Estilo del gancho: más grande que el subtítulo y arriba del todo.

    Va arriba y no abajo por dos motivos: no pisa a los subtítulos, y en las
    tres aplicaciones la mitad inferior la tapan el texto del autor, los
    botones y la barra de progreso.
    """

    font: str = "Arial"
    size: int = 100
    bold: bool = True
    outline: int = 6
    shadow: int = 2
    #: Distancia al borde superior. Deja libre la zona donde las apps ponen su
    #: propia interfaz.
    margin_vertical: int = 240
    margin_horizontal: int = 70
    #: Caracteres por línea antes de partir. Una línea que cruza toda la
    #: pantalla obliga a barrer con la vista y se lee peor que dos cortas.
    line_length: int = 18
    #: Más líneas que esto tapan el vídeo en lugar de acompañarlo.
    max_lines: int = 3


def wrap_hook(text: str, *, line_length: int, max_lines: int) -> str:
    """Parte el gancho en líneas legibles, recortando lo que sobre.

    Un gancho largo se corta con puntos suspensivos en lugar de encogerse: el
    tamaño de letra está elegido para leerse en un móvil a un brazo de
    distancia, y reducirlo para que quepa todo anula el motivo de ponerlo.
    """
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""

    lines = textwrap.wrap(cleaned, width=line_length) or [cleaned]
    if len(lines) <= max_lines:
        return "\n".join(lines)

    kept = lines[:max_lines]
    kept[-1] = kept[-1].rstrip(" .,;:") + "…"
    return "\n".join(kept)


def render_ass(
    cues: Sequence[SubtitleCue],
    width: int,
    height: int,
    style: SubtitleStyle | None = None,
    *,
    hook: str | None = None,
    hook_seconds: float = 3.0,
    hook_style: HookStyle | None = None,
) -> str:
    """Serializa subtítulos y gancho como un fichero ASS completo."""
    conf = style or SubtitleStyle()
    hook_conf = hook_style or HookStyle()

    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            # La clave del formato: fija el lienzo al tamaño real del clip.
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 0",
            # Escala bordes y sombra con la resolución, para que no se vean finos.
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,"
            f"{conf.font},{conf.size},"
            "&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            f"{-1 if conf.bold else 0},0,0,0,"
            "100,100,0,0,"
            f"1,{conf.outline},{conf.shadow},"
            # Alignment 2 = abajo y centrado.
            f"2,{conf.margin_horizontal},{conf.margin_horizontal},{conf.margin_vertical},1",
            "Style: Hook,"
            f"{hook_conf.font},{hook_conf.size},"
            "&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            f"{-1 if hook_conf.bold else 0},0,0,0,"
            "100,100,0,0,"
            f"1,{hook_conf.outline},{hook_conf.shadow},"
            # Alignment 8 = arriba y centrado.
            f"8,{hook_conf.margin_horizontal},{hook_conf.margin_horizontal},"
            f"{hook_conf.margin_vertical},1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    events = []
    if hook and hook_seconds > 0:
        wrapped = wrap_hook(hook, line_length=hook_conf.line_length, max_lines=hook_conf.max_lines)
        if wrapped:
            # Capa 1: por encima de los subtítulos si alguna vez coincidieran.
            events.append(
                f"Dialogue: 1,{_timestamp(0)},{_timestamp(hook_seconds)},Hook,,0,0,0,,"
                f"{_escape(wrapped)}"
            )

    events += [
        f"Dialogue: 0,{_timestamp(cue.start)},{_timestamp(cue.end)},Default,,0,0,0,,"
        f"{_escape(cue.text)}"
        for cue in cues
    ]

    return "\n".join([header, *events, ""])


def write_ass(
    cues: Sequence[SubtitleCue],
    destination: Path,
    width: int,
    height: int,
    style: SubtitleStyle | None = None,
    *,
    hook: str | None = None,
    hook_seconds: float = 3.0,
    hook_style: HookStyle | None = None,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        render_ass(
            cues,
            width,
            height,
            style,
            hook=hook,
            hook_seconds=hook_seconds,
            hook_style=hook_style,
        ),
        encoding="utf-8",
    )
    return destination


def _escape(text: str) -> str:
    r"""Los saltos de línea en ASS son `\N`; las llaves abren etiquetas.

    El orden importa: primero se quitan las barras invertidas del texto de
    origen y solo después se insertan las de los saltos, o el propio salto
    quedaría descartado.
    """
    return (
        text.replace("\\", "")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\r\n", "\n")
        .replace("\n", "\\N")
    )


def _timestamp(seconds: float) -> str:
    """Formato ASS: H:MM:SS.cc (centésimas, no milésimas)."""
    total_cs = max(0, round(seconds * 100))
    hours, remainder = divmod(total_cs, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"
