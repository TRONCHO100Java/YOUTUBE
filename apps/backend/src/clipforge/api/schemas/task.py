"""Estado de una tarea encolada.

Existe porque un botón que encola trabajo y devuelve 200 no le dice nada al
usuario: la petición ha ido bien, pero el trabajo no ha empezado siquiera.
Sin poder preguntar por él, "no ha pasado nada" y "está tardando" se ven
exactamente igual, y la conclusión razonable es que la aplicación está rota.

Celery ya guarda el estado en Redis (`task_track_started`), así que esto no
añade estado nuevo: solo lo saca por la API.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

#: Estados de Celery que significan "ya no va a cambiar".
TERMINAL_STATES = frozenset({"SUCCESS", "FAILURE", "REVOKED"})


class TaskRef(BaseModel):
    """Lo que devuelve un endpoint que encola trabajo."""

    task_id: str = Field(description="Id con el que consultar el estado en /api/tasks")
    state: str = Field(description="Estado inicial de la tarea")


class TaskState(BaseModel):
    """Estado de una tarea, tal y como lo cuenta el backend de resultados.

    `PENDING` es ambiguo en Celery: significa "encolada" y también "no la
    conozco". No se puede distinguir, y fingir lo contrario sería mentir; para
    quien espera, ambas cosas son "todavía no".
    """

    task_id: str
    state: str
    ready: bool = Field(description="La tarea ya no va a cambiar de estado")
    successful: bool | None = Field(None, description="None mientras no ha terminado")
    #: Lo que devolvió la tarea. Solo se rellena si terminó bien.
    result: dict[str, Any] | None = None
    #: Mensaje del fallo, si falló. Nunca la traza: eso va al log del worker.
    error: str | None = None
