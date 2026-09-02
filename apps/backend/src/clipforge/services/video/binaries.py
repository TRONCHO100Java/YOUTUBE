"""Localización de los ejecutables multimedia.

`FFMPEG_PATH` y `FFPROBE_PATH` pueden ser un nombre de comando ("ffmpeg") o una
ruta completa. Varias partes del sistema (yt-dlp, ffprobe y el render de la
FASE 5) necesitan la ruta real, así que la resolución se centraliza aquí.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError


def resolve_binary(configured: str) -> Path | None:
    """Devuelve la ruta absoluta de un ejecutable, o None si no se encuentra.

    Una ruta explícita tiene prioridad sobre el PATH: si el usuario configura un
    binario concreto, se usa ese y no otro que aparezca antes en el PATH.
    """
    if not configured:
        return None

    candidate = Path(configured)
    if candidate.is_file():
        return candidate.resolve()

    found = shutil.which(configured)
    return Path(found).resolve() if found else None


def resolve_ffmpeg() -> Path | None:
    return resolve_binary(settings.ffmpeg_path)


def resolve_ffprobe() -> Path | None:
    return resolve_binary(settings.ffprobe_path)


@lru_cache(maxsize=1)
def ffmpeg_directory() -> str | None:
    """Directorio de ffmpeg, en el formato que espera yt-dlp.

    Se le pasa el directorio y no el binario para que encuentre también ffprobe.
    yt-dlp NO resuelve un nombre suelto como "ffmpeg" contra el PATH: si se le
    pasa uno, da la herramienta por ausente y aborta al remuxear.
    """
    binary = resolve_ffmpeg()
    return str(binary.parent) if binary else None


def run_tool(
    command: list[str], *, tool_name: str, timeout: int
) -> subprocess.CompletedProcess[str]:
    """Ejecuta una herramienta externa y normaliza sus fallos.

    Siempre con lista de argumentos y sin `shell`: ningún dato del usuario puede
    interpretarse como comando.
    """
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExternalToolError(
            f"No se encuentra {tool_name} en '{command[0]}'. "
            f"Instálalo o define {tool_name.upper()}_PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ExternalToolError(f"{tool_name} ha excedido el tiempo máximo ({timeout}s)") from exc

    if completed.returncode != 0:
        raise ExternalToolError(
            f"{tool_name} ha fallado",
            details={"stderr": (completed.stderr or "").strip()[-800:]},
        )
    return completed
