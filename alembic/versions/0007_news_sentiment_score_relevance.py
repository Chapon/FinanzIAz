"""OPS1(a) — ``news_events.sentiment_score`` + ``relevance``: polaridad numérica.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-09

Persiste, en la MISMA llamada del classify (costo marginal ~cero), la polaridad
numérica point-in-time: ``sentiment_score`` ∈ [-1,+1] y ``relevance`` ∈ [0,1].
Empieza a acumular histórico point-in-time de sentiment desde ya — el meta-modelo
del rediseño (tarea 9) lo va a querer como feature y sin histórico no hay
validación. NO entra a ninguna decisión (regla 3).

Idempotente con el mismo patrón de 0004/0005: chequeo de existencia con el
inspector antes del DDL, así una DB que ya tenga las columnas (p.ej. creada por
``Base.metadata.create_all`` en una DB nueva) pasa sin tocar nada.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    add_score = not _has_column("news_events", "sentiment_score")
    add_rel = not _has_column("news_events", "relevance")
    if not (add_score or add_rel):
        return
    with op.batch_alter_table("news_events") as batch_op:
        if add_score:
            batch_op.add_column(sa.Column("sentiment_score", sa.Float(), nullable=True))
        if add_rel:
            batch_op.add_column(sa.Column("relevance", sa.Float(), nullable=True))


def downgrade() -> None:
    drop_rel = _has_column("news_events", "relevance")
    drop_score = _has_column("news_events", "sentiment_score")
    if not (drop_rel or drop_score):
        return
    with op.batch_alter_table("news_events") as batch_op:
        if drop_rel:
            batch_op.drop_column("relevance")
        if drop_score:
            batch_op.drop_column("sentiment_score")
