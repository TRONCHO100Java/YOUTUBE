"""Canales de destino.

No confundir con watched_channels, que es de donde SALEN los videos. Estos son
los canales propios a los que van los clips ya hechos.

Existen porque un canal de Shorts funciona cuando lo que publica se parece entre
si. Con varios a la vez —uno de Speed, otro de Among Us— hay que decidir que
clip va a cual, y hacerlo a mano cinco veces por video no escala. El reparto se
apoya en las etiquetas que ya pone el etiquetador.

Revision ID: a9c4e1b73d28
Revises: f4b8d2e07c31
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9c4e1b73d28"
down_revision: str | None = "f4b8d2e07c31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publish_channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("youtube_channel_id", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("niche", sa.String(length=64), nullable=True),
        sa.Column("people", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("topics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("kinds", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("min_score", sa.Float(), server_default="0", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("publish_channels")
