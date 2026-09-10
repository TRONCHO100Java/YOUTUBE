"""Endpoints de proyectos."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, status
from fastapi.responses import FileResponse

from clipforge.api.deps import CandidateRepo, ClipRepo, ProjectRepo
from clipforge.api.schemas.candidate import (
    ClipCandidateCreate,
    ClipCandidateRead,
)
from clipforge.api.schemas.clip import GeneratedClipRead
from clipforge.api.schemas.common import Page
from clipforge.api.schemas.project import (
    ProjectCreate,
    ProjectDetail,
    ProjectSummary,
    ProjectUpdate,
)
from clipforge.api.schemas.transcript import TranscriptRead, TranscriptSegmentRead
from clipforge.core.errors import ConflictError, NotFoundError, ValidationError
from clipforge.core.logging import get_logger
from clipforge.core.storage import ProjectStorage, absolute_from_storage, sanitize_filename
from clipforge.db.models import (
    CandidateSource,
    CandidateStatus,
    ClipCandidate,
    Project,
    ProjectStatus,
)
from clipforge.services.source.urls import validate_source_url
from clipforge.worker.tasks.pipeline import process_project
from clipforge.worker.tasks.retitle import retitle_project

router = APIRouter(prefix="/projects", tags=["projects"])
logger = get_logger(__name__)


@router.post(
    "",
    response_model=ProjectDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un proyecto a partir de una URL",
)
async def create_project(payload: ProjectCreate, repo: ProjectRepo) -> ProjectDetail:
    """Valida la URL, crea el proyecto y encola su procesamiento."""
    ref = validate_source_url(payload.url)

    project = await repo.add(
        Project(
            source_url=ref.url,
            source_type=ref.source_type,
            status=ProjectStatus.CREATED,
            keywords=_clean_keywords(payload.keywords),
        )
    )
    # Commit ANTES de encolar: si el worker recogiera la tarea antes de que la
    # fila estuviera visible, no encontraría el proyecto.
    await repo.session.commit()

    project.task_id = _enqueue(project.id)
    await repo.session.commit()
    # created_at/updated_at los calcula PostgreSQL (server_default y onupdate),
    # así que quedan expirados tras el UPDATE. Sin este refresh, serializarlos
    # dispararía una carga perezosa síncrona dentro del contexto asíncrono.
    await repo.session.refresh(project)

    logger.info("project.created", project_id=str(project.id), video_id=ref.video_id)
    return ProjectDetail.from_model(project)


@router.get("", response_model=Page[ProjectSummary], summary="Lista de proyectos")
async def list_projects(
    repo: ProjectRepo,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[ProjectSummary]:
    projects = await repo.list(limit=limit, offset=offset)
    total = await repo.count()
    return Page[ProjectSummary](
        items=[ProjectSummary.model_validate(p, from_attributes=True) for p in projects],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{project_id}", response_model=ProjectDetail, summary="Detalle de proyecto")
async def get_project(project_id: uuid.UUID, repo: ProjectRepo) -> ProjectDetail:
    project = await _require(project_id, repo)
    return ProjectDetail.from_model(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectDetail,
    summary="Editar las palabras clave de un proyecto",
)
async def update_project(
    project_id: uuid.UUID, payload: ProjectUpdate, repo: ProjectRepo
) -> ProjectDetail:
    """Cambia las palabras clave sin tocar el vídeo ya descargado.

    No relanza nada por su cuenta: las palabras solo influyen en el
    análisis, así que quien quiera aplicarlas a un proyecto terminado tiene
    que pulsar Regenerar. Hacerlo aquí encolaría un vídeo entero por haber
    corregido una errata.
    """
    project = await _require(project_id, repo)

    if payload.keywords is not None:
        project.keywords = _clean_keywords(payload.keywords)

    await repo.session.commit()
    await repo.session.refresh(project)

    logger.info("project.updated", project_id=str(project_id))
    return ProjectDetail.from_model(project)


@router.get(
    "/{project_id}/transcript",
    response_model=TranscriptRead,
    summary="Transcripcion del proyecto",
)
async def get_transcript(
    project_id: uuid.UUID,
    repo: ProjectRepo,
    include_words: bool = Query(
        False, description="Incluye los timestamps por palabra (respuesta mucho mayor)"
    ),
) -> TranscriptRead:
    await _require(project_id, repo)
    transcript = await repo.get_transcript(project_id)
    if transcript is None:
        raise NotFoundError(f"El proyecto {project_id} todavia no tiene transcripcion")

    return TranscriptRead(
        id=transcript.id,
        project_id=transcript.project_id,
        language=transcript.language,
        language_probability=transcript.language_probability,
        model_name=transcript.model_name,
        duration=transcript.duration,
        full_text=transcript.full_text,
        segments=[
            TranscriptSegmentRead(
                index=segment.index,
                start_time=segment.start_time,
                end_time=segment.end_time,
                text=segment.text,
                words=segment.words if include_words else None,
            )
            for segment in transcript.segments
        ],
    )


@router.get(
    "/{project_id}/candidates",
    response_model=list[ClipCandidateRead],
    summary="Momentos detectados por la IA",
)
async def list_candidates(
    project_id: uuid.UUID, repo: ProjectRepo, candidates: CandidateRepo
) -> list[ClipCandidateRead]:
    await _require(project_id, repo)
    rows = await candidates.list_for_project(project_id)
    return [ClipCandidateRead.from_model(candidate) for candidate in rows]


@router.get(
    "/{project_id}/clips",
    response_model=list[GeneratedClipRead],
    summary="Clips renderizados del proyecto",
)
async def list_clips(
    project_id: uuid.UUID, repo: ProjectRepo, clips: ClipRepo
) -> list[GeneratedClipRead]:
    await _require(project_id, repo)
    return [GeneratedClipRead.from_model(clip) for clip in await clips.list_for_project(project_id)]


@router.post(
    "/{project_id}/retry",
    response_model=ProjectDetail,
    summary="Reprocesar un proyecto terminado",
)
async def retry_project(
    project_id: uuid.UUID,
    repo: ProjectRepo,
    force: bool = Query(
        False,
        description=(
            "Reprocesa aunque el proyecto figure en curso. Necesario cuando un "
            "worker murió a mitad y dejó el estado colgado."
        ),
    ),
) -> ProjectDetail:
    project = await _require(project_id, repo)

    # Sin el escape, un worker que muere a mitad deja el proyecto bloqueado
    # para siempre: figura en curso y nada va a terminarlo.
    if ProjectStatus(project.status).is_running and not force:
        raise ConflictError(
            f"El proyecto está en curso ({project.status}); espera a que termine "
            "o reintenta con ?force=true si el worker se cayó",
        )

    project.status = ProjectStatus.CREATED
    project.error_message = None
    project.task_id = _enqueue(project.id)
    await repo.session.commit()
    # `updated_at` se recalcula en el UPDATE (onupdate), así que hay que releerlo.
    await repo.session.refresh(project)

    logger.info("project.retried", project_id=str(project.id))
    return ProjectDetail.from_model(project)


@router.post(
    "/{project_id}/retitle",
    response_model=ProjectDetail,
    summary="Reescribir solo los títulos de los clips",
)
async def retitle(project_id: uuid.UUID, repo: ProjectRepo) -> ProjectDetail:
    """Vuelve a titular sin volver a renderizar.

    El título no está dentro del MP4, así que cambiarlo no cuesta ni una
    descarga ni un segundo de GPU. Es lo que hace que probar otro enfoque
    —o aplicar unas palabras clave recién escritas— sea cuestión de
    segundos en lugar de reprocesar el vídeo entero.

    No toca el gancho: ese va incrustado en los píxeles, y cambiarlo sin
    renderizar dejaría la base de datos diciendo una cosa y el vídeo
    enseñando otra.
    """
    project = await _require(project_id, repo)

    if ProjectStatus(project.status).is_running:
        raise ConflictError(
            f"El proyecto está en curso ({project.status}); espera a que termine para retitularlo"
        )

    retitle_project.delay(str(project.id))
    logger.info("project.retitle_requested", project_id=str(project.id))
    return ProjectDetail.from_model(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Borrar proyecto")
async def delete_project(project_id: uuid.UUID, repo: ProjectRepo) -> None:
    project = await _require(project_id, repo)
    await repo.delete(project)
    await repo.session.commit()
    # El storage se borra tras el commit: si la BD falla, no perdemos ficheros.
    ProjectStorage(project_id).delete_all()
    logger.info("project.deleted", project_id=str(project_id))


@router.get(
    "/{project_id}/signals",
    summary="Señales no verbales del vídeo",
    response_model=dict,
)
async def get_signals(project_id: uuid.UUID, repo: ProjectRepo) -> dict[str, Any]:
    """Curva de energía, cortes de plano, movimiento y bloques candidatos.

    Es lo que dibuja la línea de tiempo del editor. Se sirve tal cual se guardó:
    ya viene submuestreada para caber en una pantalla, así que no hace falta
    filtrarla aquí.
    """
    project = await _require(project_id, repo)
    if not project.signals:
        raise NotFoundError(
            f"El proyecto {project_id} todavía no tiene señales medidas. "
            "Vuelve a procesarlo para generarlas."
        )
    return dict(project.signals)


@router.get(
    "/{project_id}/source",
    summary="Vídeo original del proyecto",
    response_class=FileResponse,
    responses={200: {"content": {"video/mp4": {}}}},
)
async def get_source_video(project_id: uuid.UUID, repo: ProjectRepo) -> FileResponse:
    """Sirve el MP4 de origen para poder recortarlo en el navegador.

    `FileResponse` responde a peticiones por rangos, que es lo que necesita la
    etiqueta `<video>` para saltar dentro de un fichero de cientos de megas sin
    descargarlo entero. Sin esto, el editor manual tendría que esperar a la
    descarga completa antes de dejar mover la cabeza lectora.
    """
    project = await _require(project_id, repo)
    if not project.source_video_path:
        raise NotFoundError(f"El proyecto {project_id} no tiene vídeo descargado")

    try:
        path = absolute_from_storage(project.source_video_path)
    except ValueError as exc:
        raise NotFoundError("Ruta de fichero inválida") from exc
    if not path.is_file():
        raise NotFoundError(
            "El vídeo original ya no está en disco. Vuelve a procesar el proyecto "
            "para descargarlo otra vez."
        )

    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{sanitize_filename(project.title or 'video', fallback='video')}.mp4",
        content_disposition_type="inline",
    )


@router.post(
    "/{project_id}/candidates",
    response_model=ClipCandidateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un clip a mano",
)
async def create_candidate(
    project_id: uuid.UUID,
    payload: ClipCandidateCreate,
    repo: ProjectRepo,
    candidates: CandidateRepo,
) -> ClipCandidateRead:
    """Registra un recorte hecho por el usuario, listo para renderizar.

    Los límites de duración del perfil NO se aplican: son una guía para la IA,
    no una regla para la persona que está mirando el vídeo. Lo único que se
    comprueba es que el rango exista dentro del original.
    """
    project = await _require(project_id, repo)
    if not project.source_video_path:
        raise ConflictError(
            "El proyecto todavía no tiene vídeo descargado; espera a que termine "
            "la descarga para recortar"
        )
    if project.duration and payload.end_time > project.duration + 1.0:
        raise ValidationError(
            f"La salida ({payload.end_time:.1f}s) se sale del vídeo, "
            f"que dura {project.duration:.1f}s"
        )

    candidate = await candidates.add(
        ClipCandidate(
            project_id=project_id,
            start_time=payload.start_time,
            end_time=payload.end_time,
            title=payload.title.strip(),
            reason="Recortado a mano.",
            # Sin puntuación: nadie lo ha valorado, y ponerle un cero lo
            # enterraría al final de una lista ordenada por nota.
            score=0.0,
            status=CandidateStatus.PENDING,
            source=CandidateSource.MANUAL,
            rank=await candidates.next_rank(project_id),
        )
    )
    await candidates.session.commit()
    created = await candidates.get(candidate.id)

    logger.info(
        "candidate.created_manually",
        project_id=str(project_id),
        start=round(payload.start_time, 2),
        end=round(payload.end_time, 2),
    )
    return ClipCandidateRead.from_model(created or candidate)


async def _require(project_id: uuid.UUID, repo: ProjectRepo) -> Project:
    project = await repo.get(project_id)
    if project is None:
        raise NotFoundError(f"Proyecto {project_id} no encontrado")
    return project


def _clean_keywords(raw: str | None) -> str | None:
    """Normaliza el campo libre de palabras clave.

    Guardar "" en lugar de NULL haría que el prompt arrastrase una línea de
    palabras clave vacía, que es peor que no tener ninguna: ocupa atención
    del modelo sin decirle nada.
    """
    if raw is None:
        return None
    return raw.strip() or None


def _enqueue(project_id: uuid.UUID) -> str:
    """Encola el pipeline y devuelve el id de la tarea Celery."""
    async_result = process_project.delay(str(project_id))
    return str(async_result.id)
