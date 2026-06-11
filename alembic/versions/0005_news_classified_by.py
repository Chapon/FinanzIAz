"""T7.4 — ``news_events.classified_by``: provenance del backend clasificador.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-11

Cierra M3 del code review 2026-06-09: el tag ``Classification.classifier``
("heuristic" / "ollama" / "llm" / "fallback") vivía solo en logs. Persistirlo
habilita QA de accuracy por backend y detectar a posteriori corridas donde
Ollama estuvo caído (filas no-SEC etiquetadas "heuristic" en un run hybrid-ollama).

Idempotente con el mismo patrón de 0004: chequeo de existencia con el
inspector antes del DDL, así una DB que ya tenga la columna (p.ej. creada por
``Base.metadata.create_all`` en una DB nueva) pasa sin tocar nada.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("news_events", "classified_by"):
        with op.batch_alter_table("news_events") as batch_op:
            batch_op.add_column(sa.Column("classified_by", sa.String(20), nullable=True))


def downgrade() -> None:
    if _has_column("news_events", "classified_by"):
        with op.batch_alter_table("news_events") as batch_op:
            batch_op.drop_column("classified_by")
