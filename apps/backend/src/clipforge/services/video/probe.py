"""Lectura de metadatos reales del fichero de vídeo con ffprobe.

Los datos que anuncia la fuente son orientativos; los que valen para cortar y
renderizar son los del fichero que tenemos en disco.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger

logger = get_logger(__name__)

PROBE_TIMEOUT_SECONDS = 60


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str | None


def probe_video(path: Path) -> VideoMetadata:
    """Ejecuta ffprobe sobre `path` y devuelve sus características.

    Raises:
        ExternalToolError: si ffprobe falla, no está instalado o el fichero no
            contiene una pista de vídeo utilizable.
    """
    if not path.is_file():
        raise ExternalToolError(f"No existe el fichero a analizar: {path}")

    # Lista de argumentos, nunca shell=True: `path` no se interpreta como comando.
    command = [
        settings.ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    try:
        # Lista de argumentos y sin shell: nada del usuario se interpreta como comando.
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExternalToolError(
            f"No se encuentra ffprobe en '{settings.ffprobe_path}'. "
            "Instálalo o define FFPROBE_PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ExternalToolError("ffprobe ha excedido el tiempo máximo") from exc

    if completed.returncode != 0:
        raise ExternalToolError(
            "ffprobe ha fallado", details={"stderr": completed.stderr.strip()[:500]}
        )

    try:
        payload: dict[str, Any] = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ExternalToolError("ffprobe ha devuelto una salida ilegible") from exc

    return _parse(payload, path)


def _parse(payload: dict[str, Any], path: Path) -> VideoMetadata:
    streams: list[dict[str, Any]] = payload.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video_stream is None:
        raise ExternalToolError(f"El fichero no contiene pista de vídeo: {path.name}")

    duration = _to_float(payload.get("format", {}).get("duration")) or _to_float(
        video_stream.get("duration")
    )
    if duration is None:
        raise ExternalToolError(f"No se ha podido determinar la duración de {path.name}")

    return VideoMetadata(
        duration=duration,
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        fps=_parse_fps(video_stream.get("avg_frame_rate")),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        video_codec=video_stream.get("codec_name"),
    )


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_fps(raw: object) -> float:
    """ffprobe expresa los fps como fracción ('30000/1001')."""
    if not isinstance(raw, str) or "/" not in raw:
        return _to_float(raw) or 0.0
    try:
        fraction = Fraction(raw)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return float(fraction) if fraction.denominator else 0.0
