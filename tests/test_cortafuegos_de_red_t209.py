"""Tarea 209 (SUITE-SIN-CORTAFUEGO-DE-RED) — la suite no sale a internet, y se prueba.

``CLAUDE.md`` decía *«`tests/conftest.py` bloquea red en unit tests»* y era **falso**. Los
cuatro aislamientos de `conftest.py` cubren el log (78), la DB incluso en subprocesos
(108), el fetch de tooltip (82) y Slack (148); la red no la tocaba ninguno, y
``mock_yfinance`` es **opt-in** y sólo parchea ``data.yahoo_finance.yf``.

**Cómo se descubrió.** El 2026-09-15, al mover la costura de ``collect_all`` en la tarea
207, tres tests quedaron parcheando un nombre que ya nadie llamaba y ``_finnhub_news``
**salió a la API real de Finnhub** —hay key viva en esta máquina— devolviendo 257
artículos de verdad. Se notó **sólo** porque el contenido no coincidía con el fake.

**El barrido dio SIETE, y la primera versión de este texto decía cero.** Vale contarlo,
porque el error era de método y es el mismo que la tarea entera denuncia: yo había
razonado *«la suite queda verde con el corte puesto ⇒ ningún test salía a internet»*, y
**eso no se sigue**. Un test que atrapa `Exception` ampliamente —o que llama a un gate
que falla abierto— se traga el bloqueo y pasa **igual**, habiendo intentado el fetch. La
medición no es el exit code: es la **bitácora**, leída test por test. Con ella,
`INTENTOS_BLOQUEADOS` acusa **7 tests reales** (más los 7 de este archivo, que intentan a
propósito):

* `test_anti_churn.py` — 4 tests, y `test_anti_whipsaw.py` — 2: llaman a `run_scan` con
  `prices_provider` y `history_provider` inyectados, pero el **calendario de earnings del
  Gate 6** no está mockeado. El stack: `yahoo_finance.py:_do_fetch` → `yf.Ticker.calendar`,
  en un **thread del pool** del scan, que es por qué nunca apareció en ningún traceback.
* `test_price_sanity.py::test_get_current_price_rejects_out_of_band` — 1, por el mismo
  camino, y **sólo cuando corre la suite entera**: aislado no se dispara, así que depende
  del estado del cache. Un test cuyo contacto con la red depende del orden de ejecución
  es justo lo que nadie va a encontrar leyendo el archivo.

Los siete **pasan con el corte y pasaban sin él**, y ahí está lo que la 209 les dio
gratis: antes su resultado dependía de lo que Yahoo contestara ese día, y ahora el gate
falla abierto **siempre**. Quedan registrados como tarea aparte en vez de arreglarse acá.

**Se corta en DOS lugares y el segundo es el que importa.** ``socket`` alcanza a
``requests``/``urllib3``/``http.client`` (Finnhub, EDGAR, RSS) y **no a ``curl_cffi``**,
que va por libcurl sin pasar por el módulo ``socket`` — y ``curl_cffi`` es lo que usa
**yfinance 1.x**, la mayor superficie de red del proyecto. Medido antes de escribir el
fixture: con ``socket`` parcheado, ``curl_cffi.get`` **sale igual**. Un cortafuegos
sólo-socket habría sido la forma exacta de un guard ciego al caso mayoritario
([[guard-no-puede-usar-de-verdad-lo-que-chequea]]).
"""

from __future__ import annotations

import contextlib
import socket
import ssl

import pytest

from tests.conftest import INTENTOS_BLOQUEADOS, VAR_ENTORNO, RedBloqueadaEnLaSuite, _es_local

pytest_plugins = ["pytester"]


# ── El bloqueo muerde, por los dos caminos ───────────────────────────────────


def test_un_socket_saliente_se_bloquea():
    """El camino de `requests`/`urllib3`/`http.client`."""
    s = socket.socket()
    with pytest.raises(RedBloqueadaEnLaSuite) as e:
        s.connect(("finnhub.io", 443))
    assert "finnhub.io" in str(e.value)
    assert "network" in str(e.value), "el mensaje tiene que decir cómo declarar el test"


def test_connect_ex_tambien_se_bloquea():
    """La otra puerta del mismo módulo, y hay que cerrarla aparte.

    `connect_ex` no levanta: devuelve un errno. O sea que un cliente escrito sobre él
    **no ve ninguna excepción** y el cortafuegos que sólo parchea `connect` lo deja
    pasar entero. El fixture parchea las dos; este test es el que lo fija.
    """
    s = socket.socket()
    with pytest.raises(RedBloqueadaEnLaSuite) as e:
        s.connect_ex(("finnhub.io", 443))
    assert "finnhub.io" in str(e.value)


