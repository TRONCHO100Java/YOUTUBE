"""Instancia Celery compartida.

Colas separadas desde el dia 1: `cpu` para trabajo ligero y `gpu` para el
pipeline pesado (whisper + ffmpeg). Cuando movamos el procesamiento a RunPod o
a una segunda maquina, basta con arrancar alli un worker suscrito a `gpu`.
"""

from __future__ import annotations

from datetime import timedelta

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
        "clipforge.worker.tasks.render",
        "clipforge.worker.tasks.retitle",
        "clipforge.worker.tasks.retag",
        "clipforge.worker.tasks.maintenance",
        "clipforge.worker.tasks.ingest",
        "clipforge.worker.tasks.publish",
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
    # Temporizador: revisar los canales vigilados. Es lo que hace que la
    # aplicacion traiga videos sola en lugar de esperar a que alguien pegue
    # una URL. Va embebido en el worker (`celery worker -B`) porque en un
    # solo equipo un cuarto proceso solo seria una ventana mas que cerrar.
    beat_schedule={
        "poll-watched-channels": {
            "task": "clipforge.ingest.poll_channels",
            "schedule": timedelta(minutes=settings.ingest_interval_minutes),
            # Si el worker estuvo parado, al arrancar no interesa disparar
            # todas las revisiones que se perdio: basta con la siguiente.
            "options": {"expires": 60 * settings.ingest_interval_minutes},
        },
        # Releer las vistas de lo publicado. Es lo unico que puede decir si
        # la rubrica acierta; una vez al dia basta, porque un Short no cambia
        # de suerte cada hora.
        # Recuperar sitio. Una vez al dia basta: lo que se libera son
        # originales de proyectos ya terminados, que no crecen solos.
        # Reintentar lo que fallo por causas pasajeras. Cada hora: si el
        # motivo era de red, para entonces suele haberse arreglado solo.
        # Rescatar lo que se quedo a medias. Cada quince minutos: es lo que
        # tarda en notarse que la cola esta parada sin motivo.
        "rescue-stalled-projects": {
            "task": "clipforge.maintenance.rescue_stalled",
            "schedule": timedelta(minutes=15),
            "options": {"expires": 900},
        },
        "retry-failed-projects": {
            "task": "clipforge.maintenance.retry_failed",
            "schedule": timedelta(hours=1),
            "options": {"expires": 3600},
        },
        "purge-source-videos": {
            "task": "clipforge.maintenance.purge_sources",
            "schedule": timedelta(hours=24),
            "options": {"expires": 3600 * 24},
        },
        "refresh-published-stats": {
            "task": "clipforge.publish.refresh_stats",
            "schedule": timedelta(hours=12),
            "options": {"expires": 3600 * 12},
        },
    }
    if settings.ingest_enabled
    else {},
)


@setup_logging.connect
def _configure_celery_logging(**_kwargs: object) -> None:
    """Usamos structlog tambien en el worker, no el logger por defecto de Celery."""
    configure_logging(force=True)
