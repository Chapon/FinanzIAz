"""Tests para ``data.yahoo_finance.get_analyst_data`` y helpers asociados.

Cubre:
- ``_bucket_recommendations`` con DataFrame con columna ``period`` (formato moderno yfinance)
- ``_bucket_recommendations`` sin columna ``period`` (fallback por índice)
- ``_normalize_price_targets`` con dict completo, dict parcial, None
- ``get_analyst_data`` end-to-end con yfinance mockeado
- Cache hit en llamadas sucesivas
"""

from __future__ import annotations

import pandas as pd

from data.yahoo_finance import (
    _analyst_cache,
    _bucket_recommendations,
    _normalize_price_targets,
    get_analyst_data,
)


def test_bucket_recommendations_modern_format():
    df = pd.DataFrame(
        {
            "period": ["0m", "-1m", "-2m", "-3m"],
            "strongBuy": [12, 11, 10, 9],
            "buy": [18, 19, 20, 21],
            "hold": [7, 7, 6, 5],
            "sell": [1, 2, 2, 2],
            "strongSell": [0, 0, 1, 1],
        }
    )
    out = _bucket_recommendations(df)
    assert len(out) == 4
    # Debe estar ordenado cronológicamente: -3m primero, 0m último
    assert out[0]["period"] == "-3m"
    assert out[-1]["period"] == "0m"
    # Totales
    assert out[-1]["total"] == 12 + 18 + 7 + 1 + 0
    assert out[0]["total"] == 9 + 21 + 5 + 2 + 1


def test_bucket_recommendations_no_period_column():
    """Versiones viejas de yfinance no traen ``period`` — fallback debe ordenar
    asumiendo índice 0=0m, 1=-1m, etc."""
    df = pd.DataFrame(
        {
            "strongBuy": [5, 4, 3, 2],
            "buy": [10, 10, 10, 10],
            "hold": [3, 3, 3, 3],
            "sell": [1, 1, 1, 1],
            "strongSell": [0, 0, 0, 0],
        }
    )
    out = _bucket_recommendations(df)
    assert len(out) == 4
    # period strings should be "0m", "-1m", "-2m", "-3m" mapped by index
    periods = [b["period"] for b in out]
    assert set(periods) == {"0m", "-1m", "-2m", "-3m"}


def test_bucket_recommendations_empty():
    assert _bucket_recommendations(None) == []
    assert _bucket_recommendations(pd.DataFrame()) == []


def test_bucket_recommendations_skips_zero_total_rows():
    df = pd.DataFrame(
        {
            "period": ["0m", "-1m"],
            "strongBuy": [0, 5],
            "buy": [0, 3],
            "hold": [0, 2],
            "sell": [0, 0],
            "strongSell": [0, 0],
        }
    )
    out = _bucket_recommendations(df)
    # Solo el mes -1m debe quedar — el 0m tiene total 0
    assert len(out) == 1
    assert out[0]["period"] == "-1m"


def test_normalize_price_targets_full():
    raw = {"current": 100.0, "mean": 120.0, "median": 115.0, "low": 80.0, "high": 150.0}
    out = _normalize_price_targets(raw)
    assert out is not None
    assert out["mean"] == 120.0
    assert out["current"] == 100.0


def test_normalize_price_targets_partial():
    """Si falta current pero hay mean/high, devuelve dict con None en current."""
    raw = {"mean": 120.0, "high": 150.0}
    out = _normalize_price_targets(raw)
    assert out is not None
    assert out["current"] is None
    assert out["mean"] == 120.0
    assert out["low"] is None


def test_normalize_price_targets_useless():
    """Si no hay mean/median/high, devolver None."""
    assert _normalize_price_targets({}) is None
    assert _normalize_price_targets({"current": 100.0}) is None
    assert _normalize_price_targets(None) is None
    assert _normalize_price_targets("not a dict") is None


