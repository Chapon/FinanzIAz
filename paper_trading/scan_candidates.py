"""
Registro de candidatos del scan — **tarea 256**. Sólo registro: no cambia ninguna decisión.

**Por qué existe.** ``paper_orders`` guarda lo que se **ejecutó**, y el log, avisos y
resúmenes. Lo que el scan **descartó** —un BUY que no entró porque no había lugar, porque lo
frenó un gate o porque perdió el ranking— no quedaba en ningún lado. Chapa preguntó *«¿por
qué no compramos ACN en julio?»* y la respuesta sólo se pudo **reconstruir** desde el store
PIT del harness, cuyo score sale ~0,1 por debajo del vivo: no era verificable.

**Qué se registra, por scan y por cuenta.** Cada ticker que la estrategia evaluó como
candidato a compra, con su score, su lugar en el ranking y cómo terminó:

- ``sin_datos`` — no había historia o ``analyze`` no devolvió nada: ni siquiera se evaluó.
- ``screen`` — era BUY y lo sacó el screen de calidad/liquidez (E1b).
- ``sin_lugar`` — era BUY y perdió el ranking contra los lugares libres.
- ``sin_tamano`` — se eligió, pero el sizing le dio $0 (sin caja, Kelly u overlay).
- ``comprado`` / ``encolado`` — se eligió y el engine lo ejecutó o lo dejó pendiente.
- ``bloqueado`` — se eligió y lo frenó el engine; ``detail`` lleva el texto del gate.

**Lo que NO se registra:** los tickers que ya están en cartera y los que dieron HOLD o SELL.
O sea: **si un ticker no aparece en un scan, ese scan no lo vio como compra.** Registrar
también los HOLD multiplicaría las filas por diez sin contestar una pregunta más.

**Cómo se engancha.** El engine abre un colector (``collecting``) alrededor de la estrategia;
la estrategia anota con ``note``/``mark``. Sin colector abierto, las dos son no-ops: el
harness y cualquier otro que llame a la estrategia no cambian. Las filas se escriben con
``persist`` **en una sesión propia, después de que el scan commiteó**, y cualquier error ahí
se loguea y se traga: el registro nunca puede tumbar un scan.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta

from config.logging_config import get_logger

log = get_logger(__name__)

SIN_DATOS = "sin_datos"
SCREEN = "screen"
SIN_LUGAR = "sin_lugar"
ELEGIDO = "elegido"  # transitorio: el engine lo resuelve en comprado / encolado / bloqueado
SIN_TAMANO = "sin_tamano"
COMPRADO = "comprado"
ENCOLADO = "encolado"
BLOQUEADO = "bloqueado"

RETENTION_DAYS = 90
_DETAIL_MAX = 300

_COLECTOR: ContextVar[list[dict] | None] = ContextVar("finanzias_scan_candidates", default=None)


@contextmanager
def collecting() -> Iterator[list[dict]]:
    """Abre un colector para un scan y lo cierra al salir, pase lo que pase."""
    filas: list[dict] = []
    token = _COLECTOR.set(filas)
    try:
        yield filas
    finally:
        _COLECTOR.reset(token)


def note(
    ticker: str,
    outcome: str,
    *,
    score: float | None = None,
    rank: int | None = None,
    detail: str | None = None,
) -> None:
    """Anota un candidato. No-op si no hay un scan colectando."""
    filas = _COLECTOR.get()
    if filas is None:
        return
    filas.append({"ticker": ticker, "outcome": outcome, "score": score, "rank": rank, "detail": detail})


def mark(ticker: str, outcome: str, detail: str | None = None) -> None:
    """Cambia el resultado de un candidato ya anotado (el último con ese ticker)."""
    filas = _COLECTOR.get()
    if filas is None:
        return
    for fila in reversed(filas):
        if fila["ticker"] == ticker:
            fila["outcome"] = outcome
            if detail is not None:
                fila["detail"] = detail
            return


def _motivo_de_bloqueo(ticker: str, warnings: Iterable[str]) -> str | None:
    """El aviso del engine que frenó la compra de ``ticker``, si dejó uno.

    Los gates escriben ``"{t} BUY bloqueado: …"``; la orden duplicada, ``"{t} BUY: ya existe…"``;
    el fill, ``"{t}: sin precio…"`` / ``"{t}: fill rechazado…"`` / ``"{t}: precio … fuera de
    banda…"``. Los avisos que **no** frenan (``"{t} BUY recortado por ADV"``, ``"{t} BUY SIN cap
    por ADV"``) quedan afuera a propósito: un recorte no es un bloqueo.
    """
    for w in warnings:
        if w.startswith((f"{ticker} BUY bloqueado", f"{ticker} BUY:", f"{ticker}:")):
            return w
    return None


def resolve_engine_outcomes(
    filas: list[dict], new_orders: Iterable, warnings: list[str], *, market_blocked: bool
) -> None:
    """Resuelve cada ``elegido`` según lo que hizo el engine con él."""
    ordenes = [o for o in new_orders if getattr(o, "side", None) == "BUY"]
    comprados = {o.ticker for o in ordenes if o.status == "filled"}
    encolados = {o.ticker for o in ordenes if o.status == "pending"}
    for fila in filas:
        if fila["outcome"] != ELEGIDO:
            continue
        t = fila["ticker"]
        if t in comprados:
            fila["outcome"] = COMPRADO
        elif t in encolados:
            fila["outcome"] = ENCOLADO
        elif market_blocked:
            fila["outcome"] = BLOQUEADO
            fila["detail"] = "mercado cerrado (Gate 1)"
        else:
            fila["outcome"] = BLOQUEADO
            fila["detail"] = _motivo_de_bloqueo(t, warnings) or "el engine no lo ejecutó y no dejó aviso"


def persist(
    account_id: int, scan_at: datetime, filas: list[dict], *, retention_days: int = RETENTION_DAYS
) -> int:
    """Escribe las filas del scan y poda las de más de ``retention_days``. Devuelve cuántas escribió.

    Sesión propia y fail-soft: un error acá se loguea y devuelve 0, nunca sube al scan.
    """
    try:
        from database.models import session_scope
        from paper_trading.models import PaperScanCandidate

        with session_scope() as s:
            for f in filas:
                detail = f.get("detail")
                s.add(
                    PaperScanCandidate(
                        account_id=account_id,
                        scan_at=scan_at,
                        ticker=f["ticker"],
                        outcome=f["outcome"],
                        signal_score=f.get("score"),
                        rank=f.get("rank"),
                        detail=detail[:_DETAIL_MAX] if detail else None,
                    )
                )
            corte = scan_at - timedelta(days=retention_days)
            (
                s.query(PaperScanCandidate)
                .filter(PaperScanCandidate.account_id == account_id)
                .filter(PaperScanCandidate.scan_at < corte)
                .delete(synchronize_session=False)
            )
        return len(filas)
    except Exception:
        log.exception("scan_candidates: no se pudo registrar el scan de la cuenta %s", account_id)
        return 0
