"""Engines y sesiones.

Dos engines sobre los MISMOS modelos:
  * async (asyncpg) -> FastAPI
  * sync  (psycopg) -> worker Celery, Alembic y scripts

Es la forma menos friccionada de tener una API asincrona y un worker sincrono
sin duplicar el modelo de datos.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from clipforge.core.config import settings

async_engine = create_async_engine(
    settings.async_database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
    autoflush=False,
)

sync_engine = create_engine(
    settings.sync_database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False, autoflush=False)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Dependencia FastAPI: una sesion por request, rollback ante excepcion."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@contextmanager
def sync_session_scope() -> Iterator[Session]:
    """Sesion transaccional para tareas Celery."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
