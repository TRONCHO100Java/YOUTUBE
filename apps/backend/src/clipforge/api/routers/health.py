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
        return ComponentHealth(status="degraded", detail="Ningun worker Celery conectado")
    return ComponentHealth(status="ok", detail=f"{len(workers)} worker(s): {', '.join(workers)}")
