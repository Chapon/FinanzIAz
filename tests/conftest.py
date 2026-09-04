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

import os
import sys
import tempfile

# La suite NO escribe en el log de producción (tarea 78). Va **antes** de
# cualquier import del proyecto: el primer ``get_logger`` que corra instala el
# ``RotatingFileHandler`` sobre ``~/.finanzias/finanzias.log`` y a partir de ahí
# cada traceback de un test queda ahí como si fuera un defecto de la app —
# medido, **551 líneas por corrida**. ``setdefault`` a propósito: se puede
# exportar la variable con una ruta para depurar una corrida puntual.
os.environ.setdefault("FINANZIAS_LOG_FILE", "")

# Los fetch de tooltip no corren en la suite (tarea 82). No es sólo por el crash
# de salida: el runnable pide **red** —bloqueada acá— y toca la **DB** desde un
# hilo del pool mientras los tests la rebindean a memoria; con eso la suite entera
# se murió a los ~35 tests. Es el mismo aislamiento que ya se hace con la red, la
# DB y el log, y va acá por el mismo motivo: antes de cualquier import.
os.environ.setdefault("FINANZIAS_DISABLE_TICKER_FETCH", "1")

# La suite tampoco toca la ``finanzias.db`` de producción **desde un subproceso**
# (tarea 108). Va acá, con las otras dos, por la misma razón y con la misma forma:
# ``database.models`` fija ``DB_PATH`` **al importarse**, así que después es tarde.
#
# ``_guard_real_db`` (más abajo) rebindea ``ENGINE`` a una in-memory, pero rebindea
# **en este proceso**: un test que abre un subproceso —el escenario de la 82— importa
# los módulos de la app sin conftest y se queda con la ruta de producción. Medido: en
# un checkout limpio **crea** ``finanzias.db``, vacía, en la raíz del repo, y eso tuvo
# el job ``pytest`` del CI **rojo 12 corridas** (tarea 107). El entorno es lo único que
# un subproceso hereda solo, así que es acá donde el aislamiento deja de depender de
# que cada test futuro se acuerde.
#
# El pid en el nombre aísla dos corridas simultáneas de la suite entre sí; el archivo
# lo borra ``_borrar_la_db_de_la_suite`` al final de la sesión.
os.environ.setdefault(
    "FINANZIAS_DB_PATH",
    os.path.join(tempfile.gettempdir(), f"finanzias_suite_{os.getpid()}.db"),
)

import contextlib
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


@pytest.fixture(scope="session", autouse=True)
def _borrar_la_db_de_la_suite():
    """Se lleva el archivo que la suite haya dejado en ``FINANZIAS_DB_PATH`` (108).

    Normalmente **no existe**: `_guard_real_db` rebindea todo a memoria y nada lo
    escribe. Aparece cuando un **subproceso** de la suite conecta —que es el caso
    entero de esta tarea—, y entonces queda un archivo por corrida en el temp del
    sistema. Se borra acá y no en el propio test porque el que lo crea es un proceso
    hijo que ya terminó.

    Sólo borra si la ruta es la que puso el conftest: exportar ``FINANZIAS_DB_PATH``
    a mano para depurar una corrida **no** puede terminar en un archivo borrado.
    """
    yield
    ruta = os.environ.get("FINANZIAS_DB_PATH", "")
    if f"finanzias_suite_{os.getpid()}.db" not in ruta:
        return
    for sufijo in ("", "-wal", "-shm"):
        with contextlib.suppress(OSError):
            Path(ruta + sufijo).unlink(missing_ok=True)


@pytest.fixture(scope="session", autouse=True)
def _cortar_fetches_de_tooltip():
    """Red de contención al final de la sesión (tarea 82).

    Con ``FINANZIAS_DISABLE_TICKER_FETCH`` puesto arriba, ningún runnable de
    tooltip llega a trabajar, así que **normalmente esto no tiene nada que
    hacer**. Existe para el test que apaga esa variable a propósito: si dejara un
    fetch en vuelo, el destructor del ``QThreadPool`` global lo despierta con el
    intérprete ya bajando, emite sobre un ``QObject`` a medio destruir y el
    proceso muere con **exit 127 después de que todos los tests pasaron** — el
    peor síntoma posible, porque no señala a nada.

    Se mira ``sys.modules`` en vez de importar: la mayoría de los tests no toca
    Qt y no hay por qué cargarlo.
    """
    yield
    mod = sys.modules.get("ui.ticker_tooltip")
    if mod is not None:
        mod.shutdown()


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

    **Alcance real, que hasta la 108 este docstring no decía.** Esto aísla **este
    proceso**: lo que hace es monkeypatchear ``ENGINE``/``SessionLocal``, así que
    protege al código que corre acá adentro y **nada más**. Un test que abre un
    **subproceso** importa ``database.models`` sin pasar por el conftest, se queda con
    la ruta de producción y toca la DB real — pasaba con el escenario de la 82, que
    en un checkout limpio dejaba una ``finanzias.db`` vacía en la raíz del repo. Esa
    mitad la cubre ``FINANZIAS_DB_PATH``, seteada arriba de todo, porque el entorno es
    lo único que un hijo hereda solo. Las dos hacen falta: sin el rebind, cada test
    compartiría un archivo; sin la variable, cada subproceso se escapa.

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
    - Opt-out explícito: ``@pytest.mark.real_db`` (registrado en pyproject) — saltea
      **el rebind**, no el aislamiento: desde la 108 el test cae en la DB de archivo
      de la sesión (``FINANZIAS_DB_PATH``), no en producción. Hoy **no lo usa nadie**.
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
