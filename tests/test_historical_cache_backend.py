"""Dispatch del cache OHLCV por backend en ``data.yahoo_finance`` (backlog ARQ1).

Verifica el cableo detrás de las firmas existentes (``_read_historical_cache`` /
``_write_historical_cache`` / ``reference_close``) para los tres backends y la
**paridad end-to-end** sqlite vs parquet (mismo df → mismos datos). No toca red;
la DB es la in-memory del guard autouse del conftest.
"""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from data import parquet_cache as pc
from data import yahoo_finance as yfm


@pytest.fixture(autouse=True)
def _tmp_parquet_dir(tmp_path):
    pc.set_parquet_dir(tmp_path)
    yield tmp_path
    pc.set_parquet_dir(None)


def _frame(closes: list[tuple[str, float]]) -> pd.DataFrame:
    idx = pd.to_datetime([d for d, _ in closes])
    vals = [c for _, c in closes]
    return pd.DataFrame(
        {
            "Open": vals,
            "High": [c * 1.01 for c in vals],
            "Low": [c * 0.99 for c in vals],
            "Close": vals,
            "Volume": [2_000_000.0 + i for i in range(len(vals))],
        },
        index=idx,
    )


def _set_backend(monkeypatch, backend: str) -> None:
    monkeypatch.setattr(yfm, "_historical_cache_backend", lambda: backend)


# ── Flag / default ───────────────────────────────────────────────────────────


def test_default_backend_is_sqlite():
    from config.settings_manager import settings

    assert settings.get("historical_cache_backend") == "sqlite"


def test_setting_flows_to_dispatch():
    from config.settings_manager import settings

    assert settings.set("historical_cache_backend", "parquet") is True
    assert yfm._historical_cache_backend() == "parquet"
    assert settings.set("historical_cache_backend", "bogus") is False  # choices


# ── Round-trip por backend ───────────────────────────────────────────────────


@pytest.mark.parametrize("backend", ["sqlite", "parquet", "dual"])
def test_roundtrip_each_backend(monkeypatch, backend):
    _set_backend(monkeypatch, backend)
    df = _frame([("2024-01-02", 100.0), ("2024-01-03", 101.5)])
    yfm._write_historical_cache("AAPL", "1y", "1d", df)
    got = yfm._read_historical_cache("AAPL", "1y", "1d")
    assert got is not None
    assert float(got["Close"].iloc[-1]) == 101.5


def test_parity_sqlite_vs_parquet_end_to_end(monkeypatch):
    """Mismo df por ambos backends → los DataFrames leídos son equivalentes."""
    df = _frame([("2023-06-01", 250.0), ("2023-06-02", 248.75), ("2023-06-05", 252.10)])

    _set_backend(monkeypatch, "sqlite")
    yfm._write_historical_cache("MSFT", "6mo", "1d", df)
    from_sqlite = yfm._read_historical_cache("MSFT", "6mo", "1d")

    _set_backend(monkeypatch, "parquet")
    yfm._write_historical_cache("MSFT", "6mo", "1d", df)
    from_parquet = yfm._read_historical_cache("MSFT", "6mo", "1d")

    assert from_sqlite is not None and from_parquet is not None
    assert_frame_equal(from_parquet, from_sqlite, check_dtype=False, check_names=False, check_freq=False)


# ── reference_close por backend ──────────────────────────────────────────────


def test_reference_close_parquet_backend(monkeypatch):
    _set_backend(monkeypatch, "parquet")
    df = _frame([("2024-06-03", 190.0), ("2024-06-04", 194.25)])
    yfm._write_historical_cache("AAPL", "6mo", "1d", df)
    assert yfm.reference_close("AAPL") == pytest.approx(194.25)


# ── dual: escribe ambos, lee parquet primero, cae a sqlite ───────────────────


def test_dual_writes_both_stores(monkeypatch):
    from database.models import HistoricalDataCache, session_scope

    _set_backend(monkeypatch, "dual")
    yfm._write_historical_cache("NVDA", "1y", "1d", _frame([("2024-01-02", 500.0)]))

    # Parquet existe...
    assert pc.path_for("NVDA", "1y", "1d").exists()
    # ...y SQLite también.
    with session_scope() as s:
        n = s.query(HistoricalDataCache).filter(HistoricalDataCache.ticker == "NVDA").count()
    assert n == 1


def test_dual_falls_back_to_sqlite_for_unmigrated(monkeypatch):
    """Clave escrita solo en SQLite: en 'dual' se sirve por fallback (migración)."""
    _set_backend(monkeypatch, "sqlite")
    yfm._write_historical_cache("TSLA", "1y", "1d", _frame([("2024-01-02", 240.0)]))
    assert not pc.path_for("TSLA", "1y", "1d").exists()  # no hay parquet aún

    _set_backend(monkeypatch, "dual")
    got = yfm._read_historical_cache("TSLA", "1y", "1d")
    assert got is not None
    assert float(got["Close"].iloc[-1]) == 240.0
