"""``claude_opinions``: las opiniones de Claude pedidas desde la pestaña Análisis (tarea 320).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-05

Por qué
-------
La pestaña Análisis le pide a Claude (vía Claude Code, con la suscripción de Chapa) una opinión
con recomendación sobre una acción. Es display-only; se registra para medir después si acierta
(la tarea 321). UNIQUE ``(ticker, fecha)``: una por ticker y día.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "claude_opinions"
UX_CLAVE = "ux_claude_opinions_ticker_fecha"


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
            sa.Column("ticker", sa.String(length=20), nullable=False),
            sa.Column("fecha", sa.String(length=10), nullable=False),
            sa.Column("creado_at", sa.DateTime(), nullable=True),
            sa.Column("recomendacion", sa.String(length=10), nullable=False),
            sa.Column("confianza", sa.Integer(), nullable=False),
            sa.Column("precio", sa.Float(), nullable=True),
            sa.Column("modelo", sa.String(length=60), nullable=True),
            sa.Column("respuesta_json", sa.Text(), nullable=False),
            sa.Column("datos_json", sa.Text(), nullable=False),
            sa.Column("segundos", sa.Float(), nullable=True),
        )
    if not _has_index(TABLA, UX_CLAVE):
        op.create_index(UX_CLAVE, TABLA, ["ticker", "fecha"], unique=True)


def downgrade() -> None:
    if not _has_table(TABLA):
        return
    if _has_index(TABLA, UX_CLAVE):
        op.drop_index(UX_CLAVE, table_name=TABLA)
    op.drop_table(TABLA)
