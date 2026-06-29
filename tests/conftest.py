"""
Shared pytest fixtures.

Key concerns
------------
1. The app's database engine is module-level (``database.models.ENGINE``)
   and points at ``finanzias.db`` next to the source tree. Tests must NOT
   touch that file. The ``test_db`` fixture rebinds ``ENGINE`` and
   ``SessionLocal`` to an in-memory SQLite for the duration of each test.
2. yfinance must never be called in unit tests — it's slow, network-bound,
   and rate-limited. Use the ``mock_yfinance`` fixture (or build your own
   ``MagicMock``) when a unit under test reaches into ``data.yahoo_finance``.
3. Synthetic OHLCV data: ``ohlcv_factory`` creates a deterministic random-
   walk DataFrame so tests are reproducible.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

# Make ``import database.models`` etc. work when pytest is invoked from the
# repo root via ``pytest`` (no editable install needed).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def test_db(monkeypatch) -> Iterator:
    """
    Swap the global SQLAlchemy engine for an in-memory SQLite so tests are
    isolated and fast. All tables from both ``database.models`` and
    ``paper_trading.models`` are created fresh.

    Usage:
        def test_something(test_db):
            with session_scope() as s:
                ...
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Importing this module registers the paper-trading tables on Base.metadata
    import paper_trading.models  # noqa: F401
    from database import models as db_models

    test_engine = create_engine("sqlite:///:memory:", echo=False)
    test_sessionmaker = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(db_models, "ENGINE", test_engine)
    monkeypatch.setattr(db_models, "SessionLocal", test_sessionmaker)

    db_models.Base.metadata.create_all(test_engine)
    yield test_engine
    db_models.Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def mock_yfinance(monkeypatch):
    """
    Block any accidental real network call. Returns the patched MagicMock
    so individual tests can configure return values.

        def test_x(mock_yfinance):
            mock_yfinance.Ticker.return_value.fast_info.last_price = 150.0
    """
    fake = MagicMock(name="yfinance")
    monkeypatch.setattr("data.yahoo_finance.yf", fake)
    return fake


@pytest.fixture
def ohlcv_factory():
    """
    Deterministic OHLCV DataFrame generator for indicator / backtest tests.

    Returns a callable: ``df = factory(rows=300, start_price=100, seed=42)``.
    Output has Open / High / Low / Close / Volume columns and a daily
    DatetimeIndex ending today.
    """

    def _make(
        rows: int = 300,
        start_price: float = 100.0,
        seed: int = 42,
        drift: float = 0.0005,
        vol: float = 0.015,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        rets = rng.normal(drift, vol, rows)
        close = start_price * np.exp(np.cumsum(rets))
        # Synthesise plausible OHLC around close
        high = close * (1 + np.abs(rng.normal(0, vol / 3, rows)))
        low = close * (1 - np.abs(rng.normal(0, vol / 3, rows)))
        open_ = np.r_[close[0], close[:-1]]
        volume = rng.integers(1_000_000, 10_000_000, rows).astype(float)
        idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=rows, freq="B")
        return pd.DataFrame(
            {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
            index=idx,
        )

    return _make


@pytest.fixture(autouse=True)
def _guard_real_db(request, monkeypatch):
    """Red de seguridad (bug B4): ningún test debe tocar la ``finanzias.db`` real.

    Rebindea ``database.models.ENGINE``/``SessionLocal`` a una SQLite in-memory
    por test (con todas las tablas creadas), de modo que cualquier writer de
    cache (``get_historical_data_batch`` → ``_finalize_historical`` →
    ``_write_historical_cache``, además de ``PriceCache``/``EarningsCache``…)
    escriba en la DB temporal y **nunca** en producción. El 2026-06-25
    ``test_historical_batch`` corrompió AAPL/MSFT 1y por no aislar la DB.

    Detalles:
    - ``StaticPool`` + ``check_same_thread=False`` comparten la conexión
      in-memory entre threads — los fetch de yfinance escriben cache desde el
      ``ThreadPoolExecutor`` de ``_run_with_timeout``, en otro thread.
    - Opt-out explícito: ``@pytest.mark.real_db`` (registrado en pyproject).
    - Si el test ya pide el fixture ``test_db``, ese aísla por su cuenta; no se
      duplica el rebind.
    """
    if request.node.get_closest_marker("real_db") or "test_db" in request.fixturenames:
        yield
        return

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import paper_trading.models  # noqa: F401 — registra las tablas en Base.metadata
    from database import models as db_models

    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_sessionmaker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(db_models, "ENGINE", engine)
    monkeypatch.setattr(db_models, "SessionLocal", test_sessionmaker)

    db_models.Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _reset_throttle_breaker():
    """Cierra el circuit-breaker de throttle (B3) antes y después de cada test.

    ``data.yahoo_finance`` guarda el estado del breaker a nivel de módulo
    (global al proceso). Un test que dispare un throttle (timeout/lote vacío)
    dejaría el breaker abierto y los fetch de los tests siguientes fallarían
    rápido (fail-fast). Lo reseteamos para que cada test arranque limpio.
    """
    from data import yahoo_finance as _yfm

    _yfm.reset_throttle()
    yield
    _yfm.reset_throttle()


@pytest.fixture(autouse=True)
def _disable_settings_persistence(tmp_path, monkeypatch):
    """
    Redirect ``settings.json`` to a per-test tmp directory so test runs don't
    pollute the user's real ``~/.finanzias/`` and so each test starts with
    pristine defaults.

    Also reload the module-level ``settings`` singleton against the patched
    path. Without the reload, the singleton has already loaded the user's
    real config at import time, leaking host state into tests that read
    ``settings.get(…)`` indirectly (e.g. ``analyze()`` reads ``sma_cross``).
    """
    monkeypatch.setattr(
        "config.settings_manager._CONFIG_PATH",
        tmp_path / "settings.json",
    )
    # Force the live singleton to re-read against the patched path.
    from config.settings_manager import settings as _live_settings

    _live_settings.load()
