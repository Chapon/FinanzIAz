"""``paper_split_adjustments``: los splits ya aplicados a posiciones abiertas (tarea 262).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-02

Por qué
-------
El motor vivo no ajustaba las posiciones por split: un split N:1 dejaba ``shares``,
``avg_cost`` y ``high_water_mark`` en la escala vieja, la equity caía (1−1/N) en el primer
scan con el precio nuevo y el trailing o la señal vendían con una pérdida que no existe.
Desde la 262 el scan ajusta la posición; esta tabla es el ledger que lo hace idempotente.

UNIQUE ``(account_id, ticker, ex_date)``, como ``paper_dividend_credits`` (0014): el scan
corre muchas veces por día, y un doble ajuste duplicaría las acciones.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "paper_split_adjustments"
IX_CUENTA = "ix_paper_splitadj_account"
UX_CLAVE = "ux_paper_splitadj_account_ticker_exdate"


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
            sa.Column("ratio", sa.Float(), nullable=False),
            sa.Column("shares_before", sa.Float(), nullable=False),
            sa.Column("shares_after", sa.Float(), nullable=False),
            sa.Column("avg_cost_before", sa.Float(), nullable=False),
            sa.Column("avg_cost_after", sa.Float(), nullable=False),
            sa.Column("hwm_before", sa.Float(), nullable=True),
            sa.Column("hwm_after", sa.Float(), nullable=True),
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
