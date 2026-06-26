"""Valida la red de seguridad autouse que aísla la ``finanzias.db`` real (B4).

El 2026-06-25 ``test_historical_batch`` escribió frames sintéticos en la DB de
producción (no usaba ``test_db``) y rompió AAPL/MSFT 1y en la pestaña Análisis.
El fixture autouse ``_guard_real_db`` (en ``conftest.py``) previene toda la
clase de bug rebindeando ``ENGINE`` a una SQLite in-memory. Estos tests fallan
si ese guard se rompe o se elimina.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from data import yahoo_finance as yf_mod
from database.models import session_scope


def test_engine_is_isolated_in_memory():
    """Sin ``test_db`` ni ``@real_db``, ``ENGINE`` apunta a una in-memory."""
    from database import models as db_models

    assert db_models.ENGINE.url.database == ":memory:", (
        f"ENGINE no aislado por el guard: {db_models.ENGINE.url}"
    )


def test_cache_write_lands_in_isolated_db():
    """Un write por la ruta real de cache cae en la in-memory del test, no en
    producción — exactamente lo que faltaba el 2026-06-25."""
    df = pd.DataFrame(
        {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1_000_000]},
        index=pd.to_datetime(["2026-01-01"]),
    )
    yf_mod._write_historical_cache("ZZZZGUARD", "1y", "1d", df)

    with session_scope() as s:
        n = s.execute(
            text("SELECT COUNT(*) FROM historical_data_cache WHERE ticker = :t"),
            {"t": "ZZZZGUARD"},
        ).scalar()
    assert n == 1  # quedó en la DB aislada; la suite no toca finanzias.db
