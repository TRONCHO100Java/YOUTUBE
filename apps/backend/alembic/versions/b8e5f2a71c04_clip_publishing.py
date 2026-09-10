"""Publicacion y rendimiento de un clip.

El ultimo tramo manual del flujo era subir: abrir la carpeta y pegar titulo,
descripcion y etiquetas cinco veces por proyecto. Con el id del video subido
ademas se puede cerrar el circulo: releer sus vistas y comprobar si la
rubrica de siete dimensiones predijo algo o es decoracion.

Revision ID: b8e5f2a71c04
Revises: a1c9e6d3b872
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e5f2a71c04"
down_revision: str | None = "a1c9e6d3b872"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generated_clips", sa.Column("youtube_video_id", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "generated_clips", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "generated_clips", sa.Column("privacy_status", sa.String(length=16), nullable=True)
    )
    op.add_column("generated_clips", sa.Column("view_count", sa.Integer(), nullable=True))
    op.add_column("generated_clips", sa.Column("like_count", sa.Integer(), nullable=True))
    op.add_column(
        "generated_clips",
        sa.Column("stats_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    for column in (
        "stats_checked_at",
        "like_count",
        "view_count",
        "privacy_status",
        "published_at",
        "youtube_video_id",
    ):
        op.drop_column("generated_clips", column)
