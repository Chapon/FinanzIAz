"""Test de la migración one-shot JSON-en-SQLite → Parquet (backlog ARQ1).

Crea una SQLite temporal con la tabla ``historical_data_cache``, corre
``migrate`` hacia un directorio parquet aislado y verifica escritura, round-trip,
preservación de ``fetched_at`` (semántica de TTL) y manejo de filas corruptas.
No toca la DB viva ni la red.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from data import parquet_cache as pc
from scripts.migrate_historical_cache_to_parquet import migrate

_CREATE = """
CREATE TABLE historical_data_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker VARCHAR(20) NOT NULL,
  period VARCHAR(10) NOT NULL,
  interval VARCHAR(10) NOT NULL,
  data_json TEXT NOT NULL,
  fetched_at DATETIME
)
"""


def _df(closes):
    idx = pd.to_datetime([d for d, _ in closes])
    vals = [c for _, c in closes]
    return pd.DataFrame(
        {"Open": vals, "High": vals, "Low": vals, "Close": vals, "Volume": [1_000_000.0] * len(vals)},
        index=idx,
    )


@pytest.fixture
def seeded_db(tmp_path):
    db = tmp_path / "finanzias.db"
    con = sqlite3.connect(str(db))
    con.execute(_CREATE)
    rows = [
        (
            "AAPL",
            "1y",
            "1d",
            _df([("2024-01-02", 100.0), ("2024-01-03", 101.0)]).to_json(orient="split", date_format="iso"),
            "2026-07-11 12:00:00",
        ),
        # fila vieja → debe quedar stale con TTL corto tras migrar
        (
            "MSFT",
            "6mo",
            "1d",
            _df([("2023-06-01", 250.0)]).to_json(orient="split", date_format="iso"),
            "2020-01-01 00:00:00",
        ),
        # fila corrupta → cuenta como fallida, no rompe
        ("BADX", "1y", "1d", "{not valid json", "2026-07-11 12:00:00"),
    ]
    con.executemany(
        "INSERT INTO historical_data_cache (ticker, period, interval, data_json, fetched_at) "
        "VALUES (?,?,?,?,?)",
        rows,
    )
    con.commit()
    con.close()
    return db


@pytest.fixture(autouse=True)
def _tmp_parquet_dir(tmp_path):
    d = tmp_path / "parquet_out"
    pc.set_parquet_dir(d)
    yield d
    pc.set_parquet_dir(None)


def test_dry_run_writes_nothing(seeded_db):
    stats = migrate(seeded_db, apply=False)
    assert stats["rows"] == 3
    assert stats["written"] == 2  # AAPL + MSFT (BADX falla)
    assert stats["failed"] == 1
    assert not pc.path_for("AAPL", "1y", "1d").exists()


def test_apply_migrates_and_preserves_fetched_at(seeded_db):
    stats = migrate(seeded_db, apply=True)
    assert stats["written"] == 2 and stats["failed"] == 1

    # AAPL migrado y legible.
    aapl = pc.read("AAPL", "1y", "1d", ttl_hours=None)
    assert aapl is not None
    assert float(aapl["Close"].iloc[-1]) == 101.0

    # MSFT tenía fetched_at de 2020 → con TTL corto queda stale (fetched_at preservado),
    # pero con TTL desactivado se lee igual.
    assert pc.read("MSFT", "6mo", "1d", ttl_hours=1) is None
    assert pc.read("MSFT", "6mo", "1d", ttl_hours=None) is not None


def test_idempotent(seeded_db):
    migrate(seeded_db, apply=True)
    stats2 = migrate(seeded_db, apply=True)  # re-run
    assert stats2["written"] == 2
    aapl = pc.read("AAPL", "1y", "1d", ttl_hours=None)
    assert float(aapl["Close"].iloc[-1]) == 101.0
