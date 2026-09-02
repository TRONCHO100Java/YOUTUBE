"""Jerarquia de errores de dominio.

La API los traduce a respuestas JSON homogeneas; el worker los usa para decidir
si una tarea es reintentable o si el proyecto debe marcarse como FAILED.
"""

from __future__ import annotations

from typing import Any


class ClipForgeError(Exception):
    """Error base de la aplicacion."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class NotFoundError(ClipForgeError):
    status_code = 404
    code = "not_found"


class ValidationError(ClipForgeError):
    status_code = 422
    code = "validation_error"


class ConflictError(ClipForgeError):
    """El recurso existe pero su estado no permite la operacion solicitada."""

    status_code = 409
    code = "conflict"


class UnsupportedSourceError(ValidationError):
    """URL o tipo de fuente no permitido."""

    code = "unsupported_source"


class ExternalToolError(ClipForgeError):
    """Fallo de una herramienta externa (yt-dlp, ffmpeg, whisper, LLM)."""

    status_code = 502
    code = "external_tool_error"
