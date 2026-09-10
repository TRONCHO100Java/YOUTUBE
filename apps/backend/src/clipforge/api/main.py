"""Aplicacion FastAPI."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from clipforge import __version__
from clipforge.api.routers import (
    candidates,
    clips,
    discovery,
    health,
    projects,
    publish_channels,
    tasks,
)
from clipforge.core.config import settings
from clipforge.core.errors import ClipForgeError
from clipforge.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

API_PREFIX = "/api"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    logger.info(
        "api.startup",
        environment=settings.environment,
        storage_path=str(settings.storage_path),
        version=__version__,
    )
    yield
    from clipforge.db.session import async_engine

    await async_engine.dispose()
    logger.info("api.shutdown")


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description="Convierte videos largos en clips verticales.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # `allow_headers` cubre las cabeceras de PETICIÓN. Estas son de
        # RESPUESTA y hay que exponerlas explícitamente: sin Content-Range la
        # etiqueta <video> no puede resolver el tamaño del fichero y se queda
        # cargando para siempre, y sin Content-Disposition la descarga pierde
        # el nombre del clip.
        expose_headers=[
            "Content-Range",
            "Accept-Ranges",
            "Content-Length",
            "Content-Disposition",
        ],
    )

    _register_middleware(app)
    _register_exception_handlers(app)

    # /health cuelga de la raiz (convencion de infra); el resto vive bajo /api.
    app.include_router(health.router)
    app.include_router(projects.router, prefix=API_PREFIX)
    app.include_router(clips.router, prefix=API_PREFIX)
    app.include_router(candidates.router, prefix=API_PREFIX)
    app.include_router(tasks.router, prefix=API_PREFIX)
    app.include_router(discovery.router, prefix=API_PREFIX)
    app.include_router(publish_channels.router, prefix=API_PREFIX)
    return app


def _register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ) -> JSONResponse:
        """Asocia un request_id a todos los logs de la peticion."""
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            structlog.contextvars.clear_contextvars()
        logger.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=elapsed_ms,
            request_id=request_id,
        )
        response.headers["X-Request-ID"] = request_id
        return response


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ClipForgeError)
    async def handle_app_error(_: Request, exc: ClipForgeError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("api.app_error", code=exc.code, message=exc.message, exc_info=exc)
        else:
            logger.info("api.app_error", code=exc.code, message=exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = _serializable_errors(exc.errors())
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    # Cuando el fallo es de una sola regla, su mensaje dice mucho
                    # mas que un "los datos no son validos" generico: es lo que
                    # acaba leyendo el usuario en el editor.
                    "message": _validation_message(errors),
                    "details": {"errors": errors},
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "http_error",
                    "message": str(exc.detail),
                    "details": {},
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.error("api.unhandled_exception", exc_info=exc)
        message = str(exc) if settings.debug else "Error interno del servidor"
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": message, "details": {}}},
        )


def _serializable_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Deja los errores de pydantic en algo que `json.dumps` acepte.

    Un validador propio que lanza `ValueError` deja la excepcion dentro de
    `ctx`, y serializarla revienta con un 500 justo cuando lo que habia era un
    422 perfectamente explicable.
    """
    cleaned: list[dict[str, Any]] = []
    for error in errors:
        if not isinstance(error, dict):
            cleaned.append({"msg": str(error)})
            continue
        item = {key: value for key, value in error.items() if key != "ctx"}
        context = error.get("ctx")
        if isinstance(context, dict):
            item["ctx"] = {key: str(value) for key, value in context.items()}
        cleaned.append(item)
    return cleaned


def _validation_message(errors: list[dict[str, Any]]) -> str:
    """Mensaje corto para el usuario a partir del primer error."""
    if len(errors) == 1:
        message = str(errors[0].get("msg", "")).removeprefix("Value error, ").strip()
        if message:
            return message
    return "Los datos enviados no son validos"


app = create_app()
