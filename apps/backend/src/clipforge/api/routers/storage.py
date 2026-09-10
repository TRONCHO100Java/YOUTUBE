"""Cuanto ocupa el almacen y como recuperar sitio.

Una granja de clips llena el disco sin que nadie se de cuenta: cada video
original pesa cerca de un giga y no se vuelve a usar despues de renderizar.
Hasta ahora eso solo se veia mirando la carpeta a mano, cuando ya era tarde.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

from clipforge.api.schemas.task import TaskRef
from clipforge.core.config import settings
from clipforge.core.logging import get_logger
from clipforge.worker.tasks.maintenance import purge_sources

router = APIRouter(prefix="/storage", tags=["storage"])
logger = get_logger(__name__)


class StorageUsage(BaseModel):
    """Lo que ocupa cada cosa, en megas."""

    #: Los originales descargados. Es lo unico de esta lista que se puede
    #: borrar sin perder nada: si hace falta, se vuelve a bajar.
    sources_mb: float
    #: Los clips renderizados. Esto no se recupera solo.
    clips_mb: float
    #: Las copias de la bandeja de subida de cada canal.
    export_mb: float
    #: Todo lo demas: transcripciones, subtitulos, cierres.
    other_mb: float
    total_mb: float
    #: Cuantos proyectos conservan todavia su original.
    projects_with_source: int


@router.get("", response_model=StorageUsage, summary="Cuanto ocupa el almacen")
async def usage() -> StorageUsage:
    """Mide el almacen por partes, para saber que compensa borrar."""
    root = settings.storage_path
    projects = root / "projects"

    sources = _size(projects, "*/source")
    clips = _size(projects, "*/clips")
    export = _size(root, "export")
    total = _folder_size(root)

    with_source = (
        sum(1 for path in projects.glob("*/source") if path.is_dir() and any(path.iterdir()))
        if projects.is_dir()
        else 0
    )

    return StorageUsage(
        sources_mb=_mb(sources),
        clips_mb=_mb(clips),
        export_mb=_mb(export),
        other_mb=_mb(max(0, total - sources - clips - export)),
        total_mb=_mb(total),
        projects_with_source=with_source,
    )


@router.post("/purge", response_model=TaskRef, summary="Borrar originales y recuperar sitio")
async def purge(
    older_than_days: int = Query(
        0,
        ge=0,
        description="Dias que debe llevar quieto un proyecto. 0 = todos los terminados",
    ),
) -> TaskRef:
    """Borra los originales de los proyectos ya terminados.

    Los clips NO se tocan. El original se puede volver a bajar de YouTube en
    dos minutos —la fase de descarga ya comprueba si falta—, mientras que un
    clip renderizado con su titulo, su nota y sus vistas no se recupera.
    """
    task = purge_sources.delay(older_than_days)
    logger.info("storage.purge_requested", task_id=task.id, older_than_days=older_than_days)
    return TaskRef(task_id=str(task.id), state=str(task.state))


def _folder_size(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(item.stat().st_size for item in folder.rglob("*") if item.is_file())


def _size(root: Path, pattern: str) -> int:
    if not root.is_dir():
        return 0
    return sum(_folder_size(path) for path in root.glob(pattern) if path.is_dir())


def _mb(value: int) -> float:
    return round(value / 1_048_576, 1)
