"""Logging estructurado con structlog, compartido por API y worker."""

from __future__ import annotations

import logging
import sys

import structlog

from clipforge.core.config import settings

_configured = False


def configure_logging(*, force: bool = False) -> None:
    """Configura structlog + stdlib logging. Idempotente."""
    global _configured
    if _configured and not force:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)

    # Uvicorn trae sus propios handlers: los silenciamos para no duplicar lineas.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Devuelve un logger ya configurado."""
    configure_logging()
    return structlog.get_logger(name)  # type: ignore[no-any-return]
