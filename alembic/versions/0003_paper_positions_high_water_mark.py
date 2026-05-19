"""Add ``high_water_mark`` column to ``paper_positions``.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-18

Stores the highest live price seen since a position was opened (or partially
added to). Required by the ATR trailing-stop gate introduced in T01 of the
engine roadmap.

Existing rows: leave ``high_water_mark`` NULL. The engine treats NULL as
"not yet observed" and seeds it with the current tick price on the next scan
so the trailing stop has a baseline before it can fire.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("paper_positions") as batch_op:
        batch_op.add_column(sa.Column("high_water_mark", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("paper_positions") as batch_op:
        batch_op.drop_column("high_water_mark")
