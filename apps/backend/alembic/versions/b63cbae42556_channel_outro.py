"""channel outro

Revision ID: b63cbae42556
Revises: 98b19be0fdc9
Create Date: 2026-09-10 19:55:50.707459
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b63cbae42556'
down_revision: str | None = '98b19be0fdc9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """El cierre que se pega al final de los clips de un canal.

    Tres columnas y no una: el nombre y la linea de texto son lo que el
    usuario decide, y la ruta es el resultado ya construido. Guardar solo la
    ruta obligaria a abrir el video para saber que pone, y guardar solo el
    texto obligaria a rehacer el cierre en cada render.
    """
    op.add_column("publish_channels", sa.Column("outro_handle", sa.String(120), nullable=True))
    op.add_column(
        "publish_channels", sa.Column("outro_tagline", sa.String(120), nullable=True)
    )
    op.add_column("publish_channels", sa.Column("outro_path", sa.Text(), nullable=True))


def downgrade() -> None:
    """Los ficheros de cierre quedan en disco: borrarlos no es cosa de una
    migracion, que solo sabe de la forma de la tabla.
    """
    op.drop_column("publish_channels", "outro_path")
    op.drop_column("publish_channels", "outro_tagline")
    op.drop_column("publish_channels", "outro_handle")
