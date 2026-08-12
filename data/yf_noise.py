"""
Filtro de ruido para el logger de ``yfinance`` (backlog UNIV1, pieza c).

El problema
-----------
yfinance **no tira excepción** cuando el endpoint ``quoteSummary`` devuelve 404:
loguea el error él mismo (logger ``yfinance``, nivel ERROR) y devuelve un frame
vacío. Por eso el retry/clasificación de ``data.yahoo_finance`` ni se entera —
``_is_transient`` nunca se consulta— y cada símbolo problemático deja ~2 líneas
ERROR con traceback por run (una por módulo consultado: ``recommendations`` y
``analyst_price_targets``). Un scan de Leads sobre el S&P 500 producía ~24 ERRORs
que enterraban los errores reales del log.

El discriminador (verificado contra Yahoo el 2026-07-20)
--------------------------------------------------------
Los dos 404 de ``quoteSummary`` NO significan lo mismo:

- ``"Quote not found for symbol: X"`` → el símbolo **no existe** en Yahoo
  (deslistado o renombrado). 14/14 de los casos del log 2026-07-15 quedaron sin
  barras al probarlos: ANSS, CTLT, CMA, CTRA, DAY, DFS, FI, HOLX, HES, IPG,
  JNPR, MMC, PARA, WBA. Es **permanente**: no se reintenta.
- ``"No fundamentals data found for symbol: X"`` → el símbolo existe pero Yahoo
  no sirve *ese módulo*. **FOX y LOW** cotizan perfectamente y producen este 404.
  Tratarlo como delisting habría sacado a Lowe's del universo.

Qué hace este filtro
--------------------
Descarta esas dos líneas (son esperables y ruidosas) y, para las del primer tipo,
anota el símbolo en un set en memoria. La anotación es un ``set`` y nada más:
escribir a la DB desde un handler de logging invita a reentrancia (un fallo de
escritura loguea → vuelve a entrar al filtro). El consumidor —
``data.yahoo_finance.get_analyst_data``— lee el set *después* del fetch y recién
ahí llama a ``_record_miss``, que ya sabe distinguir delisting de throttle (B3).

Ampliación LOG-HYGIENE (tarea 25, pieza b)
------------------------------------------
``<TICKER>: Yahoo web request for share count failed`` sale del mismo logger a
nivel **ERROR** (``yfinance/base.py``, dos sitios) y aparece pegado a los eventos
de throttle — o sea, es **transitorio y ya manejado**: yfinance devuelve ``None``
y el caller sigue sin el dato de shares. A nivel ERROR compite visualmente con
fallos reales.

Acá se **degrada a DEBUG en vez de descartarse**: el ERROR no es informativo pero
el evento sí (correlaciona con el throttle), así que conviene que siga estando
para diagnosticar, solo que fuera del nivel que uno mira cuando algo se rompe.
Es la diferencia con los 404 de arriba, que no aportan nada y se tiran.
"""

from __future__ import annotations

import logging
import re
import threading

_QUOTE_NOT_FOUND = re.compile(r"Quote not found for symbol:\s*([^\"'}\s]+)")
_NO_FUNDAMENTALS = re.compile(r"No fundamentals data found for symbol:\s*([^\"'}\s]+)")
# Tarea 25(b): transitorio y ya manejado por yfinance (devuelve None) → DEBUG.
_SHARE_COUNT_FAILED = re.compile(r"Yahoo web request for share count failed")

_lock = threading.Lock()
_unknown_symbols: set[str] = set()

_installed = False


def note_unknown_symbol(symbol: str) -> None:
    """Marca ``symbol`` como inexistente en Yahoo (visto en un 404 de quote)."""
    if symbol:
        with _lock:
            _unknown_symbols.add(symbol.upper())


def is_unknown_symbol(symbol: str) -> bool:
    """¿Yahoo dijo en este proceso que ``symbol`` no existe?"""
    with _lock:
        return symbol.upper() in _unknown_symbols


def unknown_symbols() -> set[str]:
    """Copia del set de símbolos inexistentes vistos hasta ahora."""
    with _lock:
        return set(_unknown_symbols)


def reset_unknown_symbols() -> None:
    """Limpia el set — para tests y para forzar un re-chequeo."""
    with _lock:
        _unknown_symbols.clear()


class QuoteSummary404Filter(logging.Filter):
    """Silencia los 404 esperables de ``quoteSummary`` y anota los símbolos muertos.

    Descarta los dos patrones de 404 conocidos y **degrada a DEBUG** el fallo de
    share count (tarea 25b). Cualquier otro mensaje de yfinance pasa intacto y
    con su nivel original — no queremos tapar errores nuevos, que es justo lo que
    este filtro viene a destapar.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover — record mal formado
            return True

        match = _QUOTE_NOT_FOUND.search(message)
        if match:
            note_unknown_symbol(match.group(1))
            return False

        if _NO_FUNDAMENTALS.search(message):
            return False

        if _SHARE_COUNT_FAILED.search(message) and record.levelno > logging.DEBUG:
            # Degradar, no descartar: el evento correlaciona con el throttle y
            # sirve para diagnosticar, pero no es un fallo accionable.
            record.levelno = logging.DEBUG
            record.levelname = logging.getLevelName(logging.DEBUG)

        return True


def install(logger_name: str = "yfinance") -> bool:
    """Instala el filtro en el logger de yfinance. Idempotente.

    Devuelve ``True`` si lo instaló, ``False`` si ya estaba.
    """
    global _installed
    if _installed:
        return False
    logging.getLogger(logger_name).addFilter(QuoteSummary404Filter())
    _installed = True
    return True
