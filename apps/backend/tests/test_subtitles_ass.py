"""Subtítulo ASS: el que se incrusta en el vídeo.

Existe porque el estilo de un `.srt` solo puede darse con `force_style`, y
libass lo interpreta sobre un lienzo de 384x288 en vez de sobre el vídeo real.
Un `.ass` declara su propia resolución, así que cada valor es un píxel del clip.
"""

from __future__ import annotations

from pathlib import Path

from clipforge.services.subtitles import (
    SourceSegment,
    build_cues,
    render_ass,
    wrap_hook,
    write_ass,
)
from clipforge.services.subtitles.ass import SubtitleStyle, _escape, _timestamp
from clipforge.services.subtitles.srt import SubtitleCue

CUES = [
    SubtitleCue(start=0.0, end=2.5, text="Primera línea"),
    SubtitleCue(start=2.5, end=5.0, text="Dos\nlíneas"),
]


def test_declares_the_output_resolution() -> None:
    """Sin esto los márgenes quedan a merced del lienzo que suponga libass."""
    content = render_ass(CUES, 1080, 1920)

    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content


def test_has_the_three_required_sections() -> None:
    content = render_ass(CUES, 1080, 1920)

    assert "[Script Info]" in content
    assert "[V4+ Styles]" in content
    assert "[Events]" in content


def test_one_dialogue_per_cue() -> None:
    content = render_ass(CUES, 1080, 1920)
    assert content.count("Dialogue:") == len(CUES)


def test_style_values_reach_the_file() -> None:
    style = SubtitleStyle(font="Impact", size=72, margin_vertical=200)
    content = render_ass(CUES, 1080, 1920, style)

    assert "Impact,72," in content
    # MarginL, MarginR, MarginV son los tres últimos antes del Encoding.
    assert ",60,60,200,1" in content


def test_alignment_is_bottom_centered() -> None:
    """Alignment 2 en ASS es abajo y centrado."""
    lines = render_ass(CUES, 1080, 1920).splitlines()
    line = next(item for item in lines if item.startswith("Style:"))
    fields = line.split(",")
    assert fields[-5] == "2"


def test_line_breaks_use_the_ass_escape() -> None:
    content = render_ass([SubtitleCue(start=0.0, end=1.0, text="Uno\nDos")], 1080, 1920)

    assert "Uno\\NDos" in content
    assert "Uno\nDos" not in content


def test_braces_are_neutralised() -> None:
    """En ASS las llaves abren etiquetas de formato; el texto no debe abrirlas."""
    assert "{" not in _escape("texto {con} llaves")
    assert "}" not in _escape("texto {con} llaves")


def test_timestamps_use_centiseconds() -> None:
    assert _timestamp(0.0) == "0:00:00.00"
    assert _timestamp(3.456) == "0:00:03.46"
    assert _timestamp(65.0) == "0:01:05.00"
    assert _timestamp(3661.5) == "1:01:01.50"


def test_negative_time_is_clamped() -> None:
    assert _timestamp(-5.0) == "0:00:00.00"


def test_written_file_is_utf8(tmp_path: Path) -> None:
    cues = build_cues([SourceSegment(start=0.0, end=3.0, text="Acción y ñandú")], 0.0, 3.0)
    written = write_ass(cues, tmp_path / "subs" / "clip.ass", 1080, 1920)

    assert "Acción y ñandú" in written.read_text(encoding="utf-8")


def test_empty_cue_list_still_produces_a_valid_file() -> None:
    content = render_ass([], 1080, 1920)

    assert "[Events]" in content
    assert "Dialogue:" not in content


# ------------------------------------------------------------------- gancho
def test_the_hook_is_written_on_its_own_layer() -> None:
    """Va en capa 1 para quedar por encima del subtítulo si coincidieran."""
    rendered = render_ass([], 1080, 1920, hook="Mira lo que pasa")

    assert "Style: Hook," in rendered
    assert "Dialogue: 1," in rendered
    assert "Mira lo que pasa" in rendered


def test_the_hook_sits_at_the_top() -> None:
    """Alignment 8. La mitad de abajo la tapan los botones de la app."""
    rendered = render_ass([], 1080, 1920, hook="Arriba")

    hook_style = next(line for line in rendered.splitlines() if line.startswith("Style: Hook,"))
    assert hook_style.split(",")[18] == "8"


def test_the_hook_only_covers_the_first_seconds() -> None:
    rendered = render_ass([], 1080, 1920, hook="Corto", hook_seconds=2.5)

    event = next(line for line in rendered.splitlines() if line.startswith("Dialogue: 1,"))
    assert "0:00:00.00" in event
    assert "0:00:02.50" in event


def test_a_clip_without_subtitles_still_gets_its_hook() -> None:
    """El caso que motivó todo: un clip visual no lleva subtítulos y es el que
    más necesita una frase escrita."""
    rendered = render_ass([], 1080, 1920, hook="Sin diálogo")

    assert "Dialogue: 1," in rendered
    assert "Dialogue: 0," not in rendered


def test_no_hook_means_no_hook_event() -> None:
    assert "Dialogue: 1," not in render_ass([], 1080, 1920)
    assert "Dialogue: 1," not in render_ass([], 1080, 1920, hook="   ")
    assert "Dialogue: 1," not in render_ass([], 1080, 1920, hook="Algo", hook_seconds=0)


def test_the_hook_is_escaped_like_any_other_text() -> None:
    rendered = render_ass([], 1080, 1920, hook=r"Llaves {raras} y barra \ suelta")

    assert "{raras}" not in rendered
    assert "(raras)" in rendered


# -------------------------------------------------------------- partido en lineas
def test_a_long_hook_is_split_into_lines() -> None:
    wrapped = wrap_hook(
        "Esta frase es demasiado larga para caber en una sola linea de movil",
        line_length=22,
        max_lines=3,
    )

    assert "\n" in wrapped
    assert all(len(line) <= 22 for line in wrapped.split("\n"))


def test_an_endless_hook_is_truncated_not_shrunk() -> None:
    """Encoger la letra para que quepa todo anula el motivo de ponerla."""
    wrapped = wrap_hook("palabra " * 60, line_length=22, max_lines=3)

    assert len(wrapped.split("\n")) == 3
    assert wrapped.endswith("…")


def test_wrapping_collapses_stray_whitespace() -> None:
    assert wrap_hook("  hola   mundo  ", line_length=40, max_lines=2) == "hola mundo"


def test_an_empty_hook_wraps_to_nothing() -> None:
    assert wrap_hook("   ", line_length=20, max_lines=2) == ""


def test_the_hook_reaches_the_ass_as_a_line_break() -> None:
    rendered = render_ass([], 1080, 1920, hook="Una frase larga que no cabe de ninguna manera aqui")

    event = next(line for line in rendered.splitlines() if line.startswith("Dialogue: 1,"))
    assert r"\N" in event
