"""
Registro de tickers fallidos.

Mantiene en SQLite la lista de símbolos que devolvieron error al consultar
Yahoo Finance (delisted, ticker incorrecto, sin datos, etc.) para:

1. Filtrarlos antes de llamadas en bulk (evita ruido en logs y ahorra QPS).
2. Mostrarlos al usuario en una pestaña dedicada con sus últimos errores.
3. Permitir reintento manual o ignorado permanente.

API pública
-----------
- ``record_failure(ticker, error, operation)``  → graba o actualiza (permanente)
- ``record_transient(ticker, error, operation)``→ fallo transitorio (se reintenta)
- ``record_success(ticker)``                    → limpia el registro
- ``get_all()``                                 → lista para la UI
- ``get_failing_set()``                         → set de tickers a omitir
- ``mark_for_retry(ticker)``                    → cambia status a "retry"
- ``mark_ignored(ticker)``                      → status "ignored"
- ``delete(ticker)``                            → borra del registro
- ``clear_all()``                               → vacía la tabla

``failing`` vs ``transient``
----------------------------
``failing``/``ignored`` son los únicos status que ``get_failing_set`` saltea: el
símbolo se considera permanentemente malo (deslistado, ticker incorrecto). Un
``transient`` es un fallo que casi seguro es culpa de Yahoo (timeout, throttle,
401/crumb, lote entero vacío), NO del símbolo — se registra para visibilidad pero
**no** se saltea, así un large-cap real que falló por un throttle vuelve a
intentarse el próximo scan en vez de quedar excluido del universo (bug B3).

Todas las operaciones son tolerantes a fallos: si la DB no está disponible,
loguean y devuelven valores neutros para no romper el flujo principal.
"""

from dataclasses import dataclass
from datetime import datetime

from config.logging_config import get_logger
from database.models import FailedTicker, session_scope

log = get_logger(__name__)

# Status values
STATUS_FAILING = "failing"
STATUS_RETRY = "retry"
STATUS_IGNORED = "ignored"
STATUS_TRANSIENT = "transient"


@dataclass
class FailedTickerRow:
    """Snapshot inmutable de un registro — seguro para pasar fuera del session_scope."""

    ticker: str
    last_error: str | None
    last_operation: str | None
    fail_count: int
    first_failed_at: datetime
    last_failed_at: datetime
    status: str


def _to_row(record: FailedTicker) -> FailedTickerRow:
    return FailedTickerRow(
        ticker=record.ticker,
        last_error=record.last_error,
        last_operation=record.last_operation,
        fail_count=record.fail_count,
        first_failed_at=record.first_failed_at,
        last_failed_at=record.last_failed_at,
        status=record.status,
    )


def record_failure(ticker: str, error: str, operation: str = "fetch") -> None:
    """
    Registra un fallo para ``ticker``. Si ya existía, incrementa el contador
    y actualiza el último error/operación. Si estaba marcado como ``retry``,
    vuelve a ``failing`` para que se omita de nuevo.
    """
    if not ticker:
        return
    try:
        symbol = ticker.upper().strip()
        # Truncar mensajes muy largos para no explotar la columna
        err_msg = (error or "")[:500]
        op = (operation or "fetch")[:50]

        with session_scope() as session:
            existing = session.query(FailedTicker).filter(FailedTicker.ticker == symbol).first()
            if existing:
                existing.last_error = err_msg
                existing.last_operation = op
                existing.fail_count = (existing.fail_count or 0) + 1
                # Si estaba en retry y volvió a fallar, vuelve a failing
                if existing.status == STATUS_RETRY:
                    existing.status = STATUS_FAILING
            else:
                session.add(
                    FailedTicker(
                        ticker=symbol,
                        last_error=err_msg,
                        last_operation=op,
                        fail_count=1,
                        status=STATUS_FAILING,
                    )
                )
    except Exception:
        log.exception("No se pudo registrar fallo para %s", ticker)


def record_transient(ticker: str, error: str, operation: str = "fetch", *, override: bool = False) -> None:
    """
    Registra un fallo **transitorio** (timeout/throttle/401/lote vacío) para
    ``ticker``: visible en la UI pero NO entra al ``failing`` set, así el símbolo
    se reintenta el próximo scan en vez de quedar excluido del universo.

    Si el ticker ya estaba marcado ``failing``/``ignored`` (positivamente malo,
    p.ej. deslistado confirmado) NO se degrada: ese conocimiento se preserva.

    ``override=True`` permite degradar un ``failing`` a transitorio — se usa
    cuando *a posteriori* se confirma que el fallo fue wholesale (todo un lote/
    bulk falló a la vez = throttle, no un símbolo muerto). ``ignored`` (decisión
    explícita del usuario) nunca se pisa.
    """
    if not ticker:
        return
    try:
        symbol = ticker.upper().strip()
        err_msg = (error or "")[:500]
        op = (operation or "fetch")[:50]

        with session_scope() as session:
            existing = session.query(FailedTicker).filter(FailedTicker.ticker == symbol).first()
            if existing:
                # No pisar un veredicto permanente con uno transitorio, salvo override
                # (y nunca pisar 'ignored', que es decisión manual del usuario).
                if existing.status == STATUS_IGNORED:
                    return
                if existing.status == STATUS_FAILING and not override:
                    return
                existing.last_error = err_msg
                existing.last_operation = op
                existing.fail_count = (existing.fail_count or 0) + 1
                existing.status = STATUS_TRANSIENT
            else:
                session.add(
                    FailedTicker(
                        ticker=symbol,
                        last_error=err_msg,
                        last_operation=op,
                        fail_count=1,
                        status=STATUS_TRANSIENT,
                    )
                )
    except Exception:
        log.exception("No se pudo registrar fallo transitorio para %s", ticker)