def test_get_analyst_data_end_to_end(mock_yfinance, monkeypatch):
    """Smoke test: yfinance devuelve datos válidos, get_analyst_data los normaliza."""
    # Limpiar cache para que el test sea determinista
    _analyst_cache.clear()

    # Bypass del rate limiter / timeout pool — corremos directo en el thread del test.
    monkeypatch.setattr(
        "data.yahoo_finance._run_with_timeout",
        lambda fn, *a, timeout=None, default=None, **kw: fn(),
    )
    # Aislar de la finanzias.db real: sin esto, get_analyst_data lee el cache
    # de DB (AAPL fresco) y nunca usa el mock → el test dependía del estado de
    # la DB. Forzamos miss de lectura y no-op de escritura.
    monkeypatch.setattr("data.yahoo_finance._analyst_cache_read_db", lambda t: None)
    monkeypatch.setattr("data.yahoo_finance._analyst_cache_write_db", lambda t, p: None)

    fake_ticker = mock_yfinance.Ticker.return_value
    fake_ticker.recommendations = pd.DataFrame(
        {
            "period": ["0m", "-1m", "-2m", "-3m"],
            "strongBuy": [12, 11, 10, 9],
            "buy": [18, 19, 20, 21],
            "hold": [7, 7, 6, 5],
            "sell": [1, 2, 2, 2],
            "strongSell": [0, 0, 1, 1],
        }
    )
    fake_ticker.analyst_price_targets = {
        "current": 192.5,
        "mean": 215.4,
        "median": 220.0,
        "low": 165.0,
        "high": 280.0,
    }

    out = get_analyst_data("AAPL")
    assert len(out["recommendations"]) == 4
    assert out["recommendations"][-1]["period"] == "0m"
    assert out["recommendations"][-1]["total"] == 38
    assert out["price_targets"]["mean"] == 215.4


def test_get_analyst_data_handles_yfinance_failure(mock_yfinance, monkeypatch):
    """Si yfinance tira excepción, get_analyst_data devuelve estructura vacía sin tirar."""
    _analyst_cache.clear()
    monkeypatch.setattr(
        "data.yahoo_finance._run_with_timeout",
        lambda fn, *a, timeout=None, default=None, **kw: fn(),
    )

    # Hacer que el acceso al atributo `recommendations` tire excepción
    fake_ticker = mock_yfinance.Ticker.return_value
    type(fake_ticker).recommendations = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("Yahoo se cayó"))
    )
    fake_ticker.analyst_price_targets = None

    out = get_analyst_data("BROKEN")
    # No excepción + estructura limpia
    assert out == {"recommendations": [], "price_targets": None}


def test_get_analyst_data_cache_hit(mock_yfinance, monkeypatch):
    """Segunda llamada al mismo ticker debe servir desde cache sin re-fetch."""
    _analyst_cache.clear()
    monkeypatch.setattr(
        "data.yahoo_finance._run_with_timeout",
        lambda fn, *a, timeout=None, default=None, **kw: fn(),
    )

    fake_ticker = mock_yfinance.Ticker.return_value
    fake_ticker.recommendations = pd.DataFrame(
        {"period": ["0m"], "strongBuy": [5], "buy": [3], "hold": [2], "sell": [0], "strongSell": [0]}
    )
    fake_ticker.analyst_price_targets = None

    out1 = get_analyst_data("MSFT")
    call_count_after_first = mock_yfinance.Ticker.call_count
    out2 = get_analyst_data("MSFT")
    # No debería haber re-invocado yf.Ticker
    assert mock_yfinance.Ticker.call_count == call_count_after_first
    assert out1 == out2


# ── Persistencia a DB (sobrevive a reinicios) ─────────────────────────────────


def test_get_analyst_data_persists_to_db(test_db, mock_yfinance, monkeypatch):
    """Tras un fetch, debe quedar una fila en AnalystDataCache con el JSON."""
    import json

    from database.models import AnalystDataCache, session_scope

    _analyst_cache.clear()
    monkeypatch.setattr(
        "data.yahoo_finance._run_with_timeout",
        lambda fn, *a, timeout=None, default=None, **kw: fn(),
    )

    fake_ticker = mock_yfinance.Ticker.return_value
    fake_ticker.recommendations = pd.DataFrame(
        {"period": ["0m"], "strongBuy": [10], "buy": [5], "hold": [2], "sell": [0], "strongSell": [0]}
    )
    fake_ticker.analyst_price_targets = {
        "current": 100.0,
        "mean": 120.0,
        "median": 115.0,
        "low": 80.0,
        "high": 150.0,
    }

    out = get_analyst_data("AAPL")

    with session_scope() as s:
        rows = s.query(AnalystDataCache).filter(AnalystDataCache.ticker == "AAPL").all()
        assert len(rows) == 1
        payload = json.loads(rows[0].data_json)
        assert payload == out
        assert payload["price_targets"]["mean"] == 120.0


