"""``claude_opinions_reemplazadas``: la opinión que se pisa al pedirla de nuevo el mismo día (tarea 438).

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-19

Por qué
-------
``claude_opinions`` guarda una por ``(ticker, día)`` y pedirla de nuevo la reemplaza (la 320, a
propósito: la medición de la 321 no cuenta dos veces la misma decisión). El 2026-11-11 la de MU se
pisó dos veces y con ella la evidencia de origen de ocho tareas abiertas. Chapa eligió el
2026-11-19 un histórico: ``claude_opinions`` sigue igual, y la fila que se reemplaza se copia acá
antes, con cuándo se reemplazó. Idempotente por objeto, como la 0018.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "claude_opinions_reemplazadas"
IX = "ix_claude_opinions_reemplazadas_ticker_fecha"


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, nombre: str) -> bool:
    return any(i["name"] == nombre for i in sa.inspect(op.get_bind()).get_indexes(table))


def upgrade() -> None:
    if not _has_table(TABLA):
        op.create_table(
            TABLA,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("opinion_id", sa.Integer(), nullable=True),
            sa.Column("reemplazada_at", sa.DateTime(), nullable=True),
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
            sa.Column("codigo_commit", sa.String(length=40), nullable=True),
            sa.Column("codigo_wip", sa.Boolean(), nullable=True),
        )
    if not _has_index(TABLA, IX):
        op.create_index(IX, TABLA, ["ticker", "fecha"])


def downgrade() -> None:
    if not _has_table(TABLA):
        return
    if _has_index(TABLA, IX):
        op.drop_index(IX, table_name=TABLA)
    op.drop_table(TABLA)
