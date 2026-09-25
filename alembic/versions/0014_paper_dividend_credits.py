"""``paper_dividend_credits``: el ledger de dividendos acreditados al motor (tarea 222).

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-25

Qué cambia, y por qué hace falta un ledger
-------------------------------------------
Hasta la **221** el motor no miraba dividendos: la cuenta pasaba por el ex-date, veía
caer el precio y **no recibía el efectivo** — $322,77 en 3,05 meses sobre la cuenta 2,
el 62% de todo su P&L realizado. La 221 corrigió la **medición** (el VS SPY compara
total contra total) y dejó el cableado al motor como tarea aparte, que es ésta.

Chapa eligió **caja al ex-date**: el efectivo entra al balance y queda disponible, así
que participa del sizing de las compras siguientes. Con eso hace falta saber **qué ya se
acreditó**, y eso es lo que guarda esta tabla. No alcanza con derivarlo del calendario:
el scan corre varias veces por día y puede correr después de días cerrado, así que sin
un registro explícito el mismo ex-date se acreditaría de nuevo en cada pasada — y un
doble crédito **no se lee como bug, se lee como rendimiento**.

El UNIQUE es el invariante
---------------------------
``(account_id, ticker, ex_date)`` va UNIQUE y no como índice común, por la misma razón
que en la 0012 y la 0013: **lo que sostiene un invariante es el esquema, no un ``if`` en
Python**. El `if` de Python protege al scan de hoy; el UNIQUE protege también al scan que
corra en paralelo, al script ad-hoc y al bug que todavía no escribí.

Sólo hacia adelante
--------------------
Decisión de Chapa: no se backfillean los $322,77 ya devengados. La tabla arranca vacía y
el motor acredita desde el primer ex-date que caiga en la ventana ``(último scan, hoy]``,
así que el historial de la cuenta **no se re-escribe** y ninguna métrica publicada cambia
de base retroactivamente.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "paper_dividend_credits"
IX_CUENTA = "ix_paper_divcred_account"
UX_CLAVE = "ux_paper_divcred_account_ticker_exdate"


def _has_table(table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names()


def _has_index(table: str, nombre: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(i["name"] == nombre for i in insp.get_indexes(table))


def upgrade() -> None:
    # Idempotencia por OBJETO y no de una (lección de la 74, que cazó a la 0013 con el
    # `return` temprano puesto): sobre una DB que tiene la tabla y perdió los índices,
    # un `if _has_table(...): return` los deja faltando para siempre.
    if not _has_table(TABLA):
        op.create_table(
            TABLA,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("ticker", sa.String(length=20), nullable=False),
            sa.Column("ex_date", sa.String(length=10), nullable=False),  # 'YYYY-MM-DD'
            # Las tres se guardan aunque `cash = shares * amount_per_share`: el ledger
            # tiene que poder auditarse sin re-derivar nada desde un calendario que para
            # entonces puede haber cambiado de fila.
            sa.Column("shares", sa.Float(), nullable=False),
            sa.Column("amount_per_share", sa.Float(), nullable=False),
            sa.Column("cash", sa.Float(), nullable=False),
            sa.Column("credited_at", sa.DateTime(), nullable=True),
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
