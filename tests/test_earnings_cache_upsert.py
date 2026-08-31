"""Upsert in-place de earnings_cache tolerante al lock (OPS1(b)).

Reemplaza el delete+insert por un update de la fila más reciente (o insert),
acortando la ventana de lock que el harvest horario multiplica. El
``database is locked`` de SQLite se trata como transitorio (reintento con
backoff) y el fallo final es fail-open (warning, no exception).
"""

from __future__ import annotations

import logging
from datetime import datetime

from database.models import EarningsCache, session_scope


def _rows(ticker: str) -> list[tuple]:
    with session_scope() as s:
        return [
            (r.earnings_date, r.fetched_at)
            for r in s.query(EarningsCache).filter(EarningsCache.ticker == ticker).all()
        ]


def test_is_sqlite_locked_classifier():
    from data.yahoo_finance import _is_sqlite_locked

    assert _is_sqlite_locked(Exception("database is locked"))
    assert _is_sqlite_locked(Exception("(sqlite3.OperationalError) database is locked"))
    assert not _is_sqlite_locked(Exception("no such table: earnings_cache"))


def test_upsert_inserts_then_updates_in_place(test_db):
    """Dos writes del mismo ticker → UNA fila (update in-place), con el valor nuevo."""
    from data.yahoo_finance import _write_earnings_cache

    _write_earnings_cache("AAPL", datetime(2026, 8, 1))
    rows = _rows("AAPL")
    assert len(rows) == 1
    assert rows[0][0] == datetime(2026, 8, 1)

    _write_earnings_cache("AAPL", datetime(2026, 11, 1))
    rows = _rows("AAPL")
    assert len(rows) == 1  # sigue habiendo una sola fila (no delete+insert)
    assert rows[0][0] == datetime(2026, 11, 1)  # earnings_date actualizado


def test_upsert_caches_negative_result(test_db):
    """El resultado negativo (None = sin earnings próximo) también se cachea."""
    from data.yahoo_finance import _write_earnings_cache

    _write_earnings_cache("NONE", None)
    rows = _rows("NONE")
    assert len(rows) == 1 and rows[0][0] is None


def test_lock_is_retried_then_succeeds(test_db, monkeypatch):
    """Un lock transitorio en el primer intento se reintenta y recupera."""
    from data import yahoo_finance as yf

    real_scope = yf.session_scope
    calls = {"n": 0}

    def flaky_scope():
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("database is locked")  # primer intento: lock
        return real_scope()

    monkeypatch.setattr(yf, "session_scope", flaky_scope)
    monkeypatch.setattr(yf.time, "sleep", lambda *_a, **_k: None)  # sin backoff real

    yf._write_earnings_cache("MSFT", datetime(2026, 9, 1), attempts=3)

    # OJO: no usar monkeypatch.undo() acá — el fixture ``test_db`` comparte este
    # mismo monkeypatch y undo() revertiría el rebind de SessionLocal a la DB
    # real. ``_rows`` usa el ``session_scope`` importado directo (nunca
    # parcheado), así que lee la in-memory sin depender del patch de yf.
    rows = _rows("MSFT")
    assert len(rows) == 1 and rows[0][0] == datetime(2026, 9, 1)
    assert calls["n"] == 2  # falló una vez, recuperó a la segunda


def test_persistent_lock_is_swallowed_as_warning(test_db, monkeypatch, caplog):
    """Un lock que no cede: NO se propaga (fail-open) y se loguea warning."""
    from data import yahoo_finance as yf

    def always_locked():
        raise Exception("database is locked")

    monkeypatch.setattr(yf, "session_scope", always_locked)
    monkeypatch.setattr(yf.time, "sleep", lambda *_a, **_k: None)

    with caplog.at_level(logging.WARNING, logger="data.yahoo_finance"):
        yf._write_earnings_cache("TSLA", None, attempts=2)  # no debe levantar

    assert any("TSLA" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)
