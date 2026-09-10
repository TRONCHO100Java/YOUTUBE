"""De que va cada clip.

Un canal de Shorts funciona cuando lo que publica se parece entre si. Mezclar un
gag de un streamer con un recorte de un podcast de negocios no es variedad: es
un canal sin tema, y el algoritmo tarda mucho mas en entender a quien
ensenarselo.

Estas etiquetas —nicho, quien sale, de que va y que clase de momento es—
permiten repartir los clips entre canales sin abrirlos uno a uno.

Revision ID: f4b8d2e07c31
Revises: e7a2c9d54b16
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4b8d2e07c31"
down_revision: str | None = "e7a2c9d54b16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clip_candidates",
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clip_candidates", "tags")
