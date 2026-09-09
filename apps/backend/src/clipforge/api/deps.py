"""Dependencias compartidas de FastAPI."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from clipforge.db.session import get_async_session
from clipforge.repositories.candidate_repository import CandidateRepository
from clipforge.repositories.clip_repository import ClipRepository
from clipforge.repositories.project_repository import ProjectRepository

DbSession = Annotated[AsyncSession, Depends(get_async_session)]


def get_project_repository(session: DbSession) -> ProjectRepository:
    return ProjectRepository(session)


ProjectRepo = Annotated[ProjectRepository, Depends(get_project_repository)]


def get_clip_repository(session: DbSession) -> ClipRepository:
    return ClipRepository(session)


ClipRepo = Annotated[ClipRepository, Depends(get_clip_repository)]


def get_candidate_repository(session: DbSession) -> CandidateRepository:
    return CandidateRepository(session)


CandidateRepo = Annotated[CandidateRepository, Depends(get_candidate_repository)]
