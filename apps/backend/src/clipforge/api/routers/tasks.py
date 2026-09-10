"""Consulta del estado de las tareas encoladas.

Es lo que permite que un botón asíncrono deje de parecer roto: la interfaz
encola, se queda con el id y pregunta por él hasta que termina, en lugar de
recibir un 200 y no saber nunca más nada.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from clipforge.api.schemas.task import TERMINAL_STATES, TaskState
from clipforge.core.errors import ValidationError

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskState, summary="Estado de una tarea")
async def get_task(task_id: str) -> TaskState:
    """Estado de una tarea de Celery.

    No distingue "encolada" de "no existe": las dos son `PENDING` y Celery no
    guarda lo suficiente para separarlas. Para quien está esperando son la
    misma cosa —todavía no— y la alternativa sería inventarse una certeza.
    """
    try:
        uuid.UUID(task_id)
    except ValueError as exc:
        # Los ids los genera Celery y son UUID. Cualquier otra cosa es una
        # clave arbitraria contra el backend de resultados.
        raise ValidationError(f"'{task_id}' no es un id de tarea") from exc

    from clipforge.worker.celery_app import celery_app

    async_result = celery_app.AsyncResult(task_id)
    state = str(async_result.state)
    ready = state in TERMINAL_STATES

    result = async_result.result if state == "SUCCESS" else None
    error = str(async_result.result) if state == "FAILURE" else None

    return TaskState(
        task_id=task_id,
        state=state,
        ready=ready,
        successful=(state == "SUCCESS") if ready else None,
        # La tarea puede devolver cualquier cosa serializable; solo se propaga
        # si es un objeto, que es lo que el contrato promete.
        result=result if isinstance(result, dict) else None,
        error=error,
    )
