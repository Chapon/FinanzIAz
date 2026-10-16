"""``cloud_import_cursor``: hasta qué día bajó la app lo que juntó la nube (tarea 356).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-16

Por qué
-------
La Lambda de la 355 escribe consenso y noticias en DynamoDB, particionados por día de
captura UTC. La app los baja al arrancar (``data/nube_sync.py``) y necesita saber desde
qué día: una fila por tipo, que avanza en la misma transacción que las filas del día
(§11.5 de ``docs/harvest_nube_t196_2026-09-14.md``).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "cloud_import_cursor"


def _has_table(table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return table in insp.get_table_names()


def upgrade() -> None:
    # Idempotencia por objeto, no con un `return` temprano (lección de la 74).
    if not _has_table(TABLA):
        op.create_table(
            TABLA,
            sa.Column("tipo", sa.String(length=20), primary_key=True),
            sa.Column("ultimo_dia_importado", sa.String(length=10), nullable=False),
            sa.Column("importado_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    if _has_table(TABLA):
        op.drop_table(TABLA)
