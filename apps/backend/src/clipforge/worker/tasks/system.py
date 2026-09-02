"""Tareas de infraestructura: sirven para verificar que el worker esta vivo."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from clipforge.core.logging import get_logger
from clipforge.db.session import sync_session_scope
from clipforge.worker.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="clipforge.system.ping")
def ping() -> dict[str, Any]:
    """Comprueba que el worker ejecuta tareas y alcanza Postgres."""
    with sync_session_scope() as session:
        db_ok = session.execute(text("SELECT 1")).scalar_one() == 1
    logger.info("worker.ping", database=db_ok)
    return {"pong": True, "database": db_ok}
