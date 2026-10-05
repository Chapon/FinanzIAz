"""``paper_spinoff_adjustments``: los spin-offs aplicados a mano a posiciones abiertas (tarea 303).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-05

Por qué
-------
El scan no ajusta spin-offs (la 298 mostró que el factor de Yahoo no alcanza), y el aviso de
la 297 mandaba a *«revisar a mano»* sin que hubiera forma de hacerlo. Desde la 303,
``scripts/ajustar_spinoff.py`` ajusta la posición con ``q`` y ``r`` del comunicado y acredita
la escindida como caja; esta tabla es el registro que le da origen a esa caja en el cuadre
de la 266 y que impide aplicar el mismo evento dos veces.

UNIQUE ``(account_id, ticker, ex_date)``, como ``paper_split_adjustments`` (0016).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "paper_spinoff_adjustments"
IX_CUENTA = "ix_paper_spinoffadj_account"
UX_CLAVE = "ux_paper_spinoffadj_account_ticker_exdate"


def _has_table(table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names()


def _has_index(table: str, nombre: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(i["name"] == nombre for i in insp.get_indexes(table))


def upgrade() -> None:
    # Idempotencia por objeto, no con un `return` temprano (lección de la 74).
    if not _has_table(TABLA):
        op.create_table(
            TABLA,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("paper_accounts.id"), nullable=False),
            sa.Column("ticker", sa.String(length=20), nullable=False),
            sa.Column("ex_date", sa.String(length=10), nullable=False),
            sa.Column("child_ticker", sa.String(length=20), nullable=True),
            sa.Column("q", sa.Float(), nullable=False),
            sa.Column("r", sa.Float(), nullable=False),
            sa.Column("parent_price", sa.Float(), nullable=False),
            sa.Column("child_price", sa.Float(), nullable=False),
            sa.Column("shares_at_ex", sa.Float(), nullable=False),
            sa.Column("share_ratio", sa.Float(), nullable=False),
            sa.Column("shares_before", sa.Float(), nullable=False),
            sa.Column("shares_after", sa.Float(), nullable=False),
            sa.Column("avg_cost_before", sa.Float(), nullable=False),
            sa.Column("avg_cost_after", sa.Float(), nullable=False),
            sa.Column("hwm_before", sa.Float(), nullable=True),
            sa.Column("hwm_after", sa.Float(), nullable=True),
            sa.Column("cash", sa.Float(), nullable=False),
            sa.Column("applied_at", sa.DateTime(), nullable=True),
        )
    if not _has_index(TABLA, IX_CUENTA):
        op.create_index(IX_CUENTA, TABLA, ["account_id"], unique=False)
    if not _has_index(TABLA, UX_CLAVE):
        op.create_index(UX_CLAVE, TABLA, ["account_id", "ticker", "ex_date"], unique=True)


def downgrade() -> None:
    if not _has_table(TABLA):
        return
    if _has_index(TABLA, UX_CLAVE):
        op.drop_index(UX_CLAVE, table_name=TABLA)
    if _has_index(TABLA, IX_CUENTA):
        op.drop_index(IX_CUENTA, table_name=TABLA)
    op.drop_table(TABLA)
