"""Crédito de dividendos al motor vivo (tarea 222).

Qué hace y por qué
-------------------
Hasta acá el motor **no miraba dividendos**: la cuenta pasaba por el ex-date, veía caer
el precio y no recibía el efectivo. Medido sobre la cuenta 2 el 2026-09-21: **$322,77 en
3,05 meses = 2,54%/año**, el 62% de todo su P&L neto realizado. El harness, en cambio,
corre sobre barras ``auto_adjust=True`` —total-return— así que los cobra siempre.

Chapa eligió, con los costos de las dos opciones medidos delante (2026-09-25),
**acreditar el efectivo a la caja al ex-date** y **sólo hacia adelante**. Lo que eso
mueve, medido sobre la cuenta 2 antes de decidir:

* cierra el **99,1%** del desvío contra el harness (quedan ~$2,77 de los $322,77);
* mueve el sizing de las compras en **0,78% la mediana** (p90 2,5%), porque con
  ``equal_weight`` el target es ``available / len(picks)`` y la caja entra ahí;
* **no mueve los slots**: en toda la vida de la cuenta hubo **0** BUYs sin llenar, así
  que nunca faltó caja para un nombre. El enunciado de la tarea suponía que sí.

Lo que NO cierra, y va dicho
-----------------------------
``auto_adjust=True`` **reinvierte** el dividendo en el precio (la posición crece); la
caja acreditada queda quieta hasta la próxima compra. Sobre la cuenta 2 eso vale ~$2,77
— el 0,9% del desvío—, así que el desvío `dividendos` del registro de harness **se
achica y se re-describe, no se borra**.

Sólo hacia adelante, y cómo se implementa eso
-----------------------------------------------
La ventana de cada scan es ``(último scan, hoy]``. En el primer scan después de shipear
esto, el último scan es de ayer, así que **nada histórico se acredita** — que es la
decisión de Chapa. Y si la app estuvo cerrada dos semanas, la ventana las cubre: ese
dividendo se ganó igual. El ledger (``PaperDividendCredit``) hace el resto idempotente.

Nada de esto pega a la red: se lee ``dividend_calendar_cache``, que el warm-up del scan
puebla antes (mismo lugar donde ya se calienta el cache de barras).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from database.models import session_scope, utcnow_naive  # noqa: F401  (re-export para tests)

# Fecha centinela de `data/yahoo_finance._SIN_DIVIDENDOS`: "este ticker se chequeó y no
# paga". Se duplica el literal a propósito —`paper_trading/` no debe depender de
# `data/yahoo_finance`, que arrastra yfinance y la red— y un test fija que los tres
# literales del repo coincidan. Misma forma con que la 71 resolvió los de reproducción.
_SIN_DIVIDENDOS = "0000-00-00"


def dia(ts) -> str | None:
    """``YYYY-MM-DD`` de un timestamp/str, o ``None``."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d")
    s = str(ts)
    return s[:10] if len(s) >= 10 else None


def acciones_antes_del_ex_date(eventos: list[tuple[str, float]], ex_date: str) -> float:
    """Acciones en cartera **estrictamente antes** de ``ex_date``.

    ``eventos`` son ``(día, acciones con signo)`` — positivo BUY, negativo SELL.

    **La convención es la de la T220/T221 y es la misma en los dos lados:** hay que tener
    la acción *antes* del ex-date, así que un fill del mismo día **no cobra**. Es la
    convención con la que se midieron los $322,77 y con la que el panel los reproduce
    ticker por ticker, y que el motor use otra sería volver a tener dos aritméticas del
    mismo número — el defecto que las tareas 224 y 230 acaban de sacar del dashboard.
    """
    return sum(q for d, q in eventos if d < ex_date)


