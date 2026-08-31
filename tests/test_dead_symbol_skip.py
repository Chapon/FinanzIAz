"""UNIV1 (c): un símbolo que Yahoo declara inexistente no se re-consulta.

Antes: cada ticker muerto del universo costaba ~2 requests 404 por run (uno por
módulo de quoteSummary) y ~2 líneas ERROR en el log, en cada scan de Leads.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data import yf_noise
from data.yahoo_finance import _analyst_cache, get_analyst_data


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Aísla caches y la DB real; corre el fetch en el thread del test."""
    _analyst_cache.clear()
    yf_noise.reset_unknown_symbols()
    monkeypatch.setattr(
        "data.yahoo_finance._run_with_timeout",
        lambda fn, *a, timeout=None, default=None, **kw: fn(),
    )
    monkeypatch.setattr("data.yahoo_finance._analyst_cache_read_db", lambda t: None)
    monkeypatch.setattr("data.yahoo_finance._analyst_cache_write_db", lambda t, p: None)
    yield
    _analyst_cache.clear()
    yf_noise.reset_unknown_symbols()


def test_second_request_is_skipped_for_unknown_symbol(mock_yfinance, monkeypatch):
    """Si el primer módulo revela 'Quote not found', no se pide el segundo."""
    calls = {"recommendations": 0, "price_targets": 0}

    fake = mock_yfinance.Ticker.return_value

    def _recommendations(self):
        calls["recommendations"] += 1
        # yfinance NO tira: loguea el 404 y devuelve vacío. Reproducimos eso
        # emitiendo por su logger, que es donde vive el filtro.
        yf_noise.note_unknown_symbol("ANSS")
        return pd.DataFrame()

    def _price_targets(self):
        calls["price_targets"] += 1
        return {"mean": 100.0}

    type(fake).recommendations = property(_recommendations)
    type(fake).analyst_price_targets = property(_price_targets)
    monkeypatch.setattr("data.yahoo_finance._record_miss", lambda *a, **kw: None)

    out = get_analyst_data("ANSS")

    assert calls["recommendations"] == 1
    assert calls["price_targets"] == 0, "no debe gastarse un segundo request en un símbolo muerto"
    assert out["price_targets"] is None


def test_healthy_symbol_still_makes_both_requests(mock_yfinance):
    """Un ticker sano no pierde el segundo request por culpa del guard."""
    calls = {"price_targets": 0}
    fake = mock_yfinance.Ticker.return_value

    def _price_targets(self):
        calls["price_targets"] += 1
        return {"mean": 215.4, "median": 220.0, "low": 165.0, "high": 280.0}

    type(fake).recommendations = property(lambda self: pd.DataFrame())
    type(fake).analyst_price_targets = property(_price_targets)

    out = get_analyst_data("AAPL")

    assert calls["price_targets"] == 1
    assert out["price_targets"]["mean"] == 215.4


def test_unknown_symbol_is_recorded_as_miss(mock_yfinance, monkeypatch):
    """El símbolo muerto entra al registro de fallidos (vía _record_miss / B3)."""
    recorded = []
    fake = mock_yfinance.Ticker.return_value

    def _recommendations(self):
        yf_noise.note_unknown_symbol("JNPR")
        return pd.DataFrame()

    type(fake).recommendations = property(_recommendations)
    type(fake).analyst_price_targets = property(lambda self: {})
    monkeypatch.setattr(
        "data.yahoo_finance._record_miss",
        lambda ticker, error, operation: recorded.append((ticker, operation)),
    )

    get_analyst_data("JNPR")

    assert recorded == [("JNPR", "analyst")]


def test_healthy_symbol_is_not_recorded(mock_yfinance, monkeypatch):
    """Sin 'Quote not found' no se registra nada — FOX/LOW no deben caer acá."""
    recorded = []
    fake = mock_yfinance.Ticker.return_value
    type(fake).recommendations = property(lambda self: pd.DataFrame())
    type(fake).analyst_price_targets = property(lambda self: {})
    monkeypatch.setattr(
        "data.yahoo_finance._record_miss",
        lambda ticker, error, operation: recorded.append((ticker, operation)),
    )

    get_analyst_data("LOW")

    assert recorded == []


def test_leads_worker_skips_failing_tickers(monkeypatch):
    """El scan de Leads no consulta lo que ya está en el failing set."""
    from ui.leads import worker as leads_worker

    queried = []

    monkeypatch.setattr(
        leads_worker,
        "filter_skippable",
        lambda tickers: ([t for t in tickers if t != "ANSS"], ["ANSS"]),
    )

    def _fake_analyst(ticker):
        queried.append(ticker)
        return {"recommendations": [], "price_targets": None}

    monkeypatch.setattr(leads_worker, "get_analyst_data", _fake_analyst)
    monkeypatch.setattr(leads_worker, "compute_lead_score", lambda analyst, ticker: None)

    w = leads_worker.LeadsScanWorker(["AAPL", "ANSS", "MSFT"])
    w.do_work()

    assert "ANSS" not in queried
    assert sorted(queried) == ["AAPL", "MSFT"]
