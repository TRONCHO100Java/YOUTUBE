"""Health checks: liveness (proceso vivo) y readiness (dependencias listas)."""

from __future__ import annotations

import asyncio

import redis.asyncio as aioredis
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from clipforge import __version__
from clipforge.api.deps import DbSession
from clipforge.api.schemas.health import (
    ComponentHealth,
    HealthResponse,
    ReadinessResponse,
    Status,
)
from clipforge.core.config import settings
from clipforge.core.logging import get_logger

router = APIRouter(tags=["health"])
logger = get_logger(__name__)

_CHECK_TIMEOUT_SECONDS = 3.0


@router.get("/health", response_model=HealthResponse, summary="Liveness")
async def health() -> HealthResponse:
    """No toca dependencias: responde si el proceso esta en pie."""
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=__version__,
        environment=settings.environment,
    )


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness")
async def readiness(session: DbSession, response: Response) -> ReadinessResponse:
    """Verifica Postgres, Redis y la presencia de workers Celery."""
    components = {
        "database": await _check_database(session),
        "redis": await _check_redis(),
        "worker": await _check_worker(),
    }

    if any(c.status == "error" for c in components.values()):
        overall: Status = "error"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif any(c.status == "degraded" for c in components.values()):
        overall = "degraded"
    else:
        overall = "ok"

    return ReadinessResponse(
        status=overall,
        app=settings.app_name,
        version=__version__,
        environment=settings.environment,
        components=components,
    )


async def _check_database(session: DbSession) -> ComponentHealth:
    try:
        async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
        return ComponentHealth(status="ok")
    except Exception as exc:
        logger.warning("health.database_failed", error=str(exc))
        return ComponentHealth(status="error", detail=str(exc))


async def _check_redis() -> ComponentHealth:
    client = aioredis.from_url(settings.redis_url)
    try:
        async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
            await client.ping()
        return ComponentHealth(status="ok")
    except Exception as exc:
        logger.warning("health.redis_failed", error=str(exc))
        return ComponentHealth(status="error", detail=str(exc))
    finally:
        await client.aclose()


async def _check_worker() -> ComponentHealth:
    """Un worker caido degrada, no tumba: la API sigue sirviendo lecturas."""
    from clipforge.worker.celery_app import celery_app

    def _inspect() -> list[str]:
        replies = celery_app.control.ping(timeout=1.0)
        return [name for reply in replies or [] for name in reply]

    try:
        async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
            workers = await asyncio.to_thread(_inspect)
    except Exception as exc:
        return ComponentHealth(status="degraded", detail=str(exc))

    if not workers:
        # Un worker ocupado tampoco contesta: `--pool=solo` ejecuta la tarea en
        # el hilo principal, el mismo que atiende los mensajes de control. Decir
        # "no hay worker" mientras transcribe un vídeo de hora y media manda a
        # buscar una avería que no existe, así que se cuenta lo que sí se sabe.
        pending = await _queued_tasks()
        queue = "" if pending is None else f" Tareas en cola: {pending}."
        return ComponentHealth(
            status="degraded",
            detail=(
                "Ningun worker Celery ha contestado. Puede estar caido o ocupado "
                f"procesando un video, que tampoco responde mientras trabaja.{queue}"
            ),
        )
    return ComponentHealth(status="ok", detail=f"{len(workers)} worker(s): {', '.join(workers)}")


async def _queued_tasks() -> int | None:
    """Mensajes esperando en las colas de Celery, o None si Redis no contesta.

    Con el broker Redis cada cola es una lista con el nombre de la cola, asi
    que medirlas es un LLEN. Si Redis falla no se insiste: su propio check ya
    lo esta diciendo.
    """
    from clipforge.worker.celery_app import QUEUE_CPU, QUEUE_GPU

    client = aioredis.from_url(settings.redis_url)
    try:
        async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
            return int(await client.llen(QUEUE_CPU)) + int(await client.llen(QUEUE_GPU))
    except Exception as exc:
        logger.warning("health.queue_failed", error=str(exc))
        return None
    finally:
        await client.aclose()
