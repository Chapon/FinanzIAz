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