def test_el_tls_no_se_escapa_por_SSLSocket():
    """**Parece un agujero y no lo es — por un detalle que conviene tener fijado.**

    `ssl.SSLSocket` define `connect` y `connect_ex` **propios**, así que parchear
    `socket.socket` no los pisa: leyendo el código, el TLS parece escapar. No escapa,
    porque los dos delegan en `_real_connect`, que llama `super().connect(addr)`, y ese
    `super()` resuelve por MRO **en el momento de la llamada** y cae en el parche.

    Se fija acá porque es exactamente la clase de detalle que un cambio de CPython
    puede romper **en silencio**: sin este test, el día que `SSLSocket` deje de delegar,
    la suite sigue verde y vuelve a salir a internet sin que nadie se entere.
    """
    contexto = ssl.create_default_context()
    envuelto = contexto.wrap_socket(socket.socket(), server_hostname="finnhub.io")
    try:
        with pytest.raises(RedBloqueadaEnLaSuite):
            envuelto.connect(("finnhub.io", 443))
    finally:
        envuelto.close()


def test_requests_de_verdad_queda_bloqueado():
    """No alcanza con que `socket.connect` tire: lo que importa es que la librería que
    usa el proyecto no llegue a la red."""
    import requests

    with pytest.raises(Exception) as e:
        requests.get("https://finnhub.io/api/v1/quote", timeout=5)
    assert _por_el_cortafuegos(e.value), f"{type(e.value).__name__}: {e.value}"


def test_curl_cffi_queda_bloqueado():
    """**El que un cortafuegos ingenuo se perdería.** `curl_cffi` no pasa por el módulo
    `socket`, así que el parche de arriba no lo toca — verificado midiendo."""
    curl_cffi = pytest.importorskip("curl_cffi")

    with pytest.raises(Exception) as e:
        curl_cffi.requests.get("https://query2.finance.yahoo.com/v1/test", timeout=5)
    assert _por_el_cortafuegos(e.value), f"{type(e.value).__name__}: {e.value}"


def test_yfinance_queda_bloqueado():
    """El camino real del proyecto, de punta a punta: `yf.Ticker(...).news`.

    Es el que la suite ejercita sin querer cada vez que alguien olvida un parche.

    **Este test necesitaba la bitácora para no ser vacuo.** `yfinance` se traga sus
    propios errores y devuelve `[]`, así que la versión anterior —*«assert not
    noticias»*— pasaba **igual con la máquina sin internet**, sin haber probado nada.
    Ahora afirma que el corte **se disparó**, que es la única forma de distinguir «lo
    bloqueé» de «no había red».
    """
    yf = pytest.importorskip("yfinance")

    # **Delta, no «no vacía».** La primera versión afirmaba `assert INTENTOS_BLOQUEADOS`
    # y la mutación 8 —«la bitácora nunca se vacía entre tests»— la dejaba **verde**:
    # pasaba con el bloqueo de un test anterior, que es el mismo pase vacuo entrando por
    # otra puerta. Medir el delta lo hace cierto sin depender de que el fixture limpie.
    antes = len(INTENTOS_BLOQUEADOS)

    with contextlib.suppress(Exception):  # yfinance a veces envuelve, a veces se lo traga
        assert not yf.Ticker("AAPL").news, "yfinance trajo datos reales"

    assert len(INTENTOS_BLOQUEADOS) > antes, (
        "yfinance no llegó a intentar una conexión: este test no probó el cortafuegos. "
        "Si yfinance cambió de transporte, el fixture hay que ampliarlo."
    )


def _por_el_cortafuegos(e: BaseException) -> bool:
    """¿Esta excepción viene del cortafuegos, o el test pasó por otro motivo?

    Sin esto, un test de bloqueo pasa igual si la máquina está **sin internet** — y
    entonces no probó nada. Se recorre la cadena de causas porque `requests` y
    `curl_cffi` envuelven.
    """
    vistos, cur = 0, e
    while cur is not None and vistos < 12:
        if isinstance(cur, RedBloqueadaEnLaSuite):
            return True
        if "RedBloqueadaEnLaSuite" in str(cur) or "tarea 209" in str(cur):
            return True
        cur = cur.__cause__ or cur.__context__
        vistos += 1
    return False


# ── La bitácora se vacía entre tests (hacen falta DOS, y en este orden) ──────


