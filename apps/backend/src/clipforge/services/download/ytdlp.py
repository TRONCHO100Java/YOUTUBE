"""Descarga con yt-dlp.

Se usa la API de Python en lugar de invocar el binario: evita construir líneas
de comando con datos del usuario y devuelve los metadatos ya estructurados.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError, UnsupportedError

from clipforge.core.config import settings
from clipforge.core.errors import (
    ExternalToolError,
    SourceTooLongError,
    SourceUnavailableError,
)
from clipforge.core.logging import get_logger
from clipforge.services.download.base import (
    DownloadResult,
    SourceMetadata,
    VideoDownloader,
)
from clipforge.services.source.urls import SourceRef
from clipforge.services.video.binaries import ffmpeg_directory

logger = get_logger(__name__)

#: Mensajes de yt-dlp que indican "el vídeo no se puede obtener" (culpa de la
#: fuente, no un fallo nuestro): se traducen a un 422 con explicación útil.
_UNAVAILABLE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"private video", re.I), "El vídeo es privado"),
    # YouTube alterna "Video unavailable" y "This video is unavailable".
    (re.compile(r"video (?:is )?unavailable", re.I), "El vídeo no está disponible"),
    (re.compile(r"has been removed", re.I), "El vídeo ha sido eliminado"),
    (
        re.compile(r"members-only|join this channel", re.I),
        "El vídeo es solo para miembros del canal",
    ),
    (
        re.compile(r"confirm your age|age.?restricted", re.I),
        "El vídeo tiene restricción de edad",
    ),
    (
        # yt-dlp usa varias redacciones: "not available in your country" y
        # "has not made this video available in your country".
        re.compile(r"available in your country|geo.?restricted", re.I),
        "El vídeo no está disponible en tu país",
    ),
    (
        re.compile(r"live event will begin|premieres in", re.I),
        "El vídeo aún no se ha emitido",
    ),
    (
        re.compile(r"confirm you.?re not a bot", re.I),
        "YouTube pide verificación; reintenta más tarde",
    ),
)


class YtDlpDownloader(VideoDownloader):
    """Implementación de `VideoDownloader` sobre yt-dlp."""

    def fetch_metadata(self, ref: SourceRef) -> SourceMetadata:
        info = self._extract(ref, download=False)
        return _to_metadata(info)

    def download(self, ref: SourceRef, dest_dir: Path) -> DownloadResult:
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Se consultan primero los metadatos para rechazar vídeos demasiado
        # largos ANTES de gastar ancho de banda y disco.
        metadata = self.fetch_metadata(ref)
        self._assert_duration_allowed(metadata)

        info = self._extract(ref, download=True, dest_dir=dest_dir)
        video_path = self._resolve_downloaded_path(info, dest_dir, ref)

        logger.info(
            "download.completed",
            video_id=ref.video_id,
            path=str(video_path),
            size_mb=round(video_path.stat().st_size / 1_048_576, 1),
        )
        return DownloadResult(
            video_path=video_path,
            metadata=_to_metadata(info) if info else metadata,
            filesize_bytes=video_path.stat().st_size,
        )

    # ------------------------------------------------------------------ interno
    def _options(self, dest_dir: Path | None) -> dict[str, Any]:
        options: dict[str, Any] = {
            "format": settings.ytdlp_format,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 3,
            "socket_timeout": 30,
            "merge_output_format": "mp4",
            # El nombre en disco lo decidimos nosotros a partir del id validado:
            # nada del título elegido por un tercero llega al sistema de ficheros.
            "outtmpl": "%(id)s.%(ext)s",
            "max_filesize": settings.max_source_filesize_mb * 1_048_576,
        }

        # yt-dlp no resuelve un nombre suelto como "ffmpeg" contra el PATH: sin
        # una ruta real da la herramienta por ausente y aborta al remuxear vídeo
        # y audio separados. Solo se fija si la conocemos.
        ffmpeg_dir = ffmpeg_directory()
        if ffmpeg_dir is not None:
            options["ffmpeg_location"] = ffmpeg_dir

        if dest_dir is not None:
            options["paths"] = {"home": str(dest_dir)}
        return options

    def _extract(
        self, ref: SourceRef, *, download: bool, dest_dir: Path | None = None
    ) -> dict[str, Any]:
        try:
            # Los stubs de yt-dlp declaran un TypedDict cerrado para las opciones;
            # construirlas dinámicamente obliga a este cast.
            with YoutubeDL(cast(Any, self._options(dest_dir))) as ydl:
                info = ydl.extract_info(ref.url, download=download)
        except (DownloadError, ExtractorError, UnsupportedError) as exc:
            raise self._translate(exc) from exc
        except OSError as exc:
            raise ExternalToolError(f"Error de E/S descargando el vídeo: {exc}") from exc

        if not isinstance(info, dict):
            raise ExternalToolError("yt-dlp no ha devuelto información del vídeo")
        return dict(info)

    def _translate(self, exc: Exception) -> Exception:
        """Convierte un error de yt-dlp en un error de dominio comprensible."""
        message = str(exc)
        for pattern, explanation in _UNAVAILABLE_PATTERNS:
            if pattern.search(message):
                logger.warning("download.unavailable", reason=explanation)
                return SourceUnavailableError(explanation, details={"ytdlp_error": message})
        logger.error("download.failed", error=message)
        return ExternalToolError(
            "No se ha podido descargar el vídeo", details={"ytdlp_error": message}
        )

    def _assert_duration_allowed(self, metadata: SourceMetadata) -> None:
        limit = settings.max_source_duration_seconds
        if metadata.duration is not None and metadata.duration > limit:
            raise SourceTooLongError(
                f"El vídeo dura {metadata.duration / 60:.0f} min y el límite son "
                f"{limit / 60:.0f} min",
                details={"duration": metadata.duration, "limit_seconds": limit},
            )

    def _resolve_downloaded_path(
        self, info: dict[str, Any], dest_dir: Path, ref: SourceRef
    ) -> Path:
        """Localiza el fichero resultante, que puede haber cambiado de extensión al remuxear."""
        requested = info.get("requested_downloads") or []
        for entry in requested:
            candidate = entry.get("filepath") or entry.get("_filename")
            if candidate and Path(candidate).exists():
                return Path(candidate).resolve()

        matches = sorted(dest_dir.glob(f"{ref.video_id}.*"))
        if matches:
            return matches[0].resolve()

        raise ExternalToolError("La descarga terminó pero no se encuentra el fichero de vídeo")


def _to_metadata(info: dict[str, Any]) -> SourceMetadata:
    """Mapea la respuesta de yt-dlp a nuestro modelo, tolerando campos ausentes."""
    duration = info.get("duration")
    return SourceMetadata(
        title=info.get("title"),
        author=info.get("uploader") or info.get("channel"),
        duration=float(duration) if isinstance(duration, (int, float)) else None,
        thumbnail_url=info.get("thumbnail"),
    )
