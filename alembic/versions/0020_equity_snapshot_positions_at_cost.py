"""``paper_equity_snapshots.positions_at_cost``: cuántas posiciones fueron a costo (tarea 376).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-22

Por qué
-------
``compute_equity`` marca a ``avg_cost`` cada posición sin precio, y el snapshot no lo
registraba: el 2026-10-13 (127/127 sin precio por el throttle) la cuenta 2 quedó con
``positions_value`` **exacto** al costo, y Home, Paper y Métricas lo leyeron como valor de
mercado. Con la columna, los lectores saltean o rotulan esos snapshots.

Nullable y sin default: ``NULL`` es «fila anterior a esta migración, no se sabe», que no es
lo mismo que 0. Las filas viejas no se reconstruyen. Idempotente con el patrón de la 0008.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "paper_equity_snapshots"
COLUMNA = "positions_at_cost"


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if _has_column(TABLA, COLUMNA):
        return
    with op.batch_alter_table(TABLA) as batch_op:
        batch_op.add_column(sa.Column(COLUMNA, sa.Integer(), nullable=True))


def downgrade() -> None:
    if not _has_column(TABLA, COLUMNA):
        return
    with op.batch_alter_table(TABLA) as batch_op:
        batch_op.drop_column(COLUMNA)
