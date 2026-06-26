"""Tests de robustez del fetch de precios (data.yahoo_finance).

Cubre el bug B1: las properties lazy de ``fast_info`` (``last_price`` & co.)
pueden lanzar ``KeyError: 'exchangeTimezoneName'`` en símbolos con metadata
incompleta/deslistados. Antes esa excepción se filtraba por ``getattr(..., None)``
(que solo atrapa AttributeError) y terminaba en un traceback ruidoso con posible
cascada a hard-timeouts. Ahora degrada con gracia a "sin precio" → None.
"""

from __future__ import annotations

import logging
import types

import pytest

from data import yahoo_finance as yfm
from data.failed_tickers import get_failing_set


class _RaisingFastInfo:
    """Objeto tipo ``fast_info`` cuyo ``last_price`` lanza como un símbolo muerto."""

    def __init__(self, exc: Exception):
        self._exc = exc

    @property
    def last_price(self):  # noqa: D401 - mimics yfinance lazy property
        raise self._exc


# --- _safe_fast_info (unidad) ------------------------------------------------


def test_safe_fast_info_swallows_structural_error():
    """KeyError de metadata → tratado como dato ausente (default), sin propagar."""
    info = _RaisingFastInfo(KeyError("exchangeTimezoneName"))
    assert yfm._safe_fast_info(info, "last_price") is None
    assert yfm._safe_fast_info(info, "last_price", default=0.0) == 0.0


def test_safe_fast_info_reraises_transient():
    """Un 401/crumb NO es un símbolo muerto: se re-lanza para reintentar."""
    info = _RaisingFastInfo(RuntimeError("401 Unauthorized: Invalid Crumb"))
    with pytest.raises(RuntimeError):
        yfm._safe_fast_info(info, "last_price")


def test_safe_fast_info_missing_attr_returns_default():
    """Atributo inexistente (AttributeError) → default, igual que getattr."""
    info = types.SimpleNamespace()
    assert yfm._safe_fast_info(info, "year_high") is None
    assert yfm._safe_fast_info(info, "currency", default="USD") == "USD"


# --- _fetch_ticker_info (integración con el timeout/retry) -------------------


def test_fetch_ticker_info_handles_metadata_keyerror(test_db, mock_yfinance, caplog):
    """B1: símbolo con metadata sin exchangeTimezoneName → None, sin traceback."""
    mock_yfinance.Ticker.return_value.fast_info = _RaisingFastInfo(
        KeyError("exchangeTimezoneName")
    )

    with caplog.at_level(logging.ERROR, logger="data.yahoo_finance"):
        result = yfm._fetch_ticker_info("K")

    assert result is None
    # No se emitió un traceback ruidoso (log.exception → nivel ERROR).
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
    # El símbolo quedó registrado como fallido para que el bulk fetch lo saltee.
    assert "K" in get_failing_set()


def test_fetch_ticker_info_happy_path(test_db, mock_yfinance):
    """Camino feliz: fast_info válido → dict limpio con precio y change_pct."""
    mock_yfinance.Ticker.return_value.fast_info = types.SimpleNamespace(
        last_price=150.0,
        previous_close=148.0,
        three_month_average_volume=1_000_000,
        market_cap=2_000_000_000,
        year_high=160.0,
        year_low=120.0,
        currency="USD",
    )

    result = yfm._fetch_ticker_info("AAPL")
    assert result is not None
    assert result["ticker"] == "AAPL"
    assert result["price"] == 150.0
    assert result["market_cap"] == 2_000_000_000
    assert result["change_pct"] == pytest.approx(round(((150.0 - 148.0) / 148.0) * 100, 2))
    # El happy-path no deja al ticker en la lista de fallidos.
    assert "AAPL" not in get_failing_set()
