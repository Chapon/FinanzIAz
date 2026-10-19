"""Tarea 369: un ticker que Yahoo dejó de cotizar se detecta por su serie, no por su precio.

WBD (vendido el 2026-10-05) no daba error: el histórico traía sólo la barra del 05/10, que
pisó el ``2y`` de dos años, y ``fast_info`` seguía devolviendo 30,95, que contaba como éxito y
lo dejaba fuera de ``failed_tickers``. Medido el 2026-10-19 sobre los 127 del universo vivo: 126
con 0 ruedas de atraso y WBD con 10. La vara es la de ``parquet_cache``: más de 5 ruedas.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import pytest

from data import failed_tickers as ft
from data import yahoo_finance as yf
from data.parquet_cache import FRAME_MAX_ATRASO_RUEDAS

# Un lunes: las ruedas de atraso no dependen del día en que corra la suite.
AHORA = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)


def _frame(fin: str, filas: int = 30) -> pd.DataFrame:
    idx = pd.bdate_range(end=fin, periods=filas)
    v = [100.0 + i for i in range(filas)]
    return pd.DataFrame({"Open": v, "High": v, "Low": v, "Close": v, "Volume": [1e6] * filas}, index=idx)


def _hace(ruedas: int) -> str:
    return str((pd.Timestamp(AHORA.date()) - pd.offsets.BDay(ruedas)).date())


@pytest.fixture
def aislado(test_db, monkeypatch):
    escritos: dict = {}
    monkeypatch.setattr(yf, "_write_historical_cache", lambda t, p, i, df: escritos.setdefault((t, p), df))
    monkeypatch.setattr(yf, "last_bar_is_provisional", lambda *_a, **_k: False)
    monkeypatch.setattr(yf, "_CONGELADA_AVISADO", set())
    return escritos


def _fila(ticker):
    return next((r for r in ft.get_all() if r.ticker == ticker), None)


# ── El borde ─────────────────────────────────────────────────────────────────


def test_WBD_tal_cual_una_barra_del_5_de_octubre_es_serie_congelada(aislado):
    wbd = _frame("2026-10-05", filas=1)
    assert yf._serie_congelada("WBD", wbd, "2y", "1d", ahora=AHORA)
    fila = _fila("WBD")
    assert fila.status == ft.STATUS_FAILING and fila.last_operation == ft.OP_SERIE_CONGELADA
    assert "2026-10-05" in fila.last_error and "10 ruedas" in fila.last_error


@pytest.mark.parametrize(
    "ruedas, congelada", [(0, False), (1, False), (FRAME_MAX_ATRASO_RUEDAS, False), (6, True)]
)
def test_el_umbral_es_el_de_los_frames_atrasados(aislado, ruedas, congelada):
    """Un feriado suma una rueda: con 5 de margen no dispara."""
    assert yf._serie_congelada("AAA", _frame(_hace(ruedas)), "2y", "1d", ahora=AHORA) is congelada
    assert (_fila("AAA") is not None) is congelada


def test_sólo_aplica_a_las_series_diarias(aislado):
    assert not yf._serie_congelada("AAA", _frame(_hace(30)), "5y", "1wk", ahora=AHORA)


# ── No pisa el cache y avisa una vez ─────────────────────────────────────────


def test_la_serie_congelada_no_se_cachea_y_la_al_día_sí(aislado, monkeypatch):
    real = yf._serie_congelada
    monkeypatch.setattr(yf, "_serie_congelada", lambda t, df, p, i: real(t, df, p, i, ahora=AHORA))
    assert yf._finalize_historical("WBD", _frame("2026-10-05", filas=1), "2y", "1d") is None
    assert yf._finalize_historical("AVB", _frame(_hace(0)), "2y", "1d") is not None
    assert list(aislado) == [("AVB", "2y")]


def test_avisa_una_vez_por_ticker(aislado, caplog):
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            yf._serie_congelada("WBD", _frame("2026-10-05", filas=1), "2y", "1d", ahora=AHORA)
    avisos = [r.getMessage() for r in caplog.records if "tarea 369" in r.getMessage()]
    assert len(avisos) == 1 and avisos[0].startswith("WBD:")
    assert _fila("WBD").fail_count == 3


# ── El precio congelado no lo revive ─────────────────────────────────────────


def test_un_exito_de_PRECIO_no_borra_la_serie_congelada(aislado):
    yf._serie_congelada("WBD", _frame("2026-10-05", filas=1), "2y", "1d", ahora=AHORA)
    ft.record_success("WBD", operation="price")
    ft.record_success("WBD", operation="validate")
    assert _fila("WBD") is not None
    assert "WBD" in ft.get_failing_set()


def test_un_histórico_que_vuelve_a_avanzar_sí_la_borra(aislado):
    yf._serie_congelada("WBD", _frame("2026-10-05", filas=1), "2y", "1d", ahora=AHORA)
    ft.record_success("WBD", operation="historical")
    assert _fila("WBD") is None


def test_un_fallo_COMÚN_lo_sigue_borrando_un_precio(aislado):
    """Lo de antes no cambia: un ticker que falló por otra cosa y vuelve a dar precio, sale."""
    ft.record_failure("XYZ", "Sin precio (símbolo posiblemente deslistado)", operation="price")
    ft.record_success("XYZ", operation="price")
    assert _fila("XYZ") is None


def test_los_caminos_reales_pasan_su_operación(aislado, monkeypatch):
    """``_fetch_ticker_info`` y ``validate_ticker`` cuentan como precio, no como histórico."""
    llamadas = []
    monkeypatch.setattr(yf, "record_success", lambda t, operation=None: llamadas.append((t, operation)))
    monkeypatch.setattr(yf, "_note_fetch_success", lambda: None)

    class _FI:
        last_price = 30.95
        previous_close = 30.95

        def __getitem__(self, k):
            return getattr(self, k, None)

        def get(self, k, d=None):
            return getattr(self, k, d)

    class _T:
        fast_info = _FI()

    monkeypatch.setattr(yf, "_ticker", lambda s: _T())
    assert yf._fetch_ticker_info("WBD") is not None
    assert llamadas == [("WBD", "price")]
