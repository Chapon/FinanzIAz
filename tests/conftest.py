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
   Desde la tarea 209 esto **está impuesto**, no sólo recomendado: el autouse
   ``_cortafuegos_de_red`` (al final del archivo) corta todo socket saliente y
   todo request de ``curl_cffi`` en los tests sin ``@pytest.mark.network``.
   ``mock_yfinance`` sigue siendo opt-in y sólo cubre ``data.yahoo_finance.yf``:
   el cortafuegos no lo reemplaza, evita que su ausencia salga a internet.
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
# de salida: el runnable pide **red** y toca la **DB** desde un hilo del pool
# mientras los tests la rebindean a memoria; con eso la suite entera se murió a
# los ~35 tests. Es el mismo aislamiento que ya se hace con la DB y el log, y va
# acá por el mismo motivo: antes de cualquier import.
#
# **Corrección (tarea 207), ya saldada (tarea 209):** acá decía *«el runnable pide
# red —bloqueada acá—»* y *«el mismo aislamiento que ya se hace con la red»*, y
# cuando se escribió era **falso**: ninguno de los aislamientos de este bloque tocaba
# la red, y `mock_yfinance` es opt-in y sólo parchea `data.yahoo_finance.yf`. Esta
# variable sigue cortando *este* fetch concreto y nada más; el cortafuegos de red es
# ahora `_cortafuegos_de_red`, al final de este archivo, y va por fixture autouse y
# no por variable de entorno porque tiene que leer el marcador de cada test.
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

# La suite tampoco le manda mensajes al **Slack de producción** (tarea 148). Cuarto
# aislamiento de la misma familia y por la misma razón que los tres de arriba: el
# entorno es lo único que se hereda solo.
#
# El defecto no era teórico y está contado interceptando el POST: **9 mensajes por
# corrida** al canal de Chapa. Tres son alertas de precio de MARA a $13 —
# `test_alerts_worker_t80.py` llama a `AlertCheckWorker.do_work()`, que construye su
# `AlertManager` **sin notifier inyectado** (`ui/alerts_tab.py:75`)— y seis son de
# outage de datos por el mismo camino. Con `SLACK_BOT_TOKEN` y `SLACK_CHANNEL` en el
# entorno, `default_notifier` postea de verdad. Lo reportó Chapa, no la suite: los
# tests pasaban en verde, porque mandar un mensaje no es un fallo para nadie.
#
# Y el bloqueo va en el **límite de red** (`integrations.slack.post_to_slack`), no en
# los tres productores, porque un guard por productor es una lista y el próximo
# productor no va a estar en ella. Un test que necesite ejercitar el envío de verdad
# lo levanta con `monkeypatch.delenv` — se lee en cada llamada, no al importar.
os.environ.setdefault("FINANZIAS_DISABLE_SLACK", "1")

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


# Los cuatro memos por ticker de ``data.yahoo_finance``, con nombre y motivo.
# Todos son ``dict`` module-level y ninguno se borra solo: sobreviven de un test al
# siguiente, y los cuatro **cambian si se pega o no a la red**.
_MEMOS_POR_TICKER = (
    "_out_of_band_streak",  # n rechazos seguidos; a n>=_ESCALATE_AFTER habilita el fetch de splits
    "_split_factor_cache",  # lo contrario: un factor cacheado EVITA ese fetch
    "_second_opinion_cache",  # el memo de la segunda opinión (tarea 200)
    "_opinion_log",  # el veredicto que lee el guard del engine (tarea 201)
)


