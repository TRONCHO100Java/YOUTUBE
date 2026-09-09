"""senales, perfil de contenido y candidatos manuales

Anade lo que necesitan tres cosas nuevas:

- **Senales no verbales** (`projects.signals`): la linea de tiempo de energia,
  cortes y movimiento que sustituye a la transcripcion cuando el video no habla.
- **Perfil de contenido** (`projects.content_profile`, `projects.speech_ratio`):
  que rubrica y que duraciones se le han aplicado al video, y el dato que lo
  decidio.
- **Origen del candidato** (`clip_candidates.source`): distingue lo que produjo
  la maquina de lo que ha recortado una persona. Sin esta columna, reprocesar
  un proyecto borraria los clips manuales del usuario.

Los estados nuevos de `ProjectStatus` (NEEDS_REVIEW) no necesitan migracion:
la columna es VARCHAR sin CHECK, porque `SAEnum(native_enum=False)` no crea la
restriccion por defecto.

Revision ID: b7c41d9e2a30
Revises: 22621ad022bb
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7c41d9e2a30"
down_revision: str | None = "22621ad022bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "content_profile",
            sa.Enum(
                "TALKING",
                "VISUAL",
                name="content_profile",
                native_enum=False,
                length=16,
            ),
            nullable=True,
        ),
    )
    op.add_column("projects", sa.Column("speech_ratio", sa.Float(), nullable=True))
    op.add_column(
        "projects",
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # server_default para que las filas existentes queden como AI, que es lo que
    # eran: todo lo que hay en la tabla lo propuso el analisis de la FASE 4.
    op.add_column(
        "clip_candidates",
        sa.Column(
            "source",
            sa.Enum(
                "AI",
                "SIGNAL",
                "MANUAL",
                name="candidate_source",
                native_enum=False,
                length=16,
            ),
            nullable=False,
            server_default="AI",
        ),
    )
    op.create_index(
        "ix_clip_candidates_source", "clip_candidates", ["source"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_clip_candidates_source", table_name="clip_candidates")
    op.drop_column("clip_candidates", "source")
    op.drop_column("projects", "signals")
    op.drop_column("projects", "speech_ratio")
    op.drop_column("projects", "content_profile")
