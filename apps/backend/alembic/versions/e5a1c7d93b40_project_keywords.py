"""Palabras clave del proyecto.

El usuario sabe cosas del video que ni el titulo de YouTube ni la
transcripcion dicen: quien sale, como se le llama, que se busca para
encontrarlo. Sin un sitio donde escribirlas, esa informacion se perdia y los
titulos salian describiendo la escena en vez de nombrar a quien la protagoniza.

Revision ID: e5a1c7d93b40
Revises: c93f5a1e7d24
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5a1c7d93b40"
down_revision: str | None = "c93f5a1e7d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("keywords", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "keywords")
