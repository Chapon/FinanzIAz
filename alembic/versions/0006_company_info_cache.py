"""V2 — ``company_info_cache``: cache persistente de nombre/sector/industria.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-08

Habilita la exposición sectorial del panel de concentración (V2) y evita
re-scrapear ``yfinance.Ticker(t).info`` (lento) en cada ``get_company_info``.

Idempotente (mismo patrón que 0004/0005): chequeo de existencia con el
inspector antes del DDL, así una DB nueva creada por ``Base.metadata.create_all``
pasa sin tocar nada.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names()


def upgrade() -> None:
    if _has_table("company_info_cache"):
        return
    op.create_table(
        "company_info_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("sector", sa.String(length=100), nullable=True),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_company_info_cache_ticker", "company_info_cache", ["ticker"], unique=True)


def downgrade() -> None:
    if not _has_table("company_info_cache"):
        return
    op.drop_index("ix_company_info_cache_ticker", table_name="company_info_cache")
    op.drop_table("company_info_cache")
