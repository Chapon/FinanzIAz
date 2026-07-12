"""Tests del backend Parquet+DuckDB del cache OHLCV (backlog ARQ1).

Gate técnico duro de ARQ1: equivalencia con el backend viejo (JSON-en-SQLite) +
round-trip fiel + TTL + capa analítica DuckDB. No toca red ni la DB (regla 3/5).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from data import parquet_cache as pc


@pytest.fixture(autouse=True)
def _tmp_parquet_dir(tmp_path):
    """Redirige el cache parquet a un tmp aislado y lo resetea al terminar."""
    pc.set_parquet_dir(tmp_path)
    yield tmp_path
    pc.set_parquet_dir(None)


def _make_frame(closes: list[tuple[str, float]]) -> pd.DataFrame:
    idx = pd.to_datetime([d for d, _ in closes])
    vals = [c for _, c in closes]
    return pd.DataFrame(
        {
            "Open": vals,
            "High": [c * 1.01 for c in vals],
            "Low": [c * 0.99 for c in vals],
            "Close": vals,
            "Volume": [1_000_000.0 + i for i in range(len(vals))],
        },
        index=idx,
    )


def _json_roundtrip(df: pd.DataFrame) -> pd.DataFrame:
    """Reproduce exactamente cómo lee/escribe el backend viejo (JSON-en-SQLite)."""
    js = df.to_json(orient="split", date_format="iso")
    out = pd.read_json(StringIO(js), orient="split")
    out.index = pd.to_datetime(out.index)
    return out


# ── Round-trip + equivalencia con el backend viejo ───────────────────────────


def test_write_read_roundtrip_preserves_values():
    df = _make_frame([("2024-01-02", 100.0), ("2024-01-03", 101.5), ("2024-01-04", 99.25)])
    pc.write("AAPL", "1y", "1d", df)
    got = pc.read("AAPL", "1y", "1d", ttl_hours=1)
    assert got is not None
    assert_frame_equal(got, df, check_dtype=False, check_names=False, check_freq=False)


def test_equivalence_with_json_backend():
    """Mismo df → parquet devuelve los mismos datos que el round-trip JSON viejo."""
    df = _make_frame([("2023-06-01", 250.0), ("2023-06-02", 248.75), ("2023-06-05", 252.10)])
    pc.write("MSFT", "6mo", "1d", df)
    parquet_out = pc.read("MSFT", "6mo", "1d", ttl_hours=1)
    json_out = _json_roundtrip(df)
    assert parquet_out is not None
    assert_frame_equal(
        parquet_out, json_out, check_dtype=False, check_names=False, check_freq=False
    )


def test_keys_are_isolated():
    """Distintos (period/interval) no se pisan."""
    df_1y = _make_frame([("2024-01-02", 100.0)])
    df_6mo = _make_frame([("2024-06-03", 200.0)])
    pc.write("NVDA", "1y", "1d", df_1y)
    pc.write("NVDA", "6mo", "1d", df_6mo)
    assert float(pc.read("NVDA", "1y", "1d", 1)["Close"].iloc[0]) == 100.0
    assert float(pc.read("NVDA", "6mo", "1d", 1)["Close"].iloc[0]) == 200.0


# ── TTL / frescura ───────────────────────────────────────────────────────────


def test_read_respects_ttl_stale():
    df = _make_frame([("2024-01-02", 100.0)])
    stale = datetime.now(timezone.utc) - timedelta(hours=5)
    pc.write("AAPL", "1y", "1d", df, fetched_at=stale)
    assert pc.read("AAPL", "1y", "1d", ttl_hours=1) is None  # 5h > 1h TTL
    assert pc.read("AAPL", "1y", "1d", ttl_hours=None) is not None  # TTL off → hit
    assert pc.read("AAPL", "1y", "1d", ttl_hours=6) is not None  # dentro de 6h


def test_read_miss_when_absent():
    assert pc.read("TSLA", "1y", "1d", ttl_hours=1) is None


def test_write_ignores_empty_frame():
    pc.write("EMPTY", "1y", "1d", pd.DataFrame())
    assert not pc.path_for("EMPTY", "1y", "1d").exists()


# ── latest_1d (ancla de escala, ignora TTL) ──────────────────────────────────


def test_latest_1d_picks_freshest_across_periods():
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    new = datetime.now(timezone.utc) - timedelta(hours=1)
    pc.write("AAPL", "2y", "1d", _make_frame([("2024-01-02", 190.0)]), fetched_at=old)
    pc.write("AAPL", "6mo", "1d", _make_frame([("2024-06-03", 194.0)]), fetched_at=new)
    got = pc.latest_1d("AAPL")
    assert got is not None
    assert float(got["Close"].iloc[-1]) == 194.0  # el más fresco, sin importar TTL


def test_latest_1d_none_when_no_daily():
    pc.write("AAPL", "1y", "1h", _make_frame([("2024-01-02", 100.0)]))  # intradía, no 1d
    assert pc.latest_1d("AAPL") is None


# ── invalidate ───────────────────────────────────────────────────────────────


def test_invalidate_removes_all_ticker_files():
    pc.write("AAPL", "1y", "1d", _make_frame([("2024-01-02", 100.0)]))
    pc.write("AAPL", "6mo", "1d", _make_frame([("2024-06-03", 101.0)]))
    pc.write("MSFT", "1y", "1d", _make_frame([("2024-01-02", 400.0)]))
    pc.invalidate("AAPL")
    assert pc.read("AAPL", "1y", "1d", 1) is None
    assert pc.read("AAPL", "6mo", "1d", 1) is None
    assert pc.read("MSFT", "1y", "1d", 1) is not None  # otro ticker intacto


# ── Capa analítica DuckDB (window functions) ─────────────────────────────────


def test_duckdb_scan_window_function():
    df = _make_frame(
        [("2024-01-02", 100.0), ("2024-01-03", 110.0), ("2024-01-04", 99.0)]
    )
    pc.write("AAPL", "1y", "1d", df)
    out = pc.scan(
        'SELECT "Close" - LAG("Close") OVER (ORDER BY "Date") AS delta '
        "FROM read_parquet(?) ORDER BY \"Date\"",
        [pc.parquet_glob("1d")],
    )
    deltas = out["delta"].tolist()
    assert deltas[0] != deltas[0] or pd.isna(deltas[0])  # primer LAG = NULL/NaN
    assert deltas[1] == pytest.approx(10.0)
    assert deltas[2] == pytest.approx(-11.0)
