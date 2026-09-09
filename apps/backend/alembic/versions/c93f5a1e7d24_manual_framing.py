"""encuadre corregible a mano

Dos columnas con proposito distinto:

- `clip_candidates.crop_x`: la correccion del usuario. Con NULL manda el
  encuadre automatico; con un valor, ese valor gana y no se recalcula.
- `generated_clips.crop_x` y `crop_width`: el encuadre con el que se genero
  realmente el fichero. Es lo que el editor pinta sobre el video para enseniar
  que parte se quedo dentro, y sin guardarlo habria que rehacer el analisis
  solo para dibujar un rectangulo.

Revision ID: c93f5a1e7d24
Revises: b7c41d9e2a30
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c93f5a1e7d24"
down_revision: str | None = "b7c41d9e2a30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clip_candidates", sa.Column("crop_x", sa.Integer(), nullable=True))
    op.add_column("generated_clips", sa.Column("crop_x", sa.Integer(), nullable=True))
    op.add_column("generated_clips", sa.Column("crop_width", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("generated_clips", "crop_width")
    op.drop_column("generated_clips", "crop_x")
    op.drop_column("clip_candidates", "crop_x")
