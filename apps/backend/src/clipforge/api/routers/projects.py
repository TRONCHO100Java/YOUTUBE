"""Endpoints de lectura de proyectos.

FASE 1: solo lectura. La creacion (POST /projects -> yt-dlp) llega en la FASE 2.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from clipforge.api.deps import ProjectRepo
from clipforge.api.schemas.common import Page
from clipforge.api.schemas.project import ProjectDetail, ProjectSummary
from clipforge.core.errors import NotFoundError
from clipforge.core.storage import ProjectStorage

router = APIRouter(prefix="/projects", tags=["projects"])


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
    project = await repo.get(project_id)
    if project is None:
        raise NotFoundError(f"Proyecto {project_id} no encontrado")
    return ProjectDetail.from_model(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Borrar proyecto")
async def delete_project(project_id: uuid.UUID, repo: ProjectRepo) -> None:
    project = await repo.get(project_id)
    if project is None:
        raise NotFoundError(f"Proyecto {project_id} no encontrado")
    await repo.delete(project)
    await repo.session.commit()
    # El storage en disco se borra despues del commit: si la BD falla, no perdemos ficheros.
    ProjectStorage(project_id).delete_all()
