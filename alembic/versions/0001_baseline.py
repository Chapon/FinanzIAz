"""Baseline schema (current state of database/models.py + paper_trading/models.py).

Revision ID: 0001
Revises:
Create Date: 2026-05-07

This is a *no-op* upgrade by design: it represents the schema that already
exists in ``Base.metadata.create_all`` so existing DBs can be brought into
the Alembic timeline without any data movement.

Onboarding instructions
-----------------------
- Brand-new DB:   ``alembic upgrade head``
- Existing DB:    ``alembic stamp head``  (tells Alembic the schema is
                  already at this revision; no DDL runs).

Future migrations should be generated with:
    alembic revision --autogenerate -m "describe change"
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Intentional no-op: tables/indexes are created via SQLAlchemy's
    # ``Base.metadata.create_all`` on app startup. This baseline exists
    # only so future ``--autogenerate`` revisions have a parent to chain
    # off of.
    pass


def downgrade() -> None:
    # Symmetric no-op.
    pass
