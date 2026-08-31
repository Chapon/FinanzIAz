"""ALRT1 — ``alerts.is_paused``: estado "pausada" separado de is_active.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-11

Una alerta pausada deja de evaluarse en ``check_alerts`` sin borrarla y sin
pisar la semántica de ``is_active`` (que ya vale "disparada" cuando es False).
Columna Boolean NOT NULL con server_default false → las filas existentes quedan
como no-pausadas. NO toca decisiones de trading (regla 3).

Idempotente con el mismo patrón de 0004/0005/0007: guard con el inspector antes
del DDL, así una DB que ya tenga la columna (p.ej. creada por
``Base.metadata.create_all`` en una DB nueva) pasa sin tocar nada.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if _has_column("alerts", "is_paused"):
        return
    with op.batch_alter_table("alerts") as batch_op:
        batch_op.add_column(sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    if not _has_column("alerts", "is_paused"):
        return
    with op.batch_alter_table("alerts") as batch_op:
        batch_op.drop_column("is_paused")
