"""Instancia Celery compartida.

Colas separadas desde el dia 1: `cpu` para trabajo ligero y `gpu` para el
pipeline pesado (whisper + ffmpeg). Cuando movamos el procesamiento a RunPod o
a una segunda maquina, basta con arrancar alli un worker suscrito a `gpu`.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import setup_logging

from clipforge.core.config import settings
from clipforge.core.logging import configure_logging

QUEUE_CPU = "cpu"
QUEUE_GPU = "gpu"

celery_app = Celery(
    "clipforge",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "clipforge.worker.tasks.system",
        "clipforge.worker.tasks.pipeline",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    task_time_limit=settings.celery_task_time_limit,
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    result_expires=60 * 60 * 24,
    task_default_queue=QUEUE_CPU,
    task_routes={"clipforge.pipeline.*": {"queue": QUEUE_GPU}},
    broker_connection_retry_on_startup=True,
)


@setup_logging.connect
def _configure_celery_logging(**_kwargs: object) -> None:
    """Usamos structlog tambien en el worker, no el logger por defecto de Celery."""
    configure_logging(force=True)
