"""Generación del subtítulo ASS que se quema en el vídeo.

El `.srt` es el fichero que se entrega para publicar el clip en cualquier sitio;
este `.ass` es el que se incrusta.

Hace falta un formato propio porque el estilo del `.srt` solo puede darse con
`force_style`, y libass lo interpreta sobre un lienzo de 384x288 en lugar de
sobre el vídeo real: los tamaños y márgenes quedan a merced de ese factor y un
margen algo grande manda el texto fuera de pantalla. Un `.ass` declara su propia
`PlayResX/PlayResY`, así que cada valor está en píxeles del clip final.
"""

from __future__ import annotations

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


def render_ass(
    cues: Sequence[SubtitleCue],
    width: int,
    height: int,
    style: SubtitleStyle | None = None,
) -> str:
    """Serializa los subtítulos como un fichero ASS completo."""
    conf = style or SubtitleStyle()

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
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    events = [
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
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_ass(cues, width, height, style), encoding="utf-8")
    return destination


def _escape(text: str) -> str:
    r"""Los saltos de línea en ASS son `\N`; las llaves abren etiquetas."""
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
