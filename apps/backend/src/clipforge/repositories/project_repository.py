"""Acceso a datos de Project.

Los routers no escriben SQL: asi el mismo acceso se reutiliza desde el worker y
los tests pueden sustituirlo sin levantar FastAPI.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clipforge.db.models import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, project_id: uuid.UUID) -> Project | None:
        return await self.session.get(Project, project_id)

    async def list(self, *, limit: int = 20, offset: int = 0) -> Sequence[Project]:
        stmt = select(Project).order_by(Project.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Project))
        return int(result.scalar_one())

    async def delete(self, project: Project) -> None:
        await self.session.delete(project)
        await self.session.flush()
