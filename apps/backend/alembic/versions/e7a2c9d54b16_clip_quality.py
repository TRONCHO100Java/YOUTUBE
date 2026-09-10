"""Informe de calidad del clip.

Todo lo anterior comprueba intenciones: que el juez puntue, que el montador
proponga, que el plan cuadre. Nada miraba el MP4 ya escrito, y ahi es donde se
ven los fallos que salen de un pipeline en el que ningun paso ha fallado: un
clip de seis segundos, uno mudo, uno que salio en negro.

Revision ID: e7a2c9d54b16
Revises: d3f8b1c62a95
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7a2c9d54b16"
down_revision: str | None = "d3f8b1c62a95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generated_clips",
        sa.Column("quality", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generated_clips", "quality")
