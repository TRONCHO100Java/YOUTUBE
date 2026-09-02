"""Acceso a datos de Project.

Los routers no escriben SQL: asi el mismo acceso se reutiliza desde el worker y
los tests pueden sustituirlo sin levantar FastAPI.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from clipforge.db.models import Project, Transcript


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, project: Project) -> Project:
        self.session.add(project)
        await self.session.flush()
        return project

    async def get(self, project_id: uuid.UUID) -> Project | None:
        return await self.session.get(Project, project_id)

    async def list(self, *, limit: int = 20, offset: int = 0) -> Sequence[Project]:
        stmt = select(Project).order_by(Project.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Project))
        return int(result.scalar_one())

    async def get_transcript(self, project_id: uuid.UUID) -> Transcript | None:
        """Transcripcion del proyecto con sus segmentos ya cargados.

        `selectinload` evita el N+1 y, sobre todo, evita cargas perezosas
        sincronas dentro del contexto asincrono.
        """
        stmt = (
            select(Transcript)
            .where(Transcript.project_id == project_id)
            .options(selectinload(Transcript.segments))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete(self, project: Project) -> None:
        await self.session.delete(project)
        await self.session.flush()
