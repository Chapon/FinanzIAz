"""Catch-up: alinea el timeline alembic con el esquema real post-0003 (T7.3).

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-11

Cierra M1 del code review 2026-06-09: entre 0003 (2026-05-19) y hoy el esquema
evolucionó por fuera de alembic, vía ``Base.metadata.create_all`` (tablas
nuevas) y parches ``ALTER TABLE`` manuales en ``database.models._migrate``
(columnas nuevas). Esta revisión congela ese delta en el timeline para que
alembic vuelva a ser el único camino de esquema.

Delta cubierto (medido con ``git diff c3070e3..HEAD`` sobre los models):

- Tablas nuevas (Sprint 5 / caches): ``earnings_cache``, ``analyst_data_cache``,
  ``news_events``, ``analyst_estimate_snapshots``.
- Columnas nuevas: ``paper_accounts.slack_notify`` (T12),
  ``paper_equity_snapshots.portfolio_sigma`` (T10).
- Parche legacy absorbido: ``positions.purchase_date`` (pre-baseline, vivía
  solo en ``_migrate``).

**Idempotente por diseño**: toda DB real ya tiene estos objetos (los creó
create_all/_migrate), así que cada paso chequea existencia con el inspector
antes de ejecutar DDL. Una DB stampeada en 0003 con esquema completo pasa por
acá sin tocar nada; una DB que de verdad esté en estado-0003 recibe el DDL.

Las definiciones están CONGELADAS (DDL explícito, no se importa
``Base.metadata``): si los models cambian mañana, eso es una revisión 0005,
no un cambio retroactivo de esta.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tablas que esta revisión introduce (en orden de creación).
_NEW_TABLES = ("earnings_cache", "analyst_data_cache", "news_events", "analyst_estimate_snapshots")


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(insp, table: str, column: str) -> bool:
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    insp = _inspector()
    existing = set(insp.get_table_names())

    if "earnings_cache" not in existing:
        op.create_table(
            "earnings_cache",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ticker", sa.String(20), nullable=False),
            sa.Column("earnings_date", sa.DateTime(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_earnings_cache_ticker", "earnings_cache", ["ticker"])
        op.create_index("ix_earnings_cache_fetched_at", "earnings_cache", ["fetched_at"])
        op.create_index("ix_earnings_cache_ticker_fetched", "earnings_cache", ["ticker", "fetched_at"])

    if "analyst_data_cache" not in existing:
        op.create_table(
            "analyst_data_cache",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ticker", sa.String(20), nullable=False),
            sa.Column("data_json", sa.Text(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_analyst_data_cache_ticker", "analyst_data_cache", ["ticker"])
        op.create_index("ix_analyst_data_cache_fetched_at", "analyst_data_cache", ["fetched_at"])
        op.create_index("ix_analyst_cache_ticker_fetched", "analyst_data_cache", ["ticker", "fetched_at"])

    if "news_events" not in existing:
        op.create_table(
            "news_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ticker", sa.String(20), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("source", sa.String(50), nullable=False),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
            sa.Column("content_hash", sa.String(40), nullable=False),
            sa.Column("event_type", sa.String(40), nullable=True),
            sa.Column("sentiment", sa.String(12), nullable=True),
            sa.Column("classifier_confidence", sa.Float(), nullable=True),
            sa.Column("classified_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_news_events_ticker", "news_events", ["ticker"])
        op.create_index("ix_news_events_fetched_at", "news_events", ["fetched_at"])
        op.create_index("ix_news_ticker_published", "news_events", ["ticker", "published_at"])
        op.create_index("ix_news_content_hash", "news_events", ["content_hash"], unique=True)
        op.create_index("ix_news_unclassified", "news_events", ["event_type"])

    if "analyst_estimate_snapshots" not in existing:
        op.create_table(
            "analyst_estimate_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ticker", sa.String(20), nullable=False),
            sa.Column("metric", sa.String(24), nullable=False),
            sa.Column("period_label", sa.String(16), nullable=True),
            sa.Column("consensus_value", sa.Float(), nullable=True),
            sa.Column("num_analysts", sa.Integer(), nullable=True),
            sa.Column("snapshot_date", sa.DateTime(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_analyst_estimate_snapshots_ticker", "analyst_estimate_snapshots", ["ticker"])
        op.create_index(
            "ix_analyst_estimate_snapshots_snapshot_date", "analyst_estimate_snapshots", ["snapshot_date"]
        )
        op.create_index(
            "ix_est_ticker_metric_date", "analyst_estimate_snapshots", ["ticker", "metric", "snapshot_date"]
        )

    # --- Columnas (ex-parches de _migrate) -------------------------------
    # Refrescar inspector: SQLAlchemy cachea la metadata reflejada.
    insp = _inspector()

    if not _has_column(insp, "paper_accounts", "slack_notify"):
        with op.batch_alter_table("paper_accounts") as batch_op:
            batch_op.add_column(
                sa.Column("slack_notify", sa.Boolean(), nullable=True, server_default=sa.text("1"))
            )

    if not _has_column(insp, "paper_equity_snapshots", "portfolio_sigma"):
        with op.batch_alter_table("paper_equity_snapshots") as batch_op:
            batch_op.add_column(sa.Column("portfolio_sigma", sa.Float(), nullable=True))

    if not _has_column(insp, "positions", "purchase_date"):
        with op.batch_alter_table("positions") as batch_op:
            batch_op.add_column(sa.Column("purchase_date", sa.DateTime(), nullable=True))


def downgrade() -> None:
    insp = _inspector()
    existing = set(insp.get_table_names())

    has = _has_column
    if "positions" in existing and has(insp, "positions", "purchase_date"):
        with op.batch_alter_table("positions") as batch_op:
            batch_op.drop_column("purchase_date")
    if "paper_equity_snapshots" in existing and has(insp, "paper_equity_snapshots", "portfolio_sigma"):
        with op.batch_alter_table("paper_equity_snapshots") as batch_op:
            batch_op.drop_column("portfolio_sigma")
    if "paper_accounts" in existing and has(insp, "paper_accounts", "slack_notify"):
        with op.batch_alter_table("paper_accounts") as batch_op:
            batch_op.drop_column("slack_notify")

    for table in reversed(_NEW_TABLES):
        if table in existing:
            op.drop_table(table)
