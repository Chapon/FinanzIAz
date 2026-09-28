"""Piezas para testear contra el write lock REAL de SQLite (tareas 237 y 238).

La regla que esto sostiene: **ningún fetch de red corre con una escritura pendiente en una
sesión abierta.** Los fetch (`get_current_price`, `get_bulk_prices`, earnings…) escriben su
cache por **otra** conexión; si su llamador ya hizo un `flush()`, esa escritura espera al propio
llamador hasta el `busy_timeout` y termina en `database is locked`. Pasó dos veces: el scan el
2026-07-13 y el chequeo de alertas desde la 227 (`docs/lock_arranque_t235_2026-09-28.md`).

**Por qué un archivo y no la in-memory de `test_db`:** el lock es entre conexiones sobre el
mismo archivo. En memoria no hay dos conexiones que compartan la base, y el defecto no existe.

Uso::

    def test_x(db_archivo, monkeypatch):
        fetch = FetchQueEscribeElCache(db_archivo, {"MARA": 12.5})
        monkeypatch.setattr("alerts.alert_manager.get_current_price", fetch)
        ...
        assert fetch.bloqueos == []

``db_archivo`` es un fixture, disponible en toda la suite porque ``tests/conftest.py`` carga
este módulo como plugin (``pytest_plugins``); no hace falta importarlo.
"""

from __future__ import annotations

import sqlite3
import time

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database import models as db_models
from database.models import utcnow_naive

# Corto a propósito: un rojo tarda 0,5 s y no los 30 del `busy_timeout` de producción.
TIMEOUT_S = 0.5


@pytest.fixture
def db_archivo(tmp_path, monkeypatch):
    """La DB de la app sobre un archivo, en WAL como la viva, con timeout corto."""
    import paper_trading.models  # noqa: F401  (registra las tablas de paper en Base)

    path = tmp_path / "lock_real.db"
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": TIMEOUT_S})

    @event.listens_for(engine, "connect")
    def _wal(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")

    monkeypatch.setattr(db_models, "ENGINE", engine)
    monkeypatch.setattr(
        db_models, "SessionLocal", sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )
    db_models.Base.metadata.create_all(engine)
    yield path
    engine.dispose()


class FetchQueEscribeElCache:
    """Como los fetch reales en lo que importa acá: devuelve el precio y escribe `price_cache`
    por una conexión propia. Registra cada `database is locked` y cuánto esperó.

    Sirve de las dos formas: como `get_current_price(ticker)` (llamándolo con un str) y como
    `prices_provider(tickers)` del engine (con ``.provider``, que devuelve ``{ticker: precio}``).
    ``al_pedir(con, ticker)`` corre adentro, antes del INSERT: para escribir algo desde afuera
    en medio del fetch.
    """

    def __init__(self, path, precios, al_pedir=None):
        self.path, self.precios, self.al_pedir = path, precios, al_pedir
        self.bloqueos: list[str] = []
        self.esperas: list[float] = []

    def _escribir(self, ticker):
        con = sqlite3.connect(self.path, timeout=TIMEOUT_S)
        t0 = time.perf_counter()
        try:
            if self.al_pedir:
                self.al_pedir(con, ticker)
            con.execute(
                "INSERT INTO price_cache (ticker, price, fetched_at) VALUES (?, ?, ?)",
                (ticker, self.precios[ticker], utcnow_naive().isoformat(" ")),
            )
            con.commit()
        except sqlite3.OperationalError as e:
            self.bloqueos.append(f"{ticker}: {e}")
        finally:
            self.esperas.append(time.perf_counter() - t0)
            con.close()

    def __call__(self, ticker):
        self._escribir(ticker)
        return {"price": self.precios[ticker]}

    def provider(self, tickers):
        for t in tickers:
            self._escribir(t)
        return {t: self.precios[t] for t in tickers if t in self.precios}
