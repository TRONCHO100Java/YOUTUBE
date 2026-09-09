"""Acceso a datos de candidatos a clip.

Existe desde que los candidatos dejaron de ser solo salida del análisis: ahora
el usuario los crea, los mueve y los borra desde el editor, así que necesitan
las operaciones completas y no solo la lectura que hacía `ProjectRepository`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from clipforge.db.models import ClipCandidate


class CandidateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, candidate_id: uuid.UUID) -> ClipCandidate | None:
        """Un candidato con su clip cargado.

        `selectinload` evita la carga perezosa síncrona del clip dentro del
        contexto asíncrono, que fallaría con MissingGreenlet al serializar.
        """
        stmt = (
            select(ClipCandidate)
            .where(ClipCandidate.id == candidate_id)
            # `project` hace falta para validar que un rango nuevo cabe en el
            # video; cargarlo aqui evita una carga perezosa sincrona.
            .options(
                selectinload(ClipCandidate.generated_clip),
                selectinload(ClipCandidate.project),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(self, project_id: uuid.UUID) -> Sequence[ClipCandidate]:
        """Candidatos del proyecto, del mejor al peor.

        Los manuales van primero a igualdad de puntuación: los ha hecho una
        persona, y enterrarlos bajo propuestas automáticas sería absurdo.
        """
        stmt = (
            select(ClipCandidate)
            .where(ClipCandidate.project_id == project_id)
            .options(selectinload(ClipCandidate.generated_clip))
            .order_by(ClipCandidate.score.desc(), ClipCandidate.start_time)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def add(self, candidate: ClipCandidate) -> ClipCandidate:
        self.session.add(candidate)
        await self.session.flush()
        return candidate

    async def delete(self, candidate: ClipCandidate) -> None:
        await self.session.delete(candidate)
        await self.session.flush()

    async def next_rank(self, project_id: uuid.UUID) -> int:
        """Siguiente hueco de numeración del proyecto.

        Los rangos no son únicos por diseño —el nombre del fichero lleva además
        el id— pero mantenerlos ordenados hace que la carpeta de exportación se
        lea como una lista y no como un revoltijo.
        """
        result = await self.session.execute(
            select(func.max(ClipCandidate.rank)).where(ClipCandidate.project_id == project_id)
        )
        return int(result.scalar() or 0) + 1
