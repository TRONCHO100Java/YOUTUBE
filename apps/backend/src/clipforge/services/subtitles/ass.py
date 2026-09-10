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
- **Rótulos**, arriba, cada uno en su momento. Hay de dos clases:

  - El **gancho** ocupa los primeros segundos. Es la frase que decide si
    alguien sigue mirando, y en un clip sin diálogo es lo único escrito que
    hay: sin ella se publica un vídeo mudo y sin contexto.
  - Las **notas** aparecen a mitad de clip y dicen lo que el vídeo no dice:
    quién es alguien, qué acaba de pasar, por qué importa. Son el comentario
    editorial propio, y por eso van más pequeñas que el gancho: acompañan,
    no gritan.
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


@dataclass(frozen=True, slots=True)
class NoteStyle:
    """Estilo de una nota contextual.

    Más pequeña que el gancho y algo más abajo: el gancho compite por la
    atención en el primer segundo, la nota acompaña a lo que se está viendo.
    Con el mismo tamaño las dos gritan y no se lee ninguna.
    """

    font: str = "Arial"
    size: int = 66
    bold: bool = True
    outline: int = 5
    shadow: int = 2
    margin_vertical: int = 420
    margin_horizontal: int = 90
    line_length: int = 26
    max_lines: int = 2


@dataclass(frozen=True, slots=True)
class Overlay:
    """Un texto en pantalla, con su momento y su duración.

    Los tiempos son del CLIP ya montado, no del original: quien lo compone ya
    ha traducido el instante a través del `EditPlan`, porque un rótulo puesto
    en tiempos del original aparecería desplazado en cuanto se quite un
    silencio.
    """

    text: str
    start: float
    end: float
    #: "hook" arriba del todo y grande; "note" más abajo y más pequeña.
    kind: str = "note"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def style_name(self) -> str:
        return "Hook" if self.kind == "hook" else "Note"


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
    overlays: Sequence[Overlay] = (),
    hook_style: HookStyle | None = None,
    note_style: NoteStyle | None = None,
) -> str:
    """Serializa subtítulos y rótulos como un fichero ASS completo."""
    conf = style or SubtitleStyle()
    hook_conf = hook_style or HookStyle()
    note_conf = note_style or NoteStyle()

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
            "Style: Note,"
            f"{note_conf.font},{note_conf.size},"
            "&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            f"{-1 if note_conf.bold else 0},0,0,0,"
            "100,100,0,0,"
            f"1,{note_conf.outline},{note_conf.shadow},"
            f"8,{note_conf.margin_horizontal},{note_conf.margin_horizontal},"
            f"{note_conf.margin_vertical},1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    events = []
    for overlay in overlays:
        if overlay.duration <= 0:
            continue
        conf_for = hook_conf if overlay.kind == "hook" else note_conf
        wrapped = wrap_hook(
            overlay.text, line_length=conf_for.line_length, max_lines=conf_for.max_lines
        )
        if not wrapped:
            continue
        # Capa 1: por encima de los subtítulos si alguna vez coincidieran.
        events.append(
            f"Dialogue: 1,{_timestamp(overlay.start)},{_timestamp(overlay.end)},"
            f"{overlay.style_name},,0,0,0,,{_escape(wrapped)}"
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
    overlays: Sequence[Overlay] = (),
    hook_style: HookStyle | None = None,
    note_style: NoteStyle | None = None,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        render_ass(
            cues,
            width,
            height,
            style,
            overlays=overlays,
            hook_style=hook_style,
            note_style=note_style,
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