def creditos_pendientes(
    fills: list[tuple[str, str, float, str]],
    calendario: dict[str, list[tuple[str, float]]],
    ya_acreditados: set[tuple[str, str]],
    desde: str | None,
    hasta: str,
) -> list[tuple[str, str, float, float]]:
    """``(ticker, ex_date, acciones, $/acción)`` de lo que falta acreditar.

    **Función pura**: no toca la DB ni el reloj, así que la ventana y la convención de
    quién cobra se pueden testear sin montar un scan entero.

    ``fills`` son ``(ticker, side, acciones, filled_at)``; ``desde`` es el día del scan
    anterior y es **exclusivo** (ese día ya se procesó), ``hasta`` es hoy e **inclusivo**.
    ``desde=None`` ⇒ no hay scan previo ⇒ **no se acredita nada**: es el arranque de una
    cuenta, y además es lo que hace que «sólo hacia adelante» valga también el primer día
    que esto corre.
    """
    if not fills or desde is None:
        return []

    por_ticker: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for ticker, side, acciones, filled_at in fills:
        d = dia(filled_at)
        if d is None or not acciones:
            continue
        signo = 1.0 if str(side).upper() == "BUY" else -1.0
        por_ticker[str(ticker).upper()].append((d, signo * float(acciones)))

    pendientes: list[tuple[str, str, float, float]] = []
    for ticker, eventos in sorted(por_ticker.items()):
        for ex_date, monto in calendario.get(ticker, []):
            if ex_date == _SIN_DIVIDENDOS:
                # **Es redundante, y va dicho.** Probado por mutación: sacarlo no cambia
                # nada, y por DOS razones independientes — `"0000-00-00"` ordena antes
                # que cualquier fecha ISO, así que el filtro de ventana de abajo ya lo
                # descarta; y aunque entrara, ninguna compra puede ser anterior a esa
                # fecha, así que `acciones_antes_del_ex_date` daría 0. Se deja por
                # legibilidad —la fila necesita nombre donde se lee— pero un comentario
                # que dijera que ESTO es lo que la frena dirigiría mal a quien venga a
                # tocar el filtro. Es la misma conclusión a la que llegó la 221 con su
                # centinela, con una razón más.
                continue
            if not (desde < ex_date <= hasta):
                continue
            if (ticker, ex_date) in ya_acreditados:
                continue
            acciones = acciones_antes_del_ex_date(eventos, ex_date)
            if acciones > 0 and monto:
                pendientes.append((ticker, ex_date, acciones, float(monto)))
    return pendientes


def acreditar_dividendos(session, acct, desde: str | None, hasta: str) -> list[dict]:
    """Acredita a ``acct.cash`` los dividendos de la ventana y escribe el ledger.

    Devuelve una lista de dicts por crédito, para que el scan los pueda reportar. No
    pega a la red: el calendario tiene que estar en ``dividend_calendar_cache``, que el
    warm-up del scan puebla antes (``_warm_up_dividend_calendar``).

    Corre **adentro de la transacción del scan y antes de la estrategia**, a propósito:
    con ``equal_weight`` el target de cada compra es ``available / len(picks)`` y
    ``available`` sale de ``account.cash``, así que acreditar después dejaría la caja
    afuera del sizing del mismo scan — que es justamente lo que la opción (i) vino a
    cambiar.
    """
    from database.models import DividendCalendarCache
    from paper_trading.models import PaperDividendCredit, PaperOrder

    fills = [
        (o.ticker, o.side, float(o.fill_shares or 0.0), o.filled_at)
        for o in session.query(PaperOrder)
        .filter(PaperOrder.account_id == acct.id)
        .filter(PaperOrder.status == "filled")
        .filter(PaperOrder.fill_shares.isnot(None))
        .all()
    ]
    if not fills:
        return []

    tickers = sorted({str(t).upper() for t, *_ in fills})
    calendario: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for fila in session.query(DividendCalendarCache).filter(DividendCalendarCache.ticker.in_(tickers)).all():
        calendario[str(fila.ticker).upper()].append((fila.ex_date, float(fila.amount or 0.0)))

    ya = {
        (str(c.ticker).upper(), c.ex_date)
        for c in session.query(PaperDividendCredit).filter(PaperDividendCredit.account_id == acct.id).all()
    }

    creditos = []
    for ticker, ex_date, acciones, monto in creditos_pendientes(fills, calendario, ya, desde, hasta):
        efectivo = acciones * monto
        acct.cash = float(acct.cash) + efectivo
        session.add(
            PaperDividendCredit(
                account_id=acct.id,
                ticker=ticker,
                ex_date=ex_date,
                shares=acciones,
                amount_per_share=monto,
                cash=efectivo,
                credited_at=utcnow_naive(),
            )
        )
        creditos.append({"ticker": ticker, "ex_date": ex_date, "shares": acciones, "cash": efectivo})
    return creditos
