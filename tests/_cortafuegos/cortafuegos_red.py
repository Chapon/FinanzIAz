"""La implementación del cortafuegos de red de la suite — UNA sola (tareas 209 y 211).

**Por qué este módulo existe y no es parte de `conftest.py`.** El corte de la 209 vive en
un fixture `autouse` con `monkeypatch`, o sea **en memoria de este proceso**. Un
subproceso hereda el entorno pero no los parches, así que salía a internet igual — es la
forma exacta de la **108**, donde `_guard_real_db` rebindeaba la DB acá y los hijos se
quedaban con la ruta de producción hasta que el aislamiento se movió a una variable de
entorno. La **211** cierra esa mitad con `sitecustomize.py`, que el intérprete del hijo
importa solo al arrancar.

**Y por eso el código está acá y no copiado en los dos lados.** Dos implementaciones del
mismo corte divergen: es lo que pasó en la **207**, donde `collect_all` y los `collect_*`
públicos eran dos caminos y uno quedó sin el veredicto. Acá el fixture del padre y el
`sitecustomize` del hijo llaman **a la misma función**, y un test lo fija comparando las
identidades.

Este archivo se importa desde un intérprete que **recién arranca** (por `site.py`), así
que no puede asumir nada del proyecto: ni `sys.path`, ni el cwd, ni que pandas exista.
Sólo stdlib, y todo lo opcional entre `try`.
"""

from __future__ import annotations

import socket as _socket

#: Nombre de la variable de entorno que enciende el corte en un **subproceso** (211).
#: El entorno es lo único que un hijo hereda solo — el mismo argumento de la 108 para
#: ``FINANZIAS_DB_PATH`` y de la 148 para ``FINANZIAS_DISABLE_SLACK``.
VAR_ENTORNO = "FINANZIAS_BLOQUEAR_RED"


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


def es_local(address) -> bool:
    host = address[0] if isinstance(address, (tuple, list)) and address else address
    return isinstance(host, str) and (host in _HOSTS_LOCALES or host.startswith("127."))


def pythonpath_con(directorio: str, actual: str | None, sep: str) -> str:
    """El ``PYTHONPATH`` del hijo: ``directorio`` **agregado**, no pisando lo que había.

    Existe como función aparte por un motivo concreto: en esta máquina ``PYTHONPATH``
    está **vacío**, así que "agregar" y "pisar" dan exactamente lo mismo y una mutación
    que lo reemplace por ``[directorio]`` queda **verde**. Medido: eso pasó al mutar la
    211. Separada y pura, la propiedad se puede afirmar con un valor previo inventado,
    sin depender de cómo esté el entorno de quien corra la suite.

    Va **al final** y no al principio: este directorio sólo tiene que aportar
    ``sitecustomize``, y ponerlo primero le ganaría la prioridad a cualquier cosa que el
    entorno de Chapa ya estuviera resolviendo por ahí.
    """
    # `.strip()` y no sólo `or ""`: un `PYTHONPATH` de puros espacios se colaba como una
    # entrada de verdad y dejaba `"   ;dir"`, que es un path basura a la izquierda del
    # nuestro. Lo cazó el test parametrizado, no la lectura.
    return sep.join([p for p in ((actual or "").strip(), directorio) if p])


def instalar(poner: callable) -> None:
    """Arma el corte en los **dos** transportes, usando ``poner(objeto, nombre, valor)``.

    El parámetro existe para que el padre pueda pasar ``monkeypatch.setattr`` —y que el
    parche se deshaga solo al terminar el test— mientras el hijo pasa un ``setattr``
    pelado, porque ahí el proceso entero es de un solo uso. La **lógica del corte es la
    misma función en los dos casos**, que es lo que evita que se separen.

    **Hay que cortar en DOS lugares, y el segundo es el que importa.** Parchear ``socket``
    alcanza a ``requests``/``urllib3``/``http.client`` (Finnhub, EDGAR, RSS) y **no a
    ``curl_cffi``**, que va por libcurl sin pasar por el módulo ``socket`` de Python — y
    ``curl_cffi`` es exactamente lo que usa **yfinance 1.x**, o sea la mayor superficie de
    red del proyecto. Medido antes de escribir esto: con ``socket`` parcheado, ``requests``
    queda bloqueado y ``curl_cffi.get`` **sale igual**. Un cortafuegos sólo-socket habría
    sido la forma exacta del guard que es ciego al caso mayoritario.
    """
    # `socket.socket.connect` es el cuello de botella de TODO lo que va por el módulo
    # socket: `requests`/`urllib3` arman el socket y llaman `connect`, y el
    # `socket.create_connection` de `http.client` hace lo mismo un nivel más abajo.
    # Verificado midiendo: parchear sólo esto alcanza para bloquear `requests.get`.
    #
    # Y alcanza también al TLS, que no es obvio: `ssl.SSLSocket` define `connect` y
    # `connect_ex` **propios**, pero los dos delegan en `_real_connect`, que llama
    # `super().connect(addr)` — y ese `super()` resuelve por MRO **en el momento de la
    # llamada**, o sea que cae en el atributo parcheado. Verificado midiendo y fijado
    # por un test, porque es la clase de detalle que una versión de Python puede
    # cambiar sin que nadie se entere hasta que un test vuelva a salir a internet.
    real_connect = _socket.socket.connect
    real_connect_ex = _socket.socket.connect_ex

    def _connect(self, address, *a, **kw):
        if es_local(address):
            return real_connect(self, address, *a, **kw)
        INTENTOS_BLOQUEADOS.append(f"socket.connect {address!r}")
        raise RedBloqueadaEnLaSuite(
            f"este test intentó conectarse a {address!r}. La suite no sale a internet: "
            "mockeá la fuente, o marcá el test con @pytest.mark.network si de verdad "
            "tiene que pegarle a la API real (tarea 209)."
        )

    def _connect_ex(self, address, *a, **kw):
        if es_local(address):
            return real_connect_ex(self, address, *a, **kw)
        INTENTOS_BLOQUEADOS.append(f"socket.connect_ex {address!r}")
        raise RedBloqueadaEnLaSuite(
            f"este test intentó conectarse (connect_ex) a {address!r}; ver el mensaje de "
            "`connect` (tarea 209)."
        )

    poner(_socket.socket, "connect", _connect)
    poner(_socket.socket, "connect_ex", _connect_ex)

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

    poner(curl_cffi.Curl, "perform", _perform)
