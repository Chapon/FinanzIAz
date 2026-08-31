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

import pandas as pd
import pytest

from data import failed_tickers as ft
from data import yahoo_finance as yfm
from data.failed_tickers import get_failing_set


class _RaisingFastInfo:
    """Objeto tipo ``fast_info`` cuyo ``last_price`` lanza como un símbolo muerto."""

    def __init__(self, exc: Exception):
        self._exc = exc

    @property
    def last_price(self):
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
    mock_yfinance.Ticker.return_value.fast_info = _RaisingFastInfo(KeyError("exchangeTimezoneName"))

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


# --- Circuit-breaker de throttle (bug B3) ------------------------------------


def test_record_miss_failing_when_breaker_closed(test_db):
    """Sin throttle: un fallo se registra como permanente (entra al failing set)."""
    yfm.reset_throttle()
    yfm._record_miss("DEAD", "sin datos", "price")
    assert "DEAD" in get_failing_set()


def test_record_miss_transient_when_breaker_open(test_db):
    """Con throttle: el fallo es transitorio → NO entra al failing set, se reintenta."""
    yfm._note_throttle()
    assert yfm._is_throttled()
    yfm._record_miss("JPM", "lote vacío", "historical")
    assert "JPM" not in get_failing_set()  # large-cap real no queda excluido
    # Pero sí queda registrado como transitorio para visibilidad en la UI.
    statuses = {r.ticker: r.status for r in ft.get_all()}
    assert statuses.get("JPM") == ft.STATUS_TRANSIENT


def test_run_with_timeout_fail_fast_when_throttled(test_db):
    """Breaker abierto → la llamada NO toca la red, retorna default de inmediato."""
    yfm._note_throttle()
    called = {"n": 0}

    def _fn():
        called["n"] += 1
        return "ran"

    out = yfm._run_with_timeout(_fn, default="fallback")
    assert out == "fallback"
    assert called["n"] == 0  # no se ejecutó: fail-fast


def test_record_transient_preserves_failing_unless_override(test_db):
    """Un transitorio no degrada un veredicto permanente, salvo override explícito."""
    ft.record_failure("K", "deslistado", "historical")
    assert "K" in get_failing_set()
    # Sin override: se preserva el failing.
    ft.record_transient("K", "lote vacío", "historical")
    assert "K" in get_failing_set()
    # Con override (wholesale confirmado): se degrada a transitorio.
    ft.record_transient("K", "bulk vacío", "price", override=True)
    assert "K" not in get_failing_set()


# --- Batch warm-up: resiliencia y B2 -----------------------------------------


def test_batch_wholesale_empty_marks_transient_not_failing(test_db, mock_yfinance):
    """B3: si TODO el lote vuelve vacío, los tickers reales NO se envenenan."""
    yfm.reset_throttle()
    mock_yfinance.download.return_value = pd.DataFrame()  # lote entero vacío → throttle

    out = yfm.get_historical_data_batch(["JPM", "KLAC", "LOW"], period="2y")

    assert out["JPM"] is None and out["KLAC"] is None and out["LOW"] is None
    failing = get_failing_set()
    assert not ({"JPM", "KLAC", "LOW"} & failing)  # ninguno excluido del universo
    assert yfm._is_throttled()  # breaker abierto para frenar la cascada


def test_batch_skips_known_failing_ticker(test_db, mock_yfinance):
    """B2: un símbolo ya marcado failing no se re-consulta en el warm-up batch."""
    yfm.reset_throttle()
    ft.record_failure("K", "deslistado confirmado", "historical")
    mock_yfinance.download.return_value = pd.DataFrame()

    out = yfm.get_historical_data_batch(["K", "AAPL"], period="2y")

    assert out["K"] is None  # skip directo, sin red
    # yf.download se llamó solo para AAPL (K no entró al query).
    assert mock_yfinance.download.called
    queried = mock_yfinance.download.call_args[0][0]
    assert "K" not in queried.split()
    assert "AAPL" in queried.split()


# ── get_company_info: cache-first (V2) ─────────────────────────────────────────
def test_company_info_cache_first_skips_fetch(test_db, monkeypatch):
    """Con una fila vigente en company_info_cache, no se hace el scrape lento."""
    yfm._write_company_info_cache(
        "MU", {"name": "Micron", "sector": "Technology", "industry": "Semiconductors"}
    )

    def _boom(*a, **k):
        raise AssertionError("no debería fetchear cuando hay cache")

    monkeypatch.setattr(yfm, "_run_with_timeout", _boom)
    info = yfm.get_company_info("MU")
    assert info["sector"] == "Technology"
    assert info["name"] == "Micron"


def test_company_info_fetch_writes_cache(test_db, monkeypatch):
    """Un miss fetchea y persiste; la 2ª llamada sale del cache sin re-fetchear."""
    monkeypatch.setattr(
        yfm,
        "_run_with_timeout",
        lambda fn, **k: {"name": "Apple", "sector": "Technology", "industry": "Consumer Electronics"},
    )
    info = yfm.get_company_info("AAPL")
    assert info["sector"] == "Technology"

    def _boom(*a, **k):
        raise AssertionError("2ª llamada debería salir del cache")

    monkeypatch.setattr(yfm, "_run_with_timeout", _boom)
    info2 = yfm.get_company_info("AAPL")
    assert info2["sector"] == "Technology" and info2["name"] == "Apple"


def test_company_info_fetch_failure_returns_fallback_no_cache(test_db, monkeypatch):
    """Si el scrape falla (None), devuelve fallback y NO cachea el negativo."""
    monkeypatch.setattr(yfm, "_run_with_timeout", lambda fn, **k: None)
    info = yfm.get_company_info("ZZZ")
    assert info == {"name": "ZZZ", "sector": "N/A"}
    assert yfm._read_company_info_cache("ZZZ") is None