def record_success(ticker: str) -> None:
    """
    Limpia el registro si la consulta volvió a funcionar. No falla si no
    existía registro previo.
    """
    if not ticker:
        return
    try:
        symbol = ticker.upper().strip()
        with session_scope() as session:
            # Read-before-write: el caso normal (ticker nunca falló) no tiene
            # fila que borrar. Saltarse el DELETE evita abrir una transacción de
            # ESCRITURA por cada ticker exitoso — durante un scan sano de ~52
            # tickers en paralelo eso eran ~52 write-locks innecesarios que
            # alimentaban "database is locked" + agotamiento del pool. El SELECT
            # es concurrente bajo WAL y no toma el lock de escritura.
            exists = (
                session.query(FailedTicker.id)
                .filter(FailedTicker.ticker == symbol)
                .first()
            )
            if exists is None:
                return
            session.query(FailedTicker).filter(FailedTicker.ticker == symbol).delete()
    except Exception:
        log.exception("No se pudo limpiar registro de éxito para %s", ticker)


def get_all() -> list[FailedTickerRow]:
    """Devuelve la lista completa ordenada por última falla descendente."""
    try:
        with session_scope() as session:
            rows = session.query(FailedTicker).order_by(FailedTicker.last_failed_at.desc()).all()
            return [_to_row(r) for r in rows]
    except Exception:
        log.exception("No se pudo leer la lista de tickers fallidos")
        return []


def get_failing_set() -> set[str]:
    """
    Devuelve el set de tickers que deben omitirse (status=failing o ignored).
    Los marcados como "retry" se incluyen en el flujo normal para volver a probar.
    """
    try:
        with session_scope() as session:
            rows = (
                session.query(FailedTicker.ticker)
                .filter(FailedTicker.status.in_([STATUS_FAILING, STATUS_IGNORED]))
                .all()
            )
            return {r[0] for r in rows}
    except Exception:
        log.exception("No se pudo leer el set de tickers a omitir")
        return set()


def mark_for_retry(ticker: str) -> None:
    """Marca un ticker para que vuelva a intentarse en el próximo fetch."""
    if not ticker:
        return
    try:
        symbol = ticker.upper().strip()
        with session_scope() as session:
            existing = session.query(FailedTicker).filter(FailedTicker.ticker == symbol).first()
            if existing:
                existing.status = STATUS_RETRY
    except Exception:
        log.exception("No se pudo marcar %s para retry", ticker)


def mark_ignored(ticker: str) -> None:
    """Marca un ticker como permanentemente ignorado."""
    if not ticker:
        return
    try:
        symbol = ticker.upper().strip()
        with session_scope() as session:
            existing = session.query(FailedTicker).filter(FailedTicker.ticker == symbol).first()
            if existing:
                existing.status = STATUS_IGNORED
    except Exception:
        log.exception("No se pudo marcar %s como ignorado", ticker)


def delete(ticker: str) -> None:
    """Borra el registro del ticker (equivalente a 'olvidar el fallo')."""
    if not ticker:
        return
    try:
        symbol = ticker.upper().strip()
        with session_scope() as session:
            session.query(FailedTicker).filter(FailedTicker.ticker == symbol).delete()
    except Exception:
        log.exception("No se pudo borrar el registro de %s", ticker)


def clear_all() -> int:
    """Vacía la tabla completa. Devuelve la cantidad de filas eliminadas."""
    try:
        with session_scope() as session:
            count = session.query(FailedTicker).count()
            session.query(FailedTicker).delete()
            return count
    except Exception:
        log.exception("No se pudo vaciar la tabla de tickers fallidos")
        return 0


def filter_skippable(tickers: list[str]) -> tuple[list[str], list[str]]:
    """
    Particiona una lista en (a_consultar, a_omitir).

    Útil antes de un bulk fetch::

        to_query, skipped = filter_skippable(all_tickers)
        prices = get_bulk_prices(to_query)
        # ... loguear o reportar los skipped por separado
    """
    if not tickers:
        return [], []
    skip = get_failing_set()
    if not skip:
        return list(tickers), []
    to_query: list[str] = []
    skipped: list[str] = []
    for t in tickers:
        if t.upper().strip() in skip:
            skipped.append(t)
        else:
            to_query.append(t)
    return to_query, skipped
