"""Tarea 374 — un corte de red no manda tickers sanos a ``failing``, y una posición abierta nunca.

El 2026-10-20, al volver de la suspensión, no hubo DNS por ~3 s y 14 tickers sanos quedaron en
``failing`` con el breaker cerrado; AMGN, una posición abierta de la cuenta 2, entre ellos.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import pytest

from data import failed_tickers as ft
from data import yahoo_finance as yf

UNIVERSO = ["ABBV", "ABT", "ACN", "ADBE", "AEP", "AMD", "AMGN", "AMZN", "AVGO", "AXP"]


def _fila(ticker):
    return next((r for r in ft.get_all() if r.ticker == ticker), None)


@pytest.fixture
def con_amgn_abierta(test_db):
    from database.models import session_scope
    from paper_trading.models import PaperAccount, PaperPosition

    with session_scope() as s:
        c = PaperAccount(name="Sim Segundo", initial_capital=50_000.0, is_active=True)
        s.add(c)
        s.flush()
        s.add(PaperPosition(account_id=c.id, ticker="AMGN", shares=10.0, avg_cost=300.0))


def test_con_la_red_cortada_ninguno_termina_en_failing(con_amgn_abierta, monkeypatch):
    """El canario de verdad, contra el cortafuegos de la suite: la conexión a Yahoo no sale."""
    monkeypatch.setattr(yf, "_red_caida", yf._probar_red)
    yf.reset_canario()
    for t in UNIVERSO:
        yf._record_miss(t, "Sin precio (símbolo posiblemente deslistado)", "price")
    assert ft.get_failing_set() == set()
    assert {_fila(t).status for t in UNIVERSO} == {ft.STATUS_TRANSIENT}
    assert "sin red al registrarlo" in _fila("ABBV").last_error


def test_con_red_un_simbolo_inexistente_si_entra(test_db):
    yf._record_miss("NOEXISTE", "Quote not found", "price")
    assert ft.get_failing_set() == {"NOEXISTE"}


def test_una_posicion_abierta_no_entra_a_failing_ni_con_red(con_amgn_abierta):
    yf._record_miss("AMGN", "Sin precio (símbolo posiblemente deslistado)", "price")
    assert "AMGN" not in ft.get_failing_set()
    assert _fila("AMGN").status == ft.STATUS_TRANSIENT
    assert "posición abierta" in _fila("AMGN").last_error


def test_una_posicion_abierta_que_ya_estaba_en_failing_sale(con_amgn_abierta, monkeypatch):
    """Sin el override, ``record_transient`` no pisa un ``failing`` y AMGN seguiría salteado.

    Primero entra a ``failing`` como si no fuera posición abierta (el estado de antes de la
    tarea); después, con la protección, tiene que salir. **Sin ``monkeypatch.undo()``:** el
    ``monkeypatch`` es el mismo de los aislamientos del ``conftest``, y deshacerlo devolvería la
    DB real. Se usa un interruptor dentro del reemplazo.
    """
    real = ft._es_posicion_abierta
    proteger = {"activo": False}
    monkeypatch.setattr(ft, "_es_posicion_abierta", lambda s, sym: proteger["activo"] and real(s, sym))
    ft.record_failure("AMGN", "Sin precio", "price")
    assert "AMGN" in ft.get_failing_set()
    proteger["activo"] = True
    ft.record_failure("AMGN", "Sin precio", "price")
    assert "AMGN" not in ft.get_failing_set()


def test_la_rafaga_avisa_una_vez_y_cuenta_solo_los_que_entran(test_db, caplog):
    with caplog.at_level(logging.WARNING, logger="data.failed_tickers"):
        for _ in range(10):
            ft.record_failure("WBD", "serie congelada", "serie_congelada")  # ya estaba: no cuenta
        assert not [r for r in caplog.records if "entraron a failing" in r.getMessage()]
        for t in ["A1", "A2", "A3", "A4", "A5", "A6", "A7"]:
            ft.record_failure(t, "Quote not found", "price")
    avisos = [r for r in caplog.records if "entraron a failing" in r.getMessage()]
    assert len(avisos) == 1
    assert "5 tickers" in avisos[0].getMessage()


def test_la_asimetria_que_cura_el_fetch_por_ticker_no_mira_failing_y_lo_limpia(test_db, monkeypatch):
    """La estrategia pide la historia ticker por ticker con ``get_historical_data``, que no consulta
    el failing set y con un histórico bueno borra la fila. Si alguien la cambia, el daño de un
    corte pasa de un scan a 7 días: este test lo dice antes."""
    ft.record_failure("AMZN", "Sin precio", "price")
    assert "AMZN" in ft.get_failing_set()
    idx = pd.bdate_range(end=date.today(), periods=30)
    v = [100.0 + i for i in range(30)]
    frame = pd.DataFrame({"Open": v, "High": v, "Low": v, "Close": v, "Volume": [1e6] * 30}, index=idx)
    monkeypatch.setattr(yf, "_read_historical_cache", lambda *a: None)
    monkeypatch.setattr(yf, "_write_historical_cache", lambda *a: None)
    monkeypatch.setattr(yf, "last_bar_is_provisional", lambda *_a, **_k: False)
    monkeypatch.setattr(yf, "_run_with_timeout", lambda fn, **kw: frame)
    assert yf.get_historical_data("AMZN", period="2y") is not None
    assert "AMZN" not in ft.get_failing_set()
