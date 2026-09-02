"""Contrato de descarga de la fuente.

Abstraerlo permite añadir más adelante uploads directos, Google Drive o Twitch
sin tocar el pipeline: solo hay que registrar otra implementación.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from clipforge.services.source.urls import SourceRef


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Metadatos anunciados por la fuente, antes de descargar nada."""

    title: str | None
    author: str | None
    duration: float | None
    thumbnail_url: str | None


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Resultado de una descarga completada."""

    video_path: Path
    metadata: SourceMetadata
    filesize_bytes: int


class VideoDownloader(ABC):
    """Obtiene el vídeo de origen y lo deja en disco."""

    @abstractmethod
    def fetch_metadata(self, ref: SourceRef) -> SourceMetadata:
        """Consulta los metadatos sin descargar el vídeo."""

    @abstractmethod
    def download(self, ref: SourceRef, dest_dir: Path) -> DownloadResult:
        """Descarga el vídeo en `dest_dir` y devuelve su ruta y metadatos."""
