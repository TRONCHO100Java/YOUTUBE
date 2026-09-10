"""Recuperar sitio sin perder nada que haga falta.

El video original es, con diferencia, lo que mas ocupa: en la maquina donde se
escribio esto, once de los trece gigas del almacen eran originales de proyectos
ya terminados. A un giga por video, cien videos son cien gigas de peso muerto.

Y es peso muerto de verdad: una vez renderizados los clips, el original no se
vuelve a usar. Si algun dia hace falta —porque se regenera el proyecto o se
reencuadra un clip— la fase de descarga lo vuelve a bajar sola, porque ya
comprueba si el fichero sigue estando antes de saltarsela.

Lo que NO se borra nunca son los clips ni las fichas. El original se puede
recuperar de YouTube en dos minutos; un clip renderizado con su titulo, su nota
y sus vistas, no.
"""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from clipforge.core.config import settings
from clipforge.core.logging import get_logger
from clipforge.core.storage import ProjectStorage, StorageArea
from clipforge.db.models import Project, ProjectStatus
from clipforge.db.session import sync_session_scope
from clipforge.worker.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="clipforge.maintenance.purge_sources")
def purge_sources(older_than_days: int | None = None) -> dict[str, Any]:
    """Borra los originales de los proyectos terminados y ya reposados.

    Args:
        older_than_days: dias que tiene que llevar quieto un proyecto antes de
            tocarlo. Por defecto, lo configurado. Con 0 se borra en cuanto
            termina.

    El plazo existe para dejar margen a lo que de verdad necesita el original:
    reencuadrar un clip a mano o regenerar el proyecto se hacen el mismo dia
    que se mira, no dos semanas despues.
    """
    days = settings.source_retention_days if older_than_days is None else older_than_days
    if days < 0:
        logger.info("maintenance.purge_disabled", retention_days=days)
        return {"freed_mb": 0, "projects": 0, "skipped": "desactivado"}

    cutoff = datetime.now(UTC) - timedelta(days=days)
    freed = 0
    touched: list[str] = []

    with sync_session_scope() as session:
        # Solo lo que ya no esta en marcha: borrarle el original a un proyecto
        # a mitad de render lo tumbaria.
        candidates = list(
            session.execute(
                select(Project).where(
                    Project.status.in_(
                        [
                            ProjectStatus.COMPLETED,
                            ProjectStatus.NEEDS_REVIEW,
                            ProjectStatus.FAILED,
                        ]
                    ),
                    Project.updated_at < cutoff,
                    Project.source_video_path.is_not(None),
                )
            ).scalars()
        )
        ids = [(project.id, project.title) for project in candidates]

    for project_id, title in ids:
        freed_here = _purge_one(project_id)
        if freed_here:
            freed += freed_here
            touched.append(title or str(project_id))

    logger.info(
        "maintenance.purge_finished",
        projects=len(touched),
        freed_mb=round(freed / 1_048_576, 1),
        retention_days=days,
    )
    return {
        "freed_mb": round(freed / 1_048_576, 1),
        "projects": len(touched),
        "titles": touched[:20],
    }


@celery_app.task(name="clipforge.maintenance.retry_failed")
def retry_failed(max_projects: int = 5) -> dict[str, Any]:
    """Vuelve a encolar los proyectos que fallaron por causas pasajeras.

    Casi todos los fallos de esta aplicacion son de red: una descarga que
    se corta, un modelo que no responde a tiempo. Reintentarlos a mano
    obliga a estar delante, que es justo lo que una granja no puede pedir.

    NO se reintenta lo que fallo por criterio. Un proyecto en NEEDS_REVIEW
    no fallo: la IA miro el video y no encontro nada publicable, y volver a
    pasarselo daria el mismo resultado gastando la misma GPU.

    El tope por vuelta existe para que un fallo sistematico —el disco
    lleno, Ollama caido— no llene la cola de veinte reintentos que van a
    fallar igual.
    """
    from clipforge.worker.tasks.pipeline import process_project

    requeued: list[str] = []

    with sync_session_scope() as session:
        failed = list(
            session.execute(
                select(Project)
                .where(Project.status == ProjectStatus.FAILED)
                .order_by(Project.updated_at.desc())
                .limit(max_projects)
            ).scalars()
        )
        for project in failed:
            project.status = ProjectStatus.CREATED
            project.error_message = None
            requeued.append(str(project.id))

    for project_id in requeued:
        process_project.delay(project_id)

    logger.info("maintenance.retried", projects=len(requeued))
    return {"requeued": len(requeued), "projects": requeued}


def _purge_one(project_id: uuid.UUID) -> int:
    """Borra el original de un proyecto y devuelve los bytes recuperados.

    La fila se actualiza en la MISMA operacion: dejar `source_video_path`
    apuntando a un fichero que ya no existe haria que la fase de descarga
    creyera tenerlo y fallase mas tarde, en la transcripcion, con un error que
    no dice nada del problema real.
    """
    storage = ProjectStorage(project_id)
    folder = storage.root / StorageArea.SOURCE.value
    if not folder.is_dir():
        return 0

    freed = sum(item.stat().st_size for item in folder.rglob("*") if item.is_file())
    shutil.rmtree(folder, ignore_errors=True)

    with sync_session_scope() as session:
        project = session.get(Project, project_id)
        if project is not None:
            project.source_video_path = None

    return freed
