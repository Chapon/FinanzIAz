"""Tarea 234 — un cache que no se puede escribir no convierte un dato bueno en «no hay dato».

Del log de runtime (2026-09-23 y 2026-09-27/28, tres veces): ``Error fetching price for MARA``
con ``database is locked`` en ``INSERT INTO price_cache``. El precio **ya estaba bajado** —el
propio INSERT lo trae (12.55)— pero la escritura del cache vivía adentro del ``try`` de todo el
fetch, así que la excepción del INSERT caía al ``except`` general y la función devolvía
``None``. ``get_dividends_since`` tenía la misma forma y devolvía ``0.0``: «no pagó», que es
peor que «no sé».

El lock se simula donde ocurre de verdad: al **commitear** la escritura, después de que el fetch
ya trajo el dato.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import OperationalError

from data import yahoo_finance as yfm

_LOCKED = OperationalError(
    "INSERT INTO price_cache (...) VALUES (...)", {}, sqlite3.OperationalError("database is locked")
)


def _lock_en_escrituras_despues_del_fetch(monkeypatch, estado: dict) -> None:
    """``session_scope`` que levanta el lock al salir, sólo una vez que el fetch corrió."""
    real = yfm.session_scope

    @contextmanager
    def falso():
        with real() as s:
            yield s
            if estado["fetch_hecho"]:
                raise _LOCKED

    monkeypatch.setattr(yfm, "session_scope", falso)


def test_get_current_price_devuelve_el_precio_aunque_el_cache_este_bloqueado(monkeypatch, caplog):
    estado = {"fetch_hecho": False}

    def fetch(ticker, **_kw):
        estado["fetch_hecho"] = True
        return {"ticker": ticker.upper(), "price": 12.55, "change_pct": -3.01, "volume": 48_283_025.0}

    monkeypatch.setattr(yfm, "_fetch_ticker_info", fetch)
    _lock_en_escrituras_despues_del_fetch(monkeypatch, estado)

    with caplog.at_level(logging.WARNING, logger=yfm.log.name):
        out = yfm.get_current_price("MARA")

    assert out is not None, "el precio se bajó bien y se descartó por no poder escribir el cache"
    assert out["price"] == pytest.approx(12.55)
    assert out["from_cache"] is False
    textos = [r.getMessage() for r in caplog.records]
    assert not any("Error fetching" in t for t in textos), "el log sigue diciendo que falló el FETCH"
    avisos = [r for r in caplog.records if "price_cache write failed for MARA" in r.getMessage()]
    assert len(avisos) == 1 and avisos[0].levelno == logging.WARNING
    assert avisos[0].exc_info is None, "el aviso es una línea, no un traceback"
    assert "\n" not in avisos[0].getMessage(), "el SQL y los parámetros no van al aviso"


def test_get_dividends_since_devuelve_el_total_y_no_CERO(monkeypatch):
    """El caso peor de los dos: ``0.0`` se lee como «no pagó dividendos»."""
    estado = {"fetch_hecho": False}

    def fetch(ticker, since):
        estado["fetch_hecho"] = True
        return 1.11

    monkeypatch.setattr(yfm, "_fetch_dividends_since", fetch)
    _lock_en_escrituras_despues_del_fetch(monkeypatch, estado)

    total = yfm.get_dividends_since("MO", datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert total == pytest.approx(1.11)


def test_sin_lock_el_cache_se_sigue_escribiendo(monkeypatch):
    """La contraprueba: el arreglo no puede haber apagado el cache."""
    monkeypatch.setattr(
        yfm, "_fetch_ticker_info", lambda t, **_k: {"ticker": t.upper(), "price": 12.55, "change_pct": 0.0}
    )
    assert yfm.get_current_price("MARA")["from_cache"] is False
    segunda = yfm.get_current_price("MARA")
    assert segunda is not None and segunda["from_cache"] is True
