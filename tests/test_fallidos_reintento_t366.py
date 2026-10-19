"""Tarea 366: los tickers fallidos se reintentan pasada una semana y se podan pasado un mes.

Pedido de Chapa (2026-10-19): *«la limpieza de los tickers fallidos una vez que dejan de
fallar»*. Un ``failing`` sale de los fetches (``get_failing_set``), así que nunca se vuelve a
pedir y ``record_success`` nunca corre: EMBJ, de la cartera real, quedó afuera del 10/10 al
19/10 por un solo "Sin precio" a las 02:25 mientras Yahoo lo cotizaba normal.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from data import failed_tickers as ft
from database.models import FailedTicker, session_scope, utcnow_naive

AHORA = datetime(2026, 10, 19, 15, 0)


def _fila(ticker, status=ft.STATUS_FAILING, op="price", hace_dias=0.0):
    with session_scope() as s:
        s.add(
            FailedTicker(
                ticker=ticker,
                last_error="x",
                last_operation=op,
                fail_count=1,
                status=status,
                first_failed_at=AHORA - timedelta(days=hace_dias),
                last_failed_at=AHORA - timedelta(days=hace_dias),
            )
        )


def _tickers():
    return {r.ticker for r in ft.get_all()}


@pytest.fixture
def db(test_db, monkeypatch):
    monkeypatch.setattr(ft, "_ahora", lambda: AHORA)
    return test_db


# ── El reintento ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "dias, se_saltea", [(0, True), (ft.REINTENTO_DIAS - 1, True), (ft.REINTENTO_DIAS + 1, False)]
)
def test_un_failing_se_reintenta_pasada_la_espera(db, dias, se_saltea):
    _fila("EMBJ", hace_dias=dias)
    assert ("EMBJ" in ft.get_failing_set()) is se_saltea


def test_EMBJ_tal_cual_nueve_días_después_de_un_solo_sin_precio(db):
    _fila("EMBJ", op="price", hace_dias=9.5)
    assert "EMBJ" not in ft.get_failing_set()


def test_ignored_se_saltea_siempre(db):
    _fila("LKT", status=ft.STATUS_IGNORED, hace_dias=365)
    assert "LKT" in ft.get_failing_set() and "LKT" in ft.get_failing_set(para="historico")


def test_la_serie_congelada_sólo_la_reintenta_el_histórico(db):
    """El precio de un ticker deslistado es el último que tuvo (tarea 369): no prueba nada."""
    _fila("WBD", op=ft.OP_SERIE_CONGELADA, hace_dias=ft.REINTENTO_DIAS + 3)
    assert "WBD" in ft.get_failing_set()
    assert "WBD" not in ft.get_failing_set(para="historico")


def test_reintentado_que_anda_se_borra_y_que_falla_vuelve_a_esperar(db, monkeypatch):
    _fila("OK", hace_dias=10)
    _fila("MAL", hace_dias=10)
    assert {"OK", "MAL"}.isdisjoint(ft.get_failing_set())
    ft.record_success("OK", operation="price")
    monkeypatch.setattr(ft, "_ahora", utcnow_naive)  # record_failure sella con el reloj real
    ft.record_failure("MAL", "Sin precio", operation="price")
    assert "OK" not in _tickers()
    assert "MAL" in ft.get_failing_set()


# ── La poda ──────────────────────────────────────────────────────────────────


def test_la_poda_borra_lo_viejo_y_no_toca_ignored_ni_lo_reciente(db):
    _fila("K", op="historical", hace_dias=110)
    _fila("BRK_B", op="historical", hace_dias=ft.PODA_DIAS + 1)
    _fila("TRANS", status=ft.STATUS_TRANSIENT, hace_dias=40)
    _fila("ACENTURE", op="analyst", hace_dias=ft.PODA_DIAS - 1)
    _fila("LKT", status=ft.STATUS_IGNORED, hace_dias=365)
    assert ft.podar() == 3
    assert _tickers() == {"ACENTURE", "LKT"}


def test_la_poda_sin_nada_viejo_no_borra_nada(db):
    _fila("MARAMLTX", op="analyst", hace_dias=0)
    assert ft.podar() == 0 and _tickers() == {"MARAMLTX"}
