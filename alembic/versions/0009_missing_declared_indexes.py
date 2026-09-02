"""Reconcilia los índices declarados en los models con los que existen (tarea 74).

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-02

De los **41** índices declarados entre ``database/models.py`` y
``paper_trading/models.py``, la DB viva tenía **17**: faltaban **24, en 11
tablas**. No es un olvido puntual, es un mecanismo:

    ``Base.metadata.create_all(checkfirst=True)`` **saltea entera** una tabla
    que ya existe — índices incluidos.

Así que **todo índice agregado a un model DESPUÉS de que su tabla existiera
nunca se creó**, y ninguna migración lo cubrió. La confirmación cruzada que
cierra el mecanismo: las tablas nuevas (``earnings_cache``, ``news_events``,
…) sí tienen todos los suyos, porque ahí ``create_all`` las creó de cero con
sus índices. El compuesto ``ix_price_cache_ticker_fetched`` entró a los models
el 2026-05-06, después de que la tabla existiera: **nunca se creó**.

Lo caro no era la lentitud sino que **el código miente**: quien lee el model
cree que el índice existe, y un test que mire el ORM se lo confirma. El
consumidor medido: ``get_current_price`` hacía ``SCAN price_cache`` +
``USE TEMP B-TREE FOR ORDER BY`` sobre 400.453 filas — **38,7 ms por ticker**.

**Por qué lista los 41 y no los 24 que faltaban.** Enumerar el conjunto
declarado **completo** (no el delta del día) es lo que vuelve chequeable el
invariante: ``tests/test_schema_indexes_t74.py`` borra todos los índices
declarados de una DB con las tablas puestas, corre ``upgrade head`` y exige
que no falte ninguno. Con un delta, ese test no podría distinguir *"la
migración lo crea"* de *"``create_all`` lo dejó ahí"*. Consecuencia deseada:
**un índice nuevo en un model sin revisión nueva pone el test en rojo**.

**Idempotente por diseño**: chequea con el inspector antes de cada ``CREATE
INDEX``, así que una DB nueva (que ``create_all`` ya construyó completa) pasa
por acá sin ejecutar DDL, y correrla dos veces es seguro.

Las definiciones están **CONGELADAS** (lista explícita, no se importa
``Base.metadata``), igual que en la 0004: si los models agregan un índice
mañana, eso es una revisión **nueva**, no un cambio retroactivo de ésta.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (nombre, tabla, columnas, unique) — el conjunto declarado al 2026-09-02.
# Los 24 que faltaban en la DB viva van marcados con «# faltaba».
_INDEXES: tuple[tuple[str, str, list[str], bool], ...] = (
    ("ix_analyst_cache_ticker_fetched", "analyst_data_cache", ["ticker", "fetched_at"], False),
    ("ix_analyst_data_cache_fetched_at", "analyst_data_cache", ["fetched_at"], False),
    ("ix_analyst_data_cache_ticker", "analyst_data_cache", ["ticker"], False),
    ("ix_analyst_estimate_snapshots_snapshot_date", "analyst_estimate_snapshots", ["snapshot_date"], False),
    ("ix_analyst_estimate_snapshots_ticker", "analyst_estimate_snapshots", ["ticker"], False),
    ("ix_est_ticker_metric_date", "analyst_estimate_snapshots", ["ticker", "metric", "snapshot_date"], False),
    ("ix_company_info_cache_fetched_at", "company_info_cache", ["fetched_at"], False),
    ("ix_company_info_cache_ticker", "company_info_cache", ["ticker"], True),
    ("ix_dividend_cache_ticker", "dividend_cache", ["ticker"], False),  # faltaba
    ("ix_dividend_cache_ticker_since", "dividend_cache", ["ticker", "since_date"], False),  # faltaba
    ("ix_earnings_cache_fetched_at", "earnings_cache", ["fetched_at"], False),
    ("ix_earnings_cache_ticker", "earnings_cache", ["ticker"], False),
    ("ix_earnings_cache_ticker_fetched", "earnings_cache", ["ticker", "fetched_at"], False),
    ("ix_failed_tickers_status", "failed_tickers", ["status"], False),  # faltaba
    ("ix_failed_tickers_ticker", "failed_tickers", ["ticker"], True),
    ("ix_hist_cache_key", "historical_data_cache", ["ticker", "period", "interval"], False),  # faltaba
    ("ix_news_content_hash", "news_events", ["content_hash"], True),
    ("ix_news_events_fetched_at", "news_events", ["fetched_at"], False),
    ("ix_news_events_ticker", "news_events", ["ticker"], False),
    ("ix_news_ticker_published", "news_events", ["ticker", "published_at"], False),
    ("ix_news_unclassified", "news_events", ["event_type"], False),
    ("ix_price_cache_fetched_at", "price_cache", ["fetched_at"], False),  # faltaba
    ("ix_price_cache_ticker", "price_cache", ["ticker"], False),  # faltaba
    ("ix_price_cache_ticker_fetched", "price_cache", ["ticker", "fetched_at"], False),  # faltaba
    ("ix_alerts_active_portfolio", "alerts", ["is_active", "portfolio_id"], False),  # faltaba
    ("ix_alerts_is_active", "alerts", ["is_active"], False),  # faltaba
    ("ix_alerts_portfolio_id", "alerts", ["portfolio_id"], False),  # faltaba
    ("ix_alerts_ticker", "alerts", ["ticker"], False),  # faltaba
    ("ix_alerts_ticker_active", "alerts", ["ticker", "is_active"], False),  # faltaba
    ("ix_paper_equity_account_at", "paper_equity_snapshots", ["account_id", "snapshot_at"], False),  # faltaba
    ("ix_paper_orders_account_filled", "paper_orders", ["account_id", "filled_at"], False),  # faltaba
    ("ix_paper_orders_account_status", "paper_orders", ["account_id", "status"], False),  # faltaba
    ("ix_paper_orders_ticker_filled", "paper_orders", ["ticker", "filled_at"], False),  # faltaba
    ("ix_paper_positions_account", "paper_positions", ["account_id"], False),  # faltaba
    ("ix_paper_watchlist_account", "paper_watchlist", ["account_id"], False),  # faltaba
    ("ix_positions_portfolio_id", "positions", ["portfolio_id"], False),  # faltaba
    ("ix_positions_portfolio_ticker", "positions", ["portfolio_id", "ticker"], False),  # faltaba
    ("ix_positions_ticker", "positions", ["ticker"], False),  # faltaba
    ("ix_transactions_date", "transactions", ["date"], False),  # faltaba
    ("ix_transactions_position_date", "transactions", ["position_id", "date"], False),  # faltaba
    ("ix_transactions_position_id", "transactions", ["position_id"], False),  # faltaba
)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for name, table, cols, unique in _INDEXES:
        if table not in tables:
            # La tabla no existe en esta DB (estado parcial): no es tarea de
            # esta revisión crearla — la crea create_all o su propia migración.
            continue
        if any(i["name"] == name for i in insp.get_indexes(table)):
            continue
        op.create_index(name, table, cols, unique=unique)


def downgrade() -> None:
    """No-op **a propósito**, y no por comodidad: hay dos razones y una es dura.

    (1) Esta revisión **reconcilia**, no crea en exclusiva: de los 41 índices que
    enumera, en cualquier DB dada la mayoría ya existía —los puso ``create_all``
    o la revisión que creó su tabla—. Borrarlos al bajar sacaría objetos que
    esta revisión no creó.

    (2) Y rompe el camino de bajada de las otras: ``0006.downgrade`` hace
    ``drop_index("ix_company_info_cache_ticker")`` sin guard, así que si 0009 ya
    lo borró, la bajada muere con *"no such index"*. Está probado —
    ``test_downgrade_0004_removes_delta`` falla con la versión simétrica.

    El costo de no bajar es cero: un índice de más es performance, no datos, y
    esta revisión no mueve ni una fila.
    """

