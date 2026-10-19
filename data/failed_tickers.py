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
- ``record_success(ticker, operation)``         → limpia el registro (``serie_congelada``
  sólo con ``historical``, tarea 369)
- ``get_all()``                                 → lista para la UI
- ``get_failing_set(para=)``                    → set de tickers a omitir (un ``failing`` de
  más de ``REINTENTO_DIAS`` se reintenta, tarea 366)
- ``podar()``                                   → borra lo que no falla hace ``PODA_DIAS``
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
from datetime import datetime, timedelta

from config.logging_config import get_logger
from database.models import FailedTicker, session_scope, utcnow_naive

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


#: Operación de un ticker cuya serie diaria dejó de avanzar (tarea 369): Yahoo lo dejó de
#: cotizar, pero ``fast_info`` sigue devolviendo el último precio. Ese "precio" no prueba que
#: el ticker volvió, así que sólo un histórico que avanza borra la fila.
OP_SERIE_CONGELADA = "serie_congelada"


def record_success(ticker: str, operation: str | None = None) -> None:
    """
    Limpia el registro si la consulta volvió a funcionar. No falla si no
    existía registro previo.

    Una fila ``serie_congelada`` (tarea 369) sólo la borra un éxito de ``historical``: el
    precio de ``fast_info`` de un ticker deslistado es el último que tuvo, y contarlo como
    éxito lo devolvía al universo con un precio que no se mueve. ``operation=None`` borra
    cualquier fila, como antes.
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
            fila = (
                session.query(FailedTicker.id, FailedTicker.last_operation)
                .filter(FailedTicker.ticker == symbol)
                .first()
            )
            if fila is None:
                return
            if fila.last_operation == OP_SERIE_CONGELADA and operation not in (None, "historical"):
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


#: Tarea 366 — un ``failing`` sale de los fetches, así que nunca se vuelve a pedir y nunca
#: se entera de que revivió: EMBJ (de la cartera real) quedó afuera del 10/10 al 19/10 por un
#: solo "Sin precio" a las 02:25. Pasados estos días desde su última falla, deja de saltearse
#: y el fetch siguiente lo prueba: si anda, ``record_success`` borra la fila; si falla,
#: ``record_failure`` le renueva la fecha y la espera vuelve a contar. Con las 12 filas del
#: 2026-10-19, una prueba por semana de cada una no se nota ni en el log ni en la cuota.
REINTENTO_DIAS = 7
#: Las filas sin ninguna falla en este tiempo se borran al arrancar (``podar``): son typos de
#: la pestaña Análisis o símbolos que nadie volvió a pedir. Si alguien lo pide, se registra de
#: nuevo. ``ignored`` no se toca: lo decidió Chapa.
PODA_DIAS = 30


def _ahora() -> datetime:
    return utcnow_naive()  # la misma marca que escribe ``last_failed_at``


def get_failing_set(*, para: str = "precio", ahora: datetime | None = None) -> set[str]:
    """
    Devuelve el set de tickers que deben omitirse.

    - ``ignored``: siempre (decisión de Chapa).
    - ``failing``: mientras su última falla tenga menos de ``REINTENTO_DIAS`` (tarea 366);
      después se reintenta.
    - ``serie_congelada`` (tarea 369): para ``para="precio"`` se saltea **siempre**, porque el
      precio de un ticker deslistado es el último que tuvo y no prueba nada; sólo el
      histórico (``para="historico"``) lo reintenta, y es el único que puede liberarlo.

    Los marcados como "retry" y los ``transient`` se incluyen en el flujo normal.
    """
    limite = (ahora or _ahora()) - timedelta(days=REINTENTO_DIAS)
    try:
        with session_scope() as session:
            rows = (
                session.query(
                    FailedTicker.ticker,
                    FailedTicker.status,
                    FailedTicker.last_operation,
                    FailedTicker.last_failed_at,
                )
                .filter(FailedTicker.status.in_([STATUS_FAILING, STATUS_IGNORED]))
                .all()
            )
    except Exception:
        log.exception("No se pudo leer el set de tickers a omitir")
        return set()
    omitir = set()
    for ticker, status, operacion, ultima in rows:
        if (
            status == STATUS_IGNORED  # decisión de Chapa
            or (operacion == OP_SERIE_CONGELADA and para != "historico")  # 369: el precio no la libera
            or ultima is None
            or ultima >= limite  # 366: todavía en la espera
        ):
            omitir.add(ticker)
    return omitir


def podar(dias: int = PODA_DIAS, ahora: datetime | None = None) -> int:
    """Borra las filas no ``ignored`` sin fallas en ``dias``. Devuelve cuántas (tarea 366)."""
    limite = (ahora or _ahora()) - timedelta(days=dias)
    try:
        with session_scope() as session:
            viejas = session.query(FailedTicker).filter(
                FailedTicker.status != STATUS_IGNORED, FailedTicker.last_failed_at < limite
            )
            tickers = sorted(r.ticker for r in viejas.all())
            if tickers:
                viejas.delete(synchronize_session=False)
    except Exception:
        log.exception("No se pudo podar la tabla de tickers fallidos")
        return 0
    if tickers:
        log.info(
            "Tickers fallidos: %d sin fallas en %d días, borrados: %s", len(tickers), dias, ", ".join(tickers)
        )
    return len(tickers)


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
