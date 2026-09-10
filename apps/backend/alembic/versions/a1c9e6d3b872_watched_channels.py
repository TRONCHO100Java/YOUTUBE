"""Canales vigilados.

Hasta ahora el sistema esperaba a que alguien pegase una URL. Con esta tabla
los videos entran solos: se lee el RSS de cada canal cada pocos minutos y lo
que sea nuevo se encola.

`last_video_published_at` es la marca de agua, y es lo unico que impide que dar
de alta un canal encole sus quince ultimos videos de golpe.

Revision ID: a1c9e6d3b872
Revises: f7b2d4a916c8
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c9e6d3b872"
down_revision: str | None = "f7b2d4a916c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watched_channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("min_duration", sa.Integer(), nullable=True),
        sa.Column("max_duration", sa.Integer(), nullable=True),
        sa.Column("min_views", sa.Integer(), nullable=True),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("last_video_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("projects_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Unico: dar de alta dos veces el mismo canal lo procesaria dos veces.
    op.create_index(
        "ix_watched_channels_channel_id", "watched_channels", ["channel_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_watched_channels_channel_id", table_name="watched_channels")
    op.drop_table("watched_channels")