def test_bitacora_1_este_test_la_ensucia():
    """Primera mitad del par: deja una entrada para que la segunda tenga qué NO ver.

    Va apareado con el que sigue **a propósito y en este orden** — pytest corre los
    tests de un archivo en orden de definición. Si alguien los separa, el segundo deja
    de probar lo suyo; por eso el nombre los numera.
    """
    with pytest.raises(RedBloqueadaEnLaSuite):
        socket.socket().connect(("finnhub.io", 443))
    assert INTENTOS_BLOQUEADOS, "el corte tiene que anotar lo que frenó"


def test_bitacora_2_arranca_vacia_pese_a_lo_que_dejo_el_anterior():
    """Segunda mitad: el fixture la vacía al empezar **cada** test.

    Sin esto, una afirmación del tipo *«la bitácora no está vacía»* la puede satisfacer
    el bloqueo de cualquier test anterior. Lo destapó la mutación 8, que dejaba el
    `clear()` afuera y la suite seguía verde.
    """
    assert INTENTOS_BLOQUEADOS == []


# ── Loopback sigue vivo ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("address", "local"),
    [
        (("127.0.0.1", 8000), True),
        (("127.0.0.53", 53), True),
        (("localhost", 5432), True),
        (("::1", 8000), True),
        (("0.0.0.0", 80), True),
        (("finnhub.io", 443), False),
        (("query2.finance.yahoo.com", 443), False),
        (("8.8.8.8", 53), False),
        (("", 80), False),
    ],
)
def test_que_cuenta_como_local(address, local):
    """Cortar loopback sería romper por deporte: lo que se quiere frenar son terceros.

    El host vacío **no** es loopback — es el default de un bind, no de un connect, y
    dejarlo pasar abriría un agujero por descuido.
    """
    assert _es_local(address) is local


def test_un_socket_a_loopback_no_se_bloquea():
    """Un servidor local levantado por un test tiene que seguir funcionando."""
    servidor = socket.socket()
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(1)
    puerto = servidor.getsockname()[1]
    try:
        cliente = socket.socket()
        cliente.settimeout(2)
        cliente.connect(("127.0.0.1", puerto))  # no debe levantar
        cliente.close()
    finally:
        servidor.close()


# ── El escape por marcador, corriendo pytest de verdad adentro ──────────────


def test_el_marcador_network_EXIME_y_su_ausencia_NO(pytester, monkeypatch):
    """**Las dos direcciones, con pytest corriendo de verdad.**

    Un test marcado ``network`` tiene que quedar con el ``socket.connect`` original, y
    uno sin marcador con el parcheado. Se ejercita con un pytest anidado (`pytester`)
    porque es la única forma de probar el efecto de un marcador **sobre otro test** en
    vez de probar la función que lo lee.

    No se conecta a nada: compara la identidad de ``socket.socket.connect``, así que
    corre igual en el CI y con la máquina sin internet.

    **Por qué se le saca la variable al hijo (tarea 211).** Desde la 211 el
    ``sitecustomize`` corta la red en **todo** subproceso que herede
    ``FINANZIAS_BLOQUEAR_RED``, y el pytest anidado es uno. Si la heredara, el
    ``_ORIGINAL`` que el módulo de abajo captura al importarse ya sería **el parche del
    sitecustomize** y no el ``connect`` de verdad: el test seguiría pasando, pero
    comparando dos cosas distintas de las que dice comparar. Se la borra para que el
    anidado arranque limpio y el único parche que se mida sea el del fixture.
    """
    monkeypatch.delenv(VAR_ENTORNO, raising=False)
    # El fixture se importa **por nombre**: `from tests.conftest import *` NO lo trae,
    # porque empieza con guion bajo y `import *` saltea esos nombres. Lo aprendí acá —
    # la primera versión de este test usaba el `*` y el pytest anidado corría sin
    # cortafuegos, o sea probando nada.
    pytester.makeconftest(
        "import sys\n"
        f"sys.path.insert(0, {str(_raiz())!r})\n"
        "from tests.conftest import _cortafuegos_de_red  # noqa: F401 — autouse real\n"
        "\n"
        "def pytest_configure(config):\n"
        "    config.addinivalue_line('markers', 'network: pega a la API real')\n"
    )
    pytester.makepyfile(
        """
        import socket
        import pytest

        _ORIGINAL = socket.socket.connect

        @pytest.mark.network
        def test_marcado_queda_exento():
            assert socket.socket.connect is _ORIGINAL

        def test_sin_marcar_queda_bloqueado():
            assert socket.socket.connect is not _ORIGINAL
        """
    )
    res = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    res.assert_outcomes(passed=2)


def _raiz():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent
