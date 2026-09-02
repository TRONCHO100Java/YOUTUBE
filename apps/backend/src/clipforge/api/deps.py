"""Dependencias compartidas de FastAPI."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from clipforge.db.session import get_async_session
from clipforge.repositories.project_repository import ProjectRepository

DbSession = Annotated[AsyncSession, Depends(get_async_session)]


def get_project_repository(session: DbSession) -> ProjectRepository:
    return ProjectRepository(session)


ProjectRepo = Annotated[ProjectRepository, Depends(get_project_repository)]