@pytest.fixture(autouse=True)
def _aislar_los_memos_de_yahoo():
    """Cada test arranca sin los memos por ticker de ``data.yahoo_finance`` (tarea 213).

    **El defecto, medido y no supuesto.** `test_price_sanity.py` rechaza el precio de
    KLAC en tres tests distintos; como la racha es module-level, el tercero
    —``test_get_current_price_rejects_out_of_band``— arranca con ``n = 3``, que es
    exactamente ``_ESCALATE_AFTER``, y entonces ``unreliable_reference`` **sale a buscar
    splits a Yahoo**. Corrido solo, el test no toca la red; corriendo el archivo entero,
    sí. O sea que su contacto con internet dependía del **orden de ejecución**, que es la
    clase de cosa que no se encuentra leyendo el archivo. Lo destapó la bitácora del
    cortafuegos de la **209**, no el exit code: el camino falla abierto y el test pasaba
    igual.

    **Por qué acá y no en cada archivo.** `test_split_guard_t63`, la **200** y la **201**
    ya se arman **cada uno su propia limpieza** de estos mismos dicts — o sea que el
    problema era conocido y la solución era una **lista de archivos que se acuerdan**.
    `test_price_sanity` es el que no estaba en la lista, y el próximo tampoco va a estar.
    Es el mismo argumento que el bloqueo de Slack (148), que va en el límite y no en los
    tres productores.

    Se mira ``sys.modules`` en vez de importar, como ``_cortar_fetches_de_tooltip``: la
    mayoría de los tests no toca yfinance y no hay por qué cargarlo. Limpia **antes** del
    test; lo que quede después lo puede seguir inspeccionando quien lo necesite (la 63
    afirma sobre el contenido de la racha al terminar, y sigue pudiendo).
    """
    mod = sys.modules.get("data.yahoo_finance")
    if mod is not None:
        for nombre in _MEMOS_POR_TICKER:
            getattr(mod, nombre, {}).clear()
    yield


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


# ── Cortafuegos de red (tarea 209) ───────────────────────────────────────────


class RedBloqueadaEnLaSuite(RuntimeError):
    """Un test sin el marcador ``network`` intentó salir a internet."""


# Bitácora de lo que el cortafuegos frenó **en el test en curso** (el fixture la vacía
# al empezar cada uno). No es telemetría: existe para que un test pueda afirmar que el
# corte **se disparó**, y no sólo que no llegaron datos. Sin esto, un test que verifica
# un bloqueo pasa igual con la máquina sin internet, o con una librería que se traga su
# propio error y devuelve vacío —que es justo lo que hace ``yfinance``—, o sea probando
# nada. Es la contraprueba del instrumento, no del sujeto.
INTENTOS_BLOQUEADOS: list[str] = []


# Loopback se deja pasar: lo que se quiere cortar son las llamadas a terceros, y un
# servidor local o un socketpair de Qt no es eso. Bloquearlo sería romper por deporte.
_HOSTS_LOCALES = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0"})


def _es_local(address) -> bool:
    host = address[0] if isinstance(address, (tuple, list)) and address else address
    return isinstance(host, str) and (host in _HOSTS_LOCALES or host.startswith("127."))


