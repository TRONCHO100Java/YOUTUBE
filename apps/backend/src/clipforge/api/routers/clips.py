"""Endpoints de clips renderizados: metadatos, vídeo y subtítulos."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import FileResponse

from clipforge.api.deps import ClipRepo
from clipforge.api.schemas.clip import GeneratedClipRead
from clipforge.core.errors import NotFoundError
from clipforge.core.storage import absolute_from_storage, sanitize_filename
from clipforge.db.models import GeneratedClip

router = APIRouter(prefix="/clips", tags=["clips"])


@router.get("/{clip_id}", response_model=GeneratedClipRead, summary="Detalle de un clip")
async def get_clip(clip_id: uuid.UUID, repo: ClipRepo) -> GeneratedClipRead:
    return GeneratedClipRead.from_model(await _require(clip_id, repo))


@router.get(
    "/{clip_id}/video",
    summary="Vídeo del clip",
    response_class=FileResponse,
    responses={200: {"content": {"video/mp4": {}}}},
)
async def get_clip_video(clip_id: uuid.UUID, repo: ClipRepo) -> FileResponse:
    """Sirve el MP4.

    `FileResponse` responde a peticiones por rangos, que es lo que necesita la
    etiqueta `<video>` del navegador para poder saltar dentro del clip sin
    descargarlo entero.
    """
    clip = await _require(clip_id, repo)
    path = _resolve(clip.file_path)

    return FileResponse(
        path,
        media_type="video/mp4",
        # Nombre legible al descargar, derivado del título del candidato.
        filename=f"{sanitize_filename(clip.candidate.title, fallback='clip')}.mp4",
        content_disposition_type="inline",
    )


@router.get(
    "/{clip_id}/subtitles",
    summary="Subtítulos del clip",
    response_class=FileResponse,
    responses={200: {"content": {"application/x-subrip": {}}}},
)
async def get_clip_subtitles(clip_id: uuid.UUID, repo: ClipRepo) -> FileResponse:
    clip = await _require(clip_id, repo)
    if not clip.subtitle_path:
        raise NotFoundError(f"El clip {clip_id} no tiene fichero de subtítulos")

    return FileResponse(
        _resolve(clip.subtitle_path),
        media_type="application/x-subrip",
        filename=f"{sanitize_filename(clip.candidate.title, fallback='clip')}.srt",
    )


async def _require(clip_id: uuid.UUID, repo: ClipRepo) -> GeneratedClip:
    clip = await repo.get(clip_id)
    if clip is None:
        raise NotFoundError(f"Clip {clip_id} no encontrado")
    return clip


def _resolve(relative_path: str):  # type: ignore[no-untyped-def]
    """Resuelve la ruta guardada, validando que no se escapa del storage."""
    try:
        path = absolute_from_storage(relative_path)
    except ValueError as exc:
        raise NotFoundError("Ruta de fichero inválida") from exc
    if not path.is_file():
        raise NotFoundError(f"El fichero ya no está en disco: {relative_path}")
    return path
