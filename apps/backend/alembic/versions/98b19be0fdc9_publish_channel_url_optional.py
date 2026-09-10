"""publish channel url optional

Revision ID: 98b19be0fdc9
Revises: b3e6f01a94d7
Create Date: 2026-09-10 19:42:00.682977
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '98b19be0fdc9'
down_revision: str | None = 'b3e6f01a94d7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """La URL del canal pasa a ser opcional.

    La linea editorial se decide antes de que el canal exista en YouTube:
    primero se declara "esto es lo de Speed" y se le empiezan a apartar clips,
    y el canal se crea despues. Con la columna obligatoria habia que inventarse
    una URL falsa, que luego nadie recuerda cual era.
    """
    op.alter_column(
        "publish_channels",
        "url",
        existing_type=sa.Text(),
        nullable=True,
    )


def downgrade() -> None:
    """Volver atras exige que ninguna fila la tenga vacia.

    No se rellena con un texto de relleno: eso convertiria "todavia no tengo
    canal" en una URL rota indistinguible de una de verdad.
    """
    op.execute("DELETE FROM publish_channels WHERE url IS NULL")
    op.alter_column(
        "publish_channels",
        "url",
        existing_type=sa.Text(),
        nullable=False,
    )