@pytest.fixture(autouse=True)
def _cortafuegos_de_red(request, monkeypatch):
    """Ningún test sin ``@pytest.mark.network`` sale a internet (tarea 209).

    **Por qué hizo falta, y por qué no estaba.** ``CLAUDE.md`` decía que este archivo
    bloqueaba la red y era **falso**: los cuatro aislamientos de arriba cubren el log, la
    DB, el fetch de tooltip y Slack, y ``mock_yfinance`` es **opt-in** y sólo parchea
    ``data.yahoo_finance.yf``. El 2026-09-15, al mover la costura de ``collect_all`` en la
    tarea 207, tres tests quedaron parcheando un nombre que ya nadie llamaba y
    ``_finnhub_news`` **salió a la API real de Finnhub** —hay key viva en esta máquina—
    devolviendo 257 artículos de verdad. Se notó **sólo** porque el contenido no coincidía
    con el fake; si hubiera coincidido, el test habría pasado por el motivo equivocado. Y
    en el CI, sin la key, el mismo test toma otra rama: verde de los dos lados por razones
    distintas, que es la familia de la 175 y la 176.

    **Hay que cortar en DOS lugares, y el segundo es el que importa.** Parchear ``socket``
    alcanza a ``requests``/``urllib3``/``http.client`` (Finnhub, EDGAR, RSS) y **no a
    ``curl_cffi``**, que va por libcurl sin pasar por el módulo ``socket`` de Python — y
    ``curl_cffi`` es exactamente lo que usa **yfinance 1.x**, o sea la mayor superficie de
    red del proyecto. Medido antes de escribir esto: con ``socket`` parcheado, ``requests``
    queda bloqueado y ``curl_cffi.get`` **sale igual**. Un cortafuegos sólo-socket habría
    sido la forma exacta del guard que es ciego al caso mayoritario. El corte de
    ``curl_cffi`` va en ``Curl.perform``, el nivel más bajo: verificado que alcanza a
    ``requests.get`` de módulo, a ``Session().get`` y a ``yf.Ticker(...).news``.

    **Lo que NO cubre, y va dicho:** igual que ``_guard_real_db``, esto aísla **este
    proceso**. Un test que abre un **subproceso** hereda el entorno pero no los parches,
    así que puede salir a la red. Hoy no hay ninguno que lo haga; si aparece, la mitad que
    falta se resuelve con una variable de entorno, como la 108 resolvió la de la DB.
    Tampoco corta el **DNS**: el corte va en ``connect``, y ``requests`` resuelve el
    nombre antes de llegar ahí, así que una consulta de DNS sí sale. Es a propósito —
    bloquear ``getaddrinfo`` se llevaría puesta también la resolución de ``localhost`` y
    no protege nada más: lo único que se filtra es el nombre del host, sin credenciales,
    sin cuota de API y sin dato que vuelva.

    **Por qué ``socket.socket`` alcanza también al TLS, que no es obvio.**
    ``ssl.SSLSocket`` define ``connect`` y ``connect_ex`` **propios** —o sea que el parche
    de la clase base no los pisa— pero los dos delegan en ``_real_connect``, que llama
    ``super().connect(addr)``, y ese ``super()`` resuelve por MRO **en el momento de la
    llamada**: cae en el atributo parcheado. Verificado midiendo, no deducido, y fijado
    por un test, porque es la clase de detalle que una versión de Python puede cambiar
    sin que nadie se entere hasta que un test vuelva a salir a internet en silencio.
    """
    INTENTOS_BLOQUEADOS.clear()

    if request.node.get_closest_marker("network"):
        return

    import socket as _socket

    # `socket.socket.connect` es el cuello de botella de TODO lo que va por el módulo
    # socket: `requests`/`urllib3` arman el socket y llaman `connect`, y el
    # `socket.create_connection` de `http.client` hace lo mismo un nivel más abajo.
    # Verificado midiendo: parchear sólo esto alcanza para bloquear `requests.get`.
    _real_connect = _socket.socket.connect
    _real_connect_ex = _socket.socket.connect_ex

    def _connect(self, address, *a, **kw):
        if _es_local(address):
            return _real_connect(self, address, *a, **kw)
        INTENTOS_BLOQUEADOS.append(f"socket.connect {address!r}")
        raise RedBloqueadaEnLaSuite(
            f"este test intentó conectarse a {address!r}. La suite no sale a internet: "
            "mockeá la fuente, o marcá el test con @pytest.mark.network si de verdad "
            "tiene que pegarle a la API real (tarea 209)."
        )

    def _connect_ex(self, address, *a, **kw):
        if _es_local(address):
            return _real_connect_ex(self, address, *a, **kw)
        INTENTOS_BLOQUEADOS.append(f"socket.connect_ex {address!r}")
        raise RedBloqueadaEnLaSuite(
            f"este test intentó conectarse (connect_ex) a {address!r}; ver el mensaje de "
            "`connect` (tarea 209)."
        )

    monkeypatch.setattr(_socket.socket, "connect", _connect)
    monkeypatch.setattr(_socket.socket, "connect_ex", _connect_ex)

    try:
        import curl_cffi
    except ImportError:  # pragma: no cover — sin yfinance moderno no hay nada que cortar
        return

    def _perform(self, *a, **kw):
        INTENTOS_BLOQUEADOS.append("curl_cffi.Curl.perform")
        raise RedBloqueadaEnLaSuite(
            "este test intentó un request con curl_cffi (el camino de yfinance). La suite "
            "no sale a internet: usá el fixture mock_yfinance, o marcá el test con "
            "@pytest.mark.network (tarea 209)."
        )

    monkeypatch.setattr(curl_cffi.Curl, "perform", _perform)
