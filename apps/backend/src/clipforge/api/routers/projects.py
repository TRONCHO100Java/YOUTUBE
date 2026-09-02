"""Endpoints de proyectos."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from clipforge.api.deps import ProjectRepo
from clipforge.api.schemas.candidate import ClipCandidateRead
from clipforge.api.schemas.common import Page
from clipforge.api.schemas.project import ProjectCreate, ProjectDetail, ProjectSummary
from clipforge.api.schemas.transcript import TranscriptRead, TranscriptSegmentRead
from clipforge.core.errors import ConflictError, NotFoundError
from clipforge.core.logging import get_logger
from clipforge.core.storage import ProjectStorage
from clipforge.db.models import Project, ProjectStatus
from clipforge.services.source.urls import validate_source_url
from clipforge.worker.tasks.pipeline import process_project

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
async def list_candidates(project_id: uuid.UUID, repo: ProjectRepo) -> list[ClipCandidateRead]:
    await _require(project_id, repo)
    candidates = await repo.list_candidates(project_id)
    return [ClipCandidateRead.from_model(candidate) for candidate in candidates]


@router.post(
    "/{project_id}/retry",
    response_model=ProjectDetail,
    summary="Reprocesar un proyecto terminado",
)
async def retry_project(project_id: uuid.UUID, repo: ProjectRepo) -> ProjectDetail:
    project = await _require(project_id, repo)

    if ProjectStatus(project.status).is_running:
        raise ConflictError(
            f"El proyecto está en curso ({project.status}); espera a que termine",
        )

    project.status = ProjectStatus.CREATED
    project.error_message = None
    project.task_id = _enqueue(project.id)
    await repo.session.commit()
    # `updated_at` se recalcula en el UPDATE (onupdate), así que hay que releerlo.
    await repo.session.refresh(project)

    logger.info("project.retried", project_id=str(project.id))
    return ProjectDetail.from_model(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Borrar proyecto")
async def delete_project(project_id: uuid.UUID, repo: ProjectRepo) -> None:
    project = await _require(project_id, repo)
    await repo.delete(project)
    await repo.session.commit()
    # El storage se borra tras el commit: si la BD falla, no perdemos ficheros.
    ProjectStorage(project_id).delete_all()
    logger.info("project.deleted", project_id=str(project_id))


async def _require(project_id: uuid.UUID, repo: ProjectRepo) -> Project:
    project = await repo.get(project_id)
    if project is None:
        raise NotFoundError(f"Proyecto {project_id} no encontrado")
    return project


def _enqueue(project_id: uuid.UUID) -> str:
    """Encola el pipeline y devuelve el id de la tarea Celery."""
    async_result = process_project.delay(str(project_id))
    return str(async_result.id)
