"""Metadatos de publicacion del clip: variantes, descripcion y etiquetas.

El titulado ya escribia varias variantes por clip y se quedaba con una; las
demas se tiraban. Guardarlas convierte "este titulo no me convence" en un
clic en el editor en vez de en otra llamada al modelo. La descripcion y las
etiquetas son lo que faltaba para que subir un clip no sea escribir la caja
de YouTube a mano cinco veces por proyecto.

Revision ID: f7b2d4a916c8
Revises: e5a1c7d93b40
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7b2d4a916c8"
down_revision: str | None = "e5a1c7d93b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clip_candidates",
        sa.Column("title_variants", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("clip_candidates", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "clip_candidates",
        sa.Column("hashtags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clip_candidates", "hashtags")
    op.drop_column("clip_candidates", "description")
    op.drop_column("clip_candidates", "title_variants")