def test_get_analyst_data_db_survives_restart(test_db, mock_yfinance, monkeypatch):
    """Si la DB tiene una entrada fresca y el cache RAM está vacío (reinicio),
    debe usarla sin pegarle a yfinance."""
    _analyst_cache.clear()
    monkeypatch.setattr(
        "data.yahoo_finance._run_with_timeout",
        lambda fn, *a, timeout=None, default=None, **kw: fn(),
    )

    fake_ticker = mock_yfinance.Ticker.return_value
    fake_ticker.recommendations = pd.DataFrame(
        {"period": ["0m"], "strongBuy": [10], "buy": [5], "hold": [2], "sell": [0], "strongSell": [0]}
    )
    fake_ticker.analyst_price_targets = None

    # Primer fetch: pega a yfinance + persiste
    out1 = get_analyst_data("NVDA")
    calls_after_first = mock_yfinance.Ticker.call_count

    # Simular reinicio: limpiar cache RAM (la DB persiste — test_db es in-memory
    # SQLite pero vive todo el test)
    _analyst_cache.clear()

    out2 = get_analyst_data("NVDA")
    # No re-pegó a yfinance — vino de DB
    assert mock_yfinance.Ticker.call_count == calls_after_first
    assert out1 == out2


def test_get_analyst_data_db_expired_triggers_refetch(test_db, mock_yfinance, monkeypatch):
    """Si la fila de DB está más vieja que el TTL, se debe re-fetchear."""
    from datetime import datetime, timedelta

    from database.models import AnalystDataCache, session_scope

    _analyst_cache.clear()
    monkeypatch.setattr(
        "data.yahoo_finance._run_with_timeout",
        lambda fn, *a, timeout=None, default=None, **kw: fn(),
    )

    # Insertar manualmente una fila vencida (48h vieja).
    # Usamos datetime naive (sin tz) para matchear el formato que usa
    # ``utcnow_naive()`` en el modelo — comparar tz-aware vs naive tira error.
    from datetime import timezone

    stale = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)
    with session_scope() as s:
        s.add(
            AnalystDataCache(
                ticker="GOOGL",
                data_json='{"recommendations": [], "price_targets": null}',
                fetched_at=stale,
            )
        )

    fake_ticker = mock_yfinance.Ticker.return_value
    fake_ticker.recommendations = pd.DataFrame(
        {"period": ["0m"], "strongBuy": [99], "buy": [0], "hold": [0], "sell": [0], "strongSell": [0]}
    )
    fake_ticker.analyst_price_targets = None

    out = get_analyst_data("GOOGL")
    # Debe traer data fresca (strongBuy=99), no la vieja vacía
    assert out["recommendations"][-1]["strongBuy"] == 99
    # Y la DB ahora debe tener la fila nueva (reemplazó la vieja)
    with session_scope() as s:
        rows = s.query(AnalystDataCache).filter(AnalystDataCache.ticker == "GOOGL").all()
        assert len(rows) == 1  # vieja reemplazada, no acumulada


def test_get_analyst_data_persists_empty_results_too(test_db, mock_yfinance, monkeypatch):
    """Tickers que Yahoo no cubre también se cachean (resultado vacío) — evita
    re-fetcharlos en cada apertura de la app."""
    from database.models import AnalystDataCache, session_scope

    _analyst_cache.clear()
    monkeypatch.setattr(
        "data.yahoo_finance._run_with_timeout",
        lambda fn, *a, timeout=None, default=None, **kw: fn(),
    )

    fake_ticker = mock_yfinance.Ticker.return_value
    fake_ticker.recommendations = pd.DataFrame()  # vacío
    fake_ticker.analyst_price_targets = None

    out = get_analyst_data("UNKNOWNTICKER")
    assert out == {"recommendations": [], "price_targets": None}

    with session_scope() as s:
        rows = s.query(AnalystDataCache).filter(AnalystDataCache.ticker == "UNKNOWNTICKER").all()
        assert len(rows) == 1  # negativa cacheada
