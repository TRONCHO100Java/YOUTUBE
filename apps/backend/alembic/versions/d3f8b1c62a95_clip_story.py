"""Como se cuenta cada clip.

El montador decide por donde empieza de verdad el clip, que contexto falta y
donde cae el remate. Se guarda para poder repetir un render identico sin volver
a llamar al modelo, y para poder corregirlo a mano mas adelante.

Revision ID: d3f8b1c62a95
Revises: c2d7a4e91f38
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3f8b1c62a95"
down_revision: str | None = "c2d7a4e91f38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clip_candidates",
        sa.Column("story", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clip_candidates", "story")
