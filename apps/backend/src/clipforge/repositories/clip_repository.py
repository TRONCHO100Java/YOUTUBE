"""Acceso a datos de clips renderizados."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from clipforge.db.models import ClipCandidate, GeneratedClip


class ClipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, clip_id: uuid.UUID) -> GeneratedClip | None:
        """Un clip con su candidato cargado.

        `joinedload` evita la carga perezosa síncrona del candidato dentro del
        contexto asíncrono, que fallaría con MissingGreenlet.
        """
        stmt = (
            select(GeneratedClip)
            .where(GeneratedClip.id == clip_id)
            .options(joinedload(GeneratedClip.candidate))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(self, project_id: uuid.UUID) -> Sequence[GeneratedClip]:
        """Clips del proyecto, del mejor al peor."""
        stmt = (
            select(GeneratedClip)
            .join(ClipCandidate, ClipCandidate.id == GeneratedClip.candidate_id)
            .where(ClipCandidate.project_id == project_id)
            .options(joinedload(GeneratedClip.candidate))
            .order_by(ClipCandidate.score.desc(), ClipCandidate.start_time)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
