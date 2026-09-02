"""Saca los dos índices de ``price_cache`` que nadie usa (tarea 81).

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-02

La **0009** creó los 24 índices declarados que nunca habían llegado a la DB, y
declaró en su momento que **los tres de `price_cache` eran el 100% del costo**
(+33,1 MB de +33,1 MB) y que **dos de los tres no tenían consumidor**. Se
crearon igual, por el precedente de la **53**: *mecanismo shipeado, política sin
cambiar* — hacer coincidir lo declarado con lo real era el mecanismo; sacar un
índice de un model es otra decisión.

Esta revisión es esa decisión, y está **medida con `EXPLAIN QUERY PLAN`**, no
argumentada:

- ``ix_price_cache_ticker`` (**4,6 MB**) es **prefijo** del compuesto. Su único
  plan —el delete por ticker de ``market_data_service``— pasa de
  ``COVERING INDEX ix_price_cache_ticker`` a
  ``COVERING INDEX ix_price_cache_ticker_fetched``: sigue sin tocar la tabla.
- ``ix_price_cache_fetched_at`` (**13,5 MB**) parecía ganarse el lugar con el
  archivador de la 81, que filtra por ``fetched_at < corte``. **No se lo gana:**
  el plan es ``SCAN price_cache`` con la tabla entera (401k filas) *y* con la
  tabla podada (34k) — el rango selecciona demasiado como para que el índice
  convenga. La hipótesis se planteó, se midió y **no se cumplió**.

Los tres consumidores reales de la tabla quedan servidos por el compuesto:
``get_current_price`` (ticker + ventana de TTL, ordenado por fecha), el batch
(``ticker IN`` + ventana) y el delete por ticker.

**Idempotente**: chequea con el inspector antes de cada ``DROP``, así que una DB
que nunca los tuvo pasa sin hacer nada.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOBRAN = (
    ("ix_price_cache_ticker", "price_cache"),
    ("ix_price_cache_fetched_at", "price_cache"),
)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tablas = set(insp.get_table_names())
    for nombre, tabla in _SOBRAN:
        if tabla not in tablas:
            continue
        if any(i["name"] == nombre for i in insp.get_indexes(tabla)):
            op.drop_index(nombre, table_name=tabla)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tablas = set(insp.get_table_names())
    for nombre, tabla in _SOBRAN:
        if tabla not in tablas:
            continue
        if not any(i["name"] == nombre for i in insp.get_indexes(tabla)):
            op.create_index(nombre, tabla, [nombre.replace("ix_price_cache_", "")])
