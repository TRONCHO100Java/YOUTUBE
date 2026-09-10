"""Desglose del juez.

La rubrica del juez tiene catorce dimensiones —once que suman y tres que
restan— y las siete columnas de puntuacion existentes se quedan cortas. Va en
JSONB porque es justo la parte del sistema que mas se va a iterar: ajustar un
peso no puede costar una migracion.

Revision ID: c2d7a4e91f38
Revises: b8e5f2a71c04
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c2d7a4e91f38"
down_revision: str | None = "b8e5f2a71c04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clip_candidates",
        sa.Column("judge_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clip_candidates", "judge_scores")
