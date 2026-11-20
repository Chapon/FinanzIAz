"""``claude_opinions.codigo_commit`` / ``codigo_wip``: con qué código salió cada opinión (tarea 433).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-19

Por qué
-------
La app corre lo que haya en el árbol de trabajo, WIP sin commitear incluido. El 2026-11-11 la
opinión de MU salió del WIP de la 425 —con un ``version_datos`` que ``HEAD`` no tenía— y nada lo
registraba. Con las dos columnas, la medición de la 321 puede separar las opiniones hechas con
código que no pasó por el done.

Nullable y sin default: ``NULL`` es «fila anterior a esta migración, no se sabe». Idempotente con
el patrón de la 0020.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "claude_opinions"
COLUMNAS = (
    ("codigo_commit", sa.String(length=40)),
    ("codigo_wip", sa.Boolean()),
)


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    faltan = [(n, t) for n, t in COLUMNAS if not _has_column(TABLA, n)]
    if not faltan:
        return
    with op.batch_alter_table(TABLA) as batch_op:
        for nombre, tipo in faltan:
            batch_op.add_column(sa.Column(nombre, tipo, nullable=True))


def downgrade() -> None:
    sobran = [n for n, _ in COLUMNAS if _has_column(TABLA, n)]
    if not sobran:
        return
    with op.batch_alter_table(TABLA) as batch_op:
        for nombre in sobran:
            batch_op.drop_column(nombre)
