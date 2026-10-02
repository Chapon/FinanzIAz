"""``paper_scan_candidates``: qué candidatos a compra evaluó cada scan y cómo terminaron (tarea 256).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-01

Por qué
-------
``paper_orders`` guarda lo que se **ejecutó**. Lo que el scan **descartó** —sin lugar,
frenado por un gate, filtrado por el screen— no quedaba en ningún lado, y *«¿por qué no
compramos ACN en julio?»* sólo se pudo reconstruir desde el store PIT del harness, cuyo
score no coincide con el vivo. Esta tabla es el registro que faltaba.

Sólo registro: el motor no la lee y ninguna decisión depende de ella. La escribe el scan,
en una sesión propia después de commitear, y la poda a 90 días.

Sin UNIQUE a propósito
----------------------
A diferencia de la 0012, la 0013 y la 0014, acá no hay un invariante que sostener: dos
scans en el mismo segundo son dos registros. Los dos índices son para las consultas que la
justifican —por cuenta y fecha, y por ticker— y para que la poda no recorra la tabla.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "paper_scan_candidates"
IX_CUENTA_SCAN = "ix_paper_scancand_account_scan"
IX_TICKER = "ix_paper_scancand_ticker"


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
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("scan_at", sa.DateTime(), nullable=False),
            sa.Column("ticker", sa.String(length=20), nullable=False),
            sa.Column("outcome", sa.String(length=20), nullable=False),
            sa.Column("signal_score", sa.Float(), nullable=True),
            sa.Column("rank", sa.Integer(), nullable=True),
            sa.Column("detail", sa.String(length=300), nullable=True),
        )
    if not _has_index(TABLA, IX_CUENTA_SCAN):
        op.create_index(IX_CUENTA_SCAN, TABLA, ["account_id", "scan_at"], unique=False)
    if not _has_index(TABLA, IX_TICKER):
        op.create_index(IX_TICKER, TABLA, ["ticker"], unique=False)


def downgrade() -> None:
    if not _has_table(TABLA):
        return
    if _has_index(TABLA, IX_TICKER):
        op.drop_index(IX_TICKER, table_name=TABLA)
    if _has_index(TABLA, IX_CUENTA_SCAN):
        op.drop_index(IX_CUENTA_SCAN, table_name=TABLA)
    op.drop_table(TABLA)
