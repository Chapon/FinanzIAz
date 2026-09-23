"""``dividend_calendar_cache``: el calendario de ex-dates, para que el VS SPY compare total contra total (tarea 221).

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-23

Por qué hace falta una tabla y no alcanzaba la que ya estaba
------------------------------------------------------------
``dividend_cache`` existe desde el baseline y guarda **el acumulado desde una
fecha hasta hoy** (``total_per_share``), con TTL de 6 h. Esa forma contesta
*"¿cuánto cobró esta posición abierta?"* — que es lo que consume la pestaña de
cartera real (``ui/portfolio_tab.py``) — y **no** contesta *"¿cuánto devengó la
cuenta entre estas dos fechas?"*, que es lo que el VS SPY necesita.

Derivar un intervalo del acumulado obliga a ``since(t0) − since(t1)``, o sea a
restar dos filas **fetcheadas en momentos distintos**. Un ex-date que caiga entre
los dos fetches corrompe la resta sin error y sin log. Y el TTL de 6 h está de
más para este uso: un ex-date pasado no cambia nunca.

Qué mide esto, y por qué importa (tarea 220 → 221)
---------------------------------------------------
El harness corre sobre barras bajadas con ``auto_adjust=True``, o sea series
total-return: cobra dividendos implícitamente. ``paper_trading/`` no los menciona
en ninguna línea: la cuenta pasa por el ex-date, ve caer el precio y no recibe el
efectivo. Medido sobre las tenencias reales de la cuenta 2 el 2026-09-21:
**$322,77 en 3,05 meses = 2,54%/año**, el 62% de todo el P&L realizado.

El panel de métricas compara ese retorno **de precio** contra un SPY
**total-return**, así que resta peras de manzanas: reporta −1,05pp donde la
comparación honesta da −0,40pp. Esta tabla es el insumo que lo corrige.

Estado de la DB viva al escribir esta revisión (2026-09-23)
------------------------------------------------------------
La tabla no existe. ``dividend_cache`` tiene 971 filas y **no se toca**: sigue
sirviendo a ``ui/portfolio_tab.py``, que es otro consumidor con otra pregunta.

**Idempotente** (mismo patrón que 0004/0005/0006): chequeo de existencia con el
inspector antes del DDL, así una DB nueva creada por ``Base.metadata.create_all``
—que ya la trae con su índice— pasa sin tocar nada.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "dividend_calendar_cache"
IX_TICKER = "ix_dividend_calendar_cache_ticker"
UX_CLAVE = "ux_divcal_ticker_exdate"


def _has_table(table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names()


def _has_index(table: str, nombre: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(i["name"] == nombre for i in insp.get_indexes(table))


def upgrade() -> None:
    # La idempotencia se evalúa por OBJETO y no de una: `if _has_table(...): return`
    # parece equivalente y no lo es — sobre una DB que tiene la tabla pero perdió los
    # índices, el return temprano los deja faltando para siempre. Es exactamente el
    # drift que la tarea 74 encontró (24 índices declarados que no existían en la DB) y
    # su guard `test_upgrade_restaura_todos_los_indices_declarados` cazó esta revisión
    # con ese error puesto.
    if not _has_table(TABLA):
        op.create_table(
            TABLA,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ticker", sa.String(length=20), nullable=False),
            sa.Column("ex_date", sa.String(length=10), nullable=False),  # 'YYYY-MM-DD'
            sa.Column("amount", sa.Float(), nullable=False),  # $/acción, sin ajustar por splits
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
        )
    if not _has_index(TABLA, IX_TICKER):
        op.create_index(IX_TICKER, TABLA, ["ticker"], unique=False)
    if not _has_index(TABLA, UX_CLAVE):
        # UNIQUE y no un índice común: el invariante es "una fila por ex-date". Sin él,
        # dos warm-ups concurrentes duplican la fila y el devengado de la cuenta sale al
        # DOBLE — que se lee como rendimiento, no como bug. Es la misma lección que la
        # 0012: lo que sostiene un invariante es el esquema, no un `if` en Python.
        op.create_index(UX_CLAVE, TABLA, ["ticker", "ex_date"], unique=True)


def downgrade() -> None:
    if not _has_table(TABLA):
        return
    if _has_index(TABLA, UX_CLAVE):
        op.drop_index(UX_CLAVE, table_name=TABLA)
    if _has_index(TABLA, IX_TICKER):
        op.drop_index(IX_TICKER, table_name=TABLA)
    op.drop_table(TABLA)
