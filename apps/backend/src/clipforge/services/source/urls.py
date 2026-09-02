"""Validacion y normalizacion de URLs de origen.

Es la unica puerta de entrada de contenido al sistema: aqui se rechaza todo lo
que no sea una fuente permitida, antes de que ningun dato del usuario llegue a
yt-dlp, al sistema de ficheros o a la base de datos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from clipforge.core.config import settings
from clipforge.core.errors import UnsupportedSourceError
from clipforge.db.models.enums import SourceType

MAX_URL_LENGTH = 2048

#: Los identificadores de YouTube son 11 caracteres del alfabeto base64url.
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

#: Rutas que contienen el id como primer segmento: /shorts/ID, /embed/ID, ...
_PATH_PREFIXES = ("shorts", "embed", "live", "v")


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Referencia validada y normalizada a un vídeo de origen."""

    source_type: SourceType
    url: str
    video_id: str


def validate_source_url(raw_url: str) -> SourceRef:
    """Valida una URL de usuario y devuelve una referencia normalizada.

    Raises:
        UnsupportedSourceError: si la URL es inválida, apunta a un host no
            permitido o no contiene un identificador de vídeo reconocible.
    """
    url = (raw_url or "").strip()
    if not url:
        raise UnsupportedSourceError("Debes indicar una URL")
    if len(url) > MAX_URL_LENGTH:
        raise UnsupportedSourceError(f"La URL supera los {MAX_URL_LENGTH} caracteres")

    parsed = urlparse(url if "://" in url else f"https://{url}")

    if parsed.scheme not in ("http", "https"):
        raise UnsupportedSourceError(f"Esquema no permitido: {parsed.scheme or 'ninguno'}")

    # Credenciales embebidas (user:pass@host) son siempre sospechosas.
    if parsed.username or parsed.password:
        raise UnsupportedSourceError("La URL no puede incluir credenciales")

    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsupportedSourceError("La URL no tiene host")

    allowed = {h.lower() for h in settings.allowed_source_hosts}
    if host not in allowed:
        raise UnsupportedSourceError(
            f"Host no permitido: {host}",
            details={"allowed_hosts": sorted(allowed)},
        )

    video_id = _extract_video_id(host, parsed.path, parsed.query)
    if video_id is None:
        raise UnsupportedSourceError("No se ha encontrado un identificador de vídeo en la URL")

    # URL canonica: descarta listas, timestamps y parametros de tracking, y hace
    # que dos formas distintas de la misma URL produzcan el mismo proyecto.
    return SourceRef(
        source_type=SourceType.YOUTUBE,
        url=f"https://www.youtube.com/watch?v={video_id}",
        video_id=video_id,
    )


def _extract_video_id(host: str, path: str, query: str) -> str | None:
    """Extrae el id de vídeo de las distintas formas de URL de YouTube."""
    segments = [segment for segment in path.split("/") if segment]

    # youtu.be/ID
    if host == "youtu.be":
        candidate = segments[0] if segments else ""
        return candidate if _VIDEO_ID.match(candidate) else None

    # youtube.com/watch?v=ID
    if segments[:1] == ["watch"]:
        values = parse_qs(query).get("v", [])
        candidate = values[0] if values else ""
        return candidate if _VIDEO_ID.match(candidate) else None

    # youtube.com/shorts/ID, /embed/ID, /live/ID, /v/ID
    if len(segments) >= 2 and segments[0] in _PATH_PREFIXES:
        candidate = segments[1]
        return candidate if _VIDEO_ID.match(candidate) else None

    return None
