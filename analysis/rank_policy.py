"""
Políticas de orden entre candidatos — **Tarea 39 (RANK-NEUTRAL)**.

Por qué existe
--------------
El engine rankea los candidatos BUY del día por ``buy_score`` y se queda con los
mejores hasta llenar los slots. Seis mediciones convergentes dicen que ese score
**rankea al revés** (``corr = −0.0259``, AUC 0.4980, y en la T21 el ranking vivo
quedó **por debajo de la banda entera** de diez órdenes aleatorias). La T9 midió
que eso **no es gratis**: un score sin alpha que igual decide **concentra** la
cartera en el subconjunto malo en vez de repartir, y cuesta ~8 pp de CAGR.

La política candidata de la Tarea 39 es el **orden aleatorio rotado**: un orden
arbitrario que **no persiste entre días**, o sea "sin información" de verdad — a
diferencia del alfabético, que es orden **fijo** y por lo tanto una apuesta a
nombres fijos durante 10 años (T21 §2b: ganó por suerte, +3.10 pp sobre la
mediana de las semillas).

Qué provee y por qué así
------------------------
``neutral_rank(seed, fecha, ticker)`` es una **función pura**: el valor depende
sólo de sus tres argumentos, nunca del orden en que se la llame ni del estado de
la cartera. Eso importa por dos motivos concretos:

1. **Es el objeto que se cablearía.** El engine ve un conjunto de candidatos
   distinto cada día (y cada 15 minutos), así que una política cuyo valor
   dependa de la secuencia de llamadas **no es implementable** ahí.
2. **Es el defecto que se le encontró al brazo aleatorio de la T21** (tarea 40):
   ``run_ranking_t21.py`` cacheaba ``random.random()`` por par ``(ticker,
   fecha)``, así que el número dependía del orden de las llamadas del ``sorted()``
   del día. Determinista dentro de una corrida —la banda publicada se sostiene—
   pero no reproducible ante un cambio de población ni shipeable.

``fixed_rank(seed, ticker)`` es la contracara: orden aleatorio **fijo** (ignora
la fecha). No es candidato — es el **nulo pareado en persistencia** del §4.2 del
pre-registro. El score vivo es persistente y el rotado no, así que las dos
familias **acotan** al score y permiten leer el resultado sin depender del
supuesto de persistencia.

Es lógica pura (stdlib): sin red, sin DB, sin numpy.
"""

from __future__ import annotations

from hashlib import blake2b

# 56 bits de hash ⇒ el float64 representa el entero exacto y el cociente cae en
# [0, 1) sin redondear a 1.0.
_DIGEST_BYTES = 7
_SCALE = float(1 << (8 * _DIGEST_BYTES))


def _u(seed: int, *parts: str) -> float:
    """``u ∈ [0, 1)`` determinista a partir de ``seed`` y las partes dadas.

    ``blake2b`` y no ``hash()``: el ``hash()`` de Python está randomizado por
    proceso (``PYTHONHASHSEED``), así que daría un orden distinto en cada corrida
    y en cada scan del engine.
    """
    payload = "|".join((str(int(seed)), *parts)).encode("utf-8")
    digest = blake2b(payload, digest_size=_DIGEST_BYTES).digest()
    return int.from_bytes(digest, "big") / _SCALE


def neutral_rank(seed: int, date_iso10: str, ticker: str) -> float:
    """Orden aleatorio **rotado por fecha** — la política candidata de la T39.

    Mayor entra primero (misma convención que ``rank_score`` de
    ``portfolio_sim`` y que el ``strength`` del engine). Puro: dos llamadas con
    los mismos argumentos devuelven el mismo bit, en cualquier orden.
    """
    return _u(seed, date_iso10, ticker)


def fixed_rank(seed: int, ticker: str) -> float:
    """Orden aleatorio **fijo** (no depende de la fecha) — nulo pareado en persistencia.

    Diagnóstico, **no promovible a candidato**: un orden fijo es una apuesta a
    nombres fijos durante toda la muestra, que es exactamente por qué el
    alfabético de la T21 no era un baseline neutro.
    """
    return _u(seed, ticker)


def rate_matched_priority(
    candidates_by_date: "dict[str, list[str]]",
    n_by_date: "dict[str, int]",
    seed: int,
) -> "set[tuple[str, str]]":
    """Conjunto priorizado **igualado en tasa** — enabler de la **Tarea 49**.

    Dado el conjunto de candidatos de cada fecha y **cuántas** prioridades lleva
    esa fecha (``n_by_date``, que sale del brazo candidato), elige esas mismas
    ``n`` por fecha **al azar** con ``neutral_rank(seed, fecha, ticker)`` y
    devuelve los pares ``(ticker, fecha)`` priorizados.

    Por qué existe: el descriptivo de la 45 midió que priorizar el candidato de
    anomalía vale +4.21 pp de CAGR, y el propio veredicto declaró que ese número
    está **confundido** con *"cualquier cosa menos el orden de siempre"*. La única
    forma de atribuirlo al evento es compararlo contra priorizar **lo mismo, en
    los mismos días, en la misma cantidad**, pero eligiendo al azar. Es la lección
    de la T26 (*"el umbral va contra el control igualado en tasa, no contra el
    baseline"*) aplicada al eje del turno.

    **Pura** (T39 §5.7): el resultado depende sólo de ``(seed, fecha, ticker)`` y
    del conjunto de candidatos del día — que es idéntico entre brazos porque sale
    de las mismas ``entries``. No depende del orden de las llamadas ni del estado
    de la cartera.
    """
    out: set[tuple[str, str]] = set()
    for date_iso10, n in n_by_date.items():
        if n <= 0:
            continue
        pool = candidates_by_date.get(date_iso10) or []
        if not pool:
            continue
        # ``sorted`` sobre una clave pura ⇒ el desempate por ticker lo hace
        # determinista incluso si dos hashes coincidieran.
        ranked = sorted(pool, key=lambda t: (-neutral_rank(seed, date_iso10, t), t))
        out.update((t, date_iso10) for t in ranked[:n])
    return out
