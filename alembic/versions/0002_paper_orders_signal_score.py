"""Add ``signal_score`` column to ``paper_orders``.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-15

Stores the conviction score (in [0,1]) that the strategy attached to each
order. Previously the score was only embedded in the ``reason`` text field
(e.g. ``"analyze SELL (0.36)"``), which made downstream analytics painful
and prevented gates from filtering on strength.

Existing rows: leave ``signal_score`` NULL. The engine treats NULL as
"unknown" and falls back to the legacy reason-parsing where needed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("paper_orders") as batch_op:
        batch_op.add_column(sa.Column("signal_score", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("paper_orders") as batch_op:
        batch_op.drop_column("signal_score")
