"""Endpoints de clips renderizados: metadatos, vídeo y subtítulos."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from clipforge.api.deps import ClipRepo
from clipforge.api.schemas.clip import GeneratedClipRead
from clipforge.api.schemas.task import TaskRef
from clipforge.core.errors import ConflictError, NotFoundError
from clipforge.core.logging import get_logger
from clipforge.core.storage import absolute_from_storage, sanitize_filename
from clipforge.db.models import GeneratedClip
from clipforge.services.video.thumbnail import ensure_thumbnail, thumbnail_path

#: Tope por tanda. Mas que esto no es una tanda, es un borrado masivo
#: hecho sin mirar.
MAX_BULK = 100

router = APIRouter(prefix="/clips", tags=["clips"])
logger = get_logger(__name__)


class BulkClips(BaseModel):
    """Varios clips a la vez."""

    clip_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=MAX_BULK,
        description="Clips sobre los que actuar",
    )


class BulkResult(BaseModel):
    """Cuantos se han tocado y cuantos no estaban."""

    #: Los que han cambiado de verdad. Un clip ya subido que se vuelve a
    #: marcar no cuenta: no ha pasado nada con el.
    changed: int
    #: Ids que ya no existen. No es un error —se pueden haber borrado entre
    #: que se pinto la lista y se pulso el boton— pero hay que decirlo.
    missing: int


@router.post(
    "/bulk/uploaded",
    response_model=BulkResult,
    summary="Marcar varios clips como subidos",
)
async def bulk_uploaded(payload: BulkClips, repo: ClipRepo) -> BulkResult:
    """Marca de golpe todo lo que se acaba de subir.

    Subir diez Shorts a Studio y volver a marcarlos de uno en uno es donde
    se pierde la tarde. Se hace en una transaccion: o se marcan todos o no
    se marca ninguno, para que no quede media tanda a medias si algo falla.
    """
    changed = 0
    missing = 0
    now = datetime.now(UTC)

    for clip_id in payload.clip_ids:
        clip = await repo.get(clip_id)
        if clip is None:
            missing += 1
            continue
        if clip.published_at is not None:
            continue
        clip.published_at = now
        if clip.privacy_status is None:
            clip.privacy_status = "manual"
        changed += 1

    await repo.session.commit()
    logger.info("clips.bulk_uploaded", changed=changed, missing=missing)
    return BulkResult(changed=changed, missing=missing)


@router.post(
    "/bulk/delete-files",
    response_model=BulkResult,
    summary="Borrar el fichero de varios clips",
)
async def bulk_delete_files(payload: BulkClips, repo: ClipRepo) -> BulkResult:
    """Libera el sitio de varios clips ya subidos.

    Solo toca los que ya estan marcados como subidos. Borrar en bloque el
    unico sitio donde existe un video que todavia no ha salido seria
    exactamente el error que no se puede deshacer.
    """
    changed = 0
    missing = 0

    for clip_id in payload.clip_ids:
        clip = await repo.get(clip_id)
        if clip is None:
            missing += 1
            continue
        if clip.published_at is None or clip.deleted_at is not None:
            continue

        for relative in (clip.file_path, clip.subtitle_path):
            if not relative:
                continue
            try:
                path = absolute_from_storage(relative)
            except ValueError:
                continue
            path.unlink(missing_ok=True)
            thumbnail_path(path).unlink(missing_ok=True)
        clip.deleted_at = datetime.now(UTC)
        changed += 1

    await repo.session.commit()
    logger.info("clips.bulk_deleted", changed=changed, missing=missing)
    return BulkResult(changed=changed, missing=missing)


@router.get("/{clip_id}", response_model=GeneratedClipRead, summary="Detalle de un clip")
async def get_clip(clip_id: uuid.UUID, repo: ClipRepo) -> GeneratedClipRead:
    return GeneratedClipRead.from_model(await _require(clip_id, repo))


@router.post(
    "/{clip_id}/publish",
    response_model=TaskRef,
    summary="Subir el clip a YouTube",
)
async def publish_clip(clip_id: uuid.UUID, repo: ClipRepo) -> TaskRef:
    """Encola la subida del clip a YouTube.

    Sube con la privacidad de `YOUTUBE_PRIVACY`, que viene en `private`
    a propósito: la API de datos de YouTube restringe a privado todo lo que
    sube un proyecto sin auditar, así que es lo que va a pasar de todos
    modos. Prometer otra cosa en la interfaz sería mentir.
    """
    clip = await _require(clip_id, repo)

    if clip.youtube_video_id:
        raise ConflictError(f"Este clip ya está subido: youtube.com/shorts/{clip.youtube_video_id}")

    from clipforge.services.publish import is_configured

    if not is_configured():
        raise ConflictError(
            "Falta autorizar YouTube. Ejecútalo una vez desde apps/backend: "
            "python -m clipforge.services.publish.authorize"
        )

    from clipforge.worker.tasks.publish import upload_generated_clip

    task = upload_generated_clip.delay(str(clip_id))
    logger.info("clip.publish_requested", clip_id=str(clip_id), task_id=task.id)
    return TaskRef(task_id=str(task.id), state=str(task.state))


@router.post(
    "/{clip_id}/uploaded",
    response_model=GeneratedClipRead,
    summary="Marcar el clip como ya subido",
)
async def mark_uploaded(
    clip_id: uuid.UUID,
    repo: ClipRepo,
    video_id: str | None = Query(
        None, max_length=32, description="Id del vídeo en YouTube, si lo tienes"
    ),
) -> GeneratedClipRead:
    """Anota que este clip ya está publicado, lo hayas subido como lo hayas subido.

    Existe porque subir a mano por Studio es una vía legítima —y ahora mismo
    la única que publica en público sin pasar la auditoría de Google—, y sin
    esto el sistema no se entera: el clip seguiría apareciendo como pendiente
    y volvería a la carpeta de subida en cada exportación.

    El id del vídeo es opcional: lo normal al subir por Studio es no tenerlo
    a mano, y exigirlo convertiría un botón en un formulario.
    """
    clip = await _require(clip_id, repo)

    clip.published_at = clip.published_at or datetime.now(UTC)
    if video_id:
        clip.youtube_video_id = video_id.strip() or None
    if clip.privacy_status is None:
        # Subido por fuera: no sabemos con qué privacidad quedó, y decir
        # "público" sin saberlo sería inventarse un dato.
        clip.privacy_status = "manual"

    await repo.session.commit()
    logger.info("clip.marked_uploaded", clip_id=str(clip_id))
    return GeneratedClipRead.from_model(await _require(clip_id, repo))


@router.delete(
    "/{clip_id}/file",
    response_model=GeneratedClipRead,
    summary="Borrar el fichero del clip y dejar sitio",
)
async def delete_file(clip_id: uuid.UUID, repo: ClipRepo) -> GeneratedClipRead:
    """Borra el MP4 y sus subtítulos, y conserva la ficha.

    La fila NO se borra, y es deliberado: el clip existió, se subió y tiene
    vistas, y esa historia es lo que permite saber si la rúbrica acierta.
    Vale mucho más que los treinta megas que ocupaba el fichero.

    Lo que desaparece son los bytes. Después de esto el clip sigue en la
    lista, marcado como borrado, y ya no se puede reproducir ni descargar.
    """
    clip = await _require(clip_id, repo)

    for relative in (clip.file_path, clip.subtitle_path):
        if not relative:
            continue
        try:
            path = absolute_from_storage(relative)
        except ValueError:
            continue
        path.unlink(missing_ok=True)
        # La miniatura sale del MP4: sin el no se puede regenerar, y
        # dejarla suelta seria enseñar un clip que ya no se puede ver.
        thumbnail_path(path).unlink(missing_ok=True)

    clip.deleted_at = datetime.now(UTC)
    await repo.session.commit()

    logger.info("clip.file_deleted", clip_id=str(clip_id))
    return GeneratedClipRead.from_model(await _require(clip_id, repo))


@router.get(
    "/{clip_id}/thumbnail",
    summary="Miniatura del clip",
    response_class=FileResponse,
    responses={200: {"content": {"image/jpeg": {}}}},
)
async def get_clip_thumbnail(clip_id: uuid.UUID, repo: ClipRepo) -> FileResponse:
    """Sirve una imagen del clip, sacándola la primera vez que se pide.

    Existe para no tener que cargar veinte vídeos de treinta megas solo
    para que el navegador pinte su primer fotograma. Una imagen de veinte
    kilos hace el mismo trabajo.

    Se genera al vuelo y se guarda: así vale también para los clips que ya
    estaban renderizados desde antes de que esto existiera.
    """
    clip = await _require(clip_id, repo)
    if clip.deleted_at is not None:
        raise NotFoundError("El fichero de este clip se borró para dejar sitio.")

    path = _resolve(clip.file_path)
    # A un hilo: ffmpeg bloquea, y dejar parado el bucle de eventos mientras
    # se generan veinte miniaturas congelaría el resto de la API.
    thumb = await asyncio.to_thread(ensure_thumbnail, path)

    return FileResponse(thumb, media_type="image/jpeg")


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
    if clip.deleted_at is not None:
        raise NotFoundError(
            "El fichero de este clip se borró para dejar sitio. La ficha se "
            "conserva, pero el vídeo ya no está."
        )
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
