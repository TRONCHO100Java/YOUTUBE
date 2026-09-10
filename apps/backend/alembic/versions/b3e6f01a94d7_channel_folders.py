"""Clips borrables y cada canal con su carpeta.

Tres cosas que van juntas porque describen el mismo flujo: un clip se sube, se
marca, y se borra para dejar sitio; y para saber a que carpeta va, tanto el
proyecto como el canal vigilado que lo trajo apuntan a un canal de destino.

El destino explicito manda sobre el reparto por etiquetas: "vigilo a Speed y
sus clips van a mi canal de Speed" no deberia depender de que el etiquetador
acierte.

Revision ID: b3e6f01a94d7
Revises: a9c4e1b73d28
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3e6f01a94d7"
down_revision: str | None = "a9c4e1b73d28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generated_clips", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    for table in ("projects", "watched_channels"):
        op.add_column(table, sa.Column("publish_channel_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_publish_channel",
            table,
            "publish_channels",
            ["publish_channel_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in ("watched_channels", "projects"):
        op.drop_constraint(f"fk_{table}_publish_channel", table, type_="foreignkey")
        op.drop_column(table, "publish_channel_id")
    op.drop_column("generated_clips", "deleted_at")
