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


@celery_app.task(name="clipforge.maintenance.rescue_stalled")
def rescue_stalled(idle_minutes: int | None = None) -> dict[str, Any]:
    """Reencola los proyectos que se quedaron a medias sin que nadie lo diga.

    Un worker que se reinicia, un cuelgue o un apagon dejan el proyecto
    donde estaba —en cola o a mitad de una fase— y su mensaje se pierde.
    Nadie vuelve a tocarlo: no aparece como fallido, porque no fallo, asi
    que se queda como si estuviera trabajando para siempre. En algo que
    tiene que funcionar sin nadie delante, ese silencio es peor que un error.

    Se detecta por tiempo y no preguntandole a Celery. Con el backend de
    Redis, una tarea perdida y una que espera turno se ven las dos como
    PENDING, asi que preguntar no distingue el caso. El reloj si: un
    pipeline vivo va cambiando el estado segun avanza, y ninguna fase
    aguanta una hora callada en esta maquina.

    Reencolar uno que en realidad seguia vivo no lo duplica. El proyecto
    guarda el id de SU tarea: al reencolar se queda con el nuevo, y la
    vieja, cuando despierta, ve que ya no es la dueña y se para sola.
    """
    from clipforge.worker.tasks.pipeline import process_project

    minutes = settings.stalled_project_minutes if idle_minutes is None else idle_minutes
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    rescued: list[str] = []

    with sync_session_scope() as session:
        stalled = list(
            session.execute(
                select(Project).where(
                    Project.status.notin_(
                        [
                            ProjectStatus.COMPLETED,
                            ProjectStatus.FAILED,
                            ProjectStatus.NEEDS_REVIEW,
                        ]
                    ),
                    Project.updated_at < cutoff,
                )
            ).scalars()
        )
        for project in stalled:
            rescued.append(str(project.id))

    for project_id in rescued:
        task = process_project.delay(project_id)
        # El dueño pasa a ser la tarea nueva ANTES de que arranque: si la
        # vieja seguia viva, esto es lo que la hace pararse al despertar.
        with sync_session_scope() as session:
            owner = session.get(Project, uuid.UUID(project_id))
            if owner is not None:
                owner.task_id = str(task.id)

    logger.info("maintenance.rescued", projects=len(rescued), idle_minutes=minutes)
    return {"rescued": len(rescued), "projects": rescued}


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
