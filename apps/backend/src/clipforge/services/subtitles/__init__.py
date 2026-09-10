"""Generación de subtítulos para los clips."""

from clipforge.services.subtitles.ass import (
    HookStyle,
    NoteStyle,
    Overlay,
    SubtitleStyle,
    render_ass,
    wrap_hook,
    write_ass,
)
from clipforge.services.subtitles.srt import (
    SourceSegment,
    SubtitleCue,
    build_cues,
    render_srt,
    write_srt,
)

__all__ = [
    "HookStyle",
    "NoteStyle",
    "Overlay",
    "SourceSegment",
    "SubtitleCue",
    "SubtitleStyle",
    "build_cues",
    "render_ass",
    "render_srt",
    "wrap_hook",
    "write_ass",
    "write_srt",
]
